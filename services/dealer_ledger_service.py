from __future__ import annotations

from datetime import date, datetime
from typing import Any

from models.database import Database


class LedgerError(ValueError):
    pass


MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807


class DealerLedgerService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_dealer(
        self,
        name: str,
        *,
        company: str = "",
        contact_person: str = "",
        phone: str = "",
        address: str = "",
        pan_vat: str = "",
        credit_terms_days: int = 0,
    ) -> int:
        if not isinstance(name, str) or not name.strip():
            raise LedgerError("Dealer name is required")
        if len(name.strip()) > 255:
            raise LedgerError("Dealer name must be 255 characters or fewer")
        credit_terms_days = self._integer(credit_terms_days, "Credit terms")
        text_values = self._dealer_text_values({
            "company": company, "contact_person": contact_person, "phone": phone,
            "address": address, "pan_vat": pan_vat,
        })
        with self.database.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO dealers (name, company, contact_person, phone, address, pan_vat, credit_terms_days)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (name.strip(), text_values["company"], text_values["contact_person"], text_values["phone"],
                 text_values["address"], text_values["pan_vat"], credit_terms_days),
            )
            return int(cursor.lastrowid)

    def update_dealer(self, dealer_id: int, **values: Any) -> None:
        dealer_id = self._integer(dealer_id, "Dealer id", minimum=1)
        allowed = {"name", "company", "contact_person", "phone", "address", "pan_vat", "credit_terms_days"}
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        if "name" in updates:
            if not isinstance(updates["name"], str) or not updates["name"].strip():
                raise LedgerError("Dealer name is required")
            updates["name"] = updates["name"].strip()
            if len(updates["name"]) > 255:
                raise LedgerError("Dealer name must be 255 characters or fewer")
        text_fields = {key: value for key, value in updates.items() if key != "credit_terms_days" and key != "name"}
        updates.update(self._dealer_text_values(text_fields))
        if "credit_terms_days" in updates:
            updates["credit_terms_days"] = self._integer(updates["credit_terms_days"], "Credit terms")
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"UPDATE dealers SET {', '.join(f'{key} = ?' for key in updates)} WHERE id = ?",
                (*updates.values(), dealer_id),
            )
            if cursor.rowcount != 1:
                raise LedgerError("Dealer was not found")

    def dealers(self, search: str = "") -> list[dict[str, Any]]:
        term = f"%{search.strip()}%"
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT d.*,
                          COALESCE(SUM(l.debit_paisa), 0) AS total_billed_paisa,
                          COALESCE(SUM(l.credit_paisa), 0) AS total_paid_paisa,
                          COALESCE(SUM(l.debit_paisa - l.credit_paisa), 0) AS balance_paisa
                   FROM dealers d LEFT JOIN ledger_entries l ON l.party_id = d.id AND l.party_type = 'dealer'
                   WHERE d.name LIKE ? OR d.company LIKE ? OR d.phone LIKE ?
                   GROUP BY d.id ORDER BY d.name COLLATE NOCASE""",
                (term, term, term),
            ).fetchall()
            return [dict(row) for row in rows]

    def add_invoice(
        self,
        dealer_id: int,
        invoice_date: date | str,
        invoice_no: str,
        debit_paisa: int,
        *,
        due_date: date | str | None = None,
        remark: str = "",
    ) -> int:
        dealer_id = self._integer(dealer_id, "Dealer id", minimum=1)
        debit_paisa = self._integer(debit_paisa, "Invoice amount", minimum=1)
        if not isinstance(invoice_no, str) or not invoice_no.strip():
            raise LedgerError("Invoice number is required")
        if not isinstance(remark, str):
            raise LedgerError("Remark must be text")
        if len(invoice_no.strip()) > 100:
            raise LedgerError("Invoice number must be 100 characters or fewer")
        if len(remark) > 1000:
            raise LedgerError("Remark must be 1000 characters or fewer")
        invoice = invoice_no.strip()
        entry_date = self._iso_date(invoice_date)
        due = self._iso_date(due_date) if due_date else None
        if due and due < entry_date:
            raise LedgerError("Due date cannot be before the invoice date")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                """SELECT 1 FROM ledger_entries WHERE party_type = 'dealer' AND party_id = ?
                   AND invoice_no = ? COLLATE NOCASE LIMIT 1""",
                (dealer_id, invoice),
            ).fetchone():
                raise LedgerError("This dealer invoice number already exists")
            cursor = connection.execute(
                """INSERT INTO ledger_entries
                         (party_type, party_id, dealer_id, entry_date, invoice_no, debit_paisa, due_date, remark)
                         VALUES ('dealer', ?, ?, ?, ?, ?, ?, ?)""",
                     (dealer_id, dealer_id, entry_date, invoice, debit_paisa, due, remark.strip()),
            )
            return int(cursor.lastrowid)

    def add_payment(
        self,
        dealer_id: int,
        payment_date: date | str,
        credit_paisa: int,
        *,
        linked_invoice_no: str = "",
        payment_method: str = "cash",
        remark: str = "",
    ) -> int:
        dealer_id = self._integer(dealer_id, "Dealer id", minimum=1)
        credit_paisa = self._integer(credit_paisa, "Payment amount", minimum=1)
        if not isinstance(linked_invoice_no, str):
            raise LedgerError("Linked invoice number must be text")
        if not isinstance(payment_method, str) or payment_method not in {"cash", "cheque", "bank", "QR"}:
            raise LedgerError("Choose a valid payment method")
        if not isinstance(remark, str):
            raise LedgerError("Remark must be text")
        if len(linked_invoice_no) > 100 or len(remark) > 1000:
            raise LedgerError("Linked invoice or remark is too long")
        paid_on = self._iso_date(payment_date)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            linked_invoice_text = linked_invoice_no.strip()
            invoice = None
            if linked_invoice_text:
                invoice = connection.execute(
                    """SELECT invoice_no, debit_paisa FROM ledger_entries
                       WHERE party_type = 'dealer' AND party_id = ? AND debit_paisa > 0
                         AND invoice_no = ? COLLATE NOCASE LIMIT 1""",
                    (dealer_id, linked_invoice_text),
                ).fetchone()
                if invoice is None:
                    raise LedgerError("Linked invoice was not found for this dealer")
                already_paid = connection.execute(
                    """SELECT COALESCE(SUM(credit_paisa), 0) FROM ledger_entries
                       WHERE party_type = 'dealer' AND party_id = ?
                         AND linked_invoice_no = ? COLLATE NOCASE""",
                    (dealer_id, invoice["invoice_no"]),
                ).fetchone()[0]
                if credit_paisa > int(invoice["debit_paisa"]) - int(already_paid):
                    raise LedgerError("Payment exceeds the remaining invoice balance")
            cursor = connection.execute(
                """INSERT INTO ledger_entries
                         (party_type, party_id, dealer_id, entry_date, payment_date, credit_paisa, linked_invoice_no, payment_method, remark)
                         VALUES ('dealer', ?, ?, ?, ?, ?, ?, ?, ?)""",
                     (dealer_id, dealer_id, paid_on, paid_on, credit_paisa, invoice["invoice_no"] if invoice else None,
                 payment_method, remark.strip()),
            )
            return int(cursor.lastrowid)

    def ledger(
        self,
        dealer_id: int,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        *,
        limit: int | None = 250,
        offset: int = 0,
    ) -> dict[str, Any]:
        dealer_id = self._integer(dealer_id, "Dealer id", minimum=1)
        if limit is not None:
            limit = self._integer(limit, "Page size", minimum=1)
            if limit > 500:
                raise LedgerError("Page size cannot exceed 500 rows")
        offset = self._integer(offset, "Page offset")
        start = self._iso_date(start_date) if start_date else "0001-01-01"
        end = self._iso_date(end_date) if end_date else "9999-12-31"
        if start > end:
            raise LedgerError("Start date must be on or before end date")
        with self.database.connect() as connection:
            dealer = connection.execute("SELECT * FROM dealers WHERE id = ?", (dealer_id,)).fetchone()
            if dealer is None:
                raise LedgerError("Dealer was not found")
            opening = int(connection.execute(
                """SELECT COALESCE(SUM(debit_paisa - credit_paisa), 0) FROM ledger_entries
                   WHERE party_type = 'dealer' AND party_id = ?
                     AND COALESCE(payment_date, entry_date) < ?""",
                (dealer_id, start),
            ).fetchone()[0])
            totals = connection.execute(
                """SELECT COUNT(*) AS row_count,
                          COALESCE(SUM(debit_paisa), 0) AS debit_total,
                          COALESCE(SUM(credit_paisa), 0) AS credit_total
                   FROM ledger_entries WHERE party_type = 'dealer' AND party_id = ?
                     AND COALESCE(payment_date, entry_date) >= ?
                     AND COALESCE(payment_date, entry_date) <= ?""",
                (dealer_id, start, end),
            ).fetchone()
            page_opening = opening
            if offset:
                page_opening += int(connection.execute(
                    """SELECT COALESCE(SUM(debit_paisa - credit_paisa), 0) FROM (
                           SELECT debit_paisa, credit_paisa FROM ledger_entries
                           WHERE party_type = 'dealer' AND party_id = ?
                             AND COALESCE(payment_date, entry_date) >= ?
                             AND COALESCE(payment_date, entry_date) <= ?
                           ORDER BY COALESCE(payment_date, entry_date), id LIMIT ?
                       )""",
                    (dealer_id, start, end, offset),
                ).fetchone()[0])
            query = """SELECT * FROM ledger_entries WHERE party_type = 'dealer' AND party_id = ?
                       AND COALESCE(payment_date, entry_date) >= ?
                       AND COALESCE(payment_date, entry_date) <= ?
                       ORDER BY COALESCE(payment_date, entry_date), id"""
            params: tuple[Any, ...] = (dealer_id, start, end)
            if limit is not None:
                query += " LIMIT ? OFFSET ?"
                params += (limit, offset)
            records = connection.execute(query, params).fetchall()
        balance = page_opening
        entries: list[dict[str, Any]] = []
        for row in records:
            debit = int(row["debit_paisa"])
            credit = int(row["credit_paisa"])
            balance += debit - credit
            entries.append({
                **dict(row),
                "display_date": row["entry_date"] if debit else "",
                "display_payment_date": row["payment_date"] or "",
                "balance_paisa": balance,
            })
        return {
            "dealer": dict(dealer),
            "start_date": start,
            "end_date": end,
            "opening_balance_paisa": opening,
            "page_opening_balance_paisa": page_opening,
            "entries": entries,
            "total_count": int(totals["row_count"]),
            "total_debit_paisa": int(totals["debit_total"]),
            "total_credit_paisa": int(totals["credit_total"]),
            "closing_balance_paisa": opening + int(totals["debit_total"]) - int(totals["credit_total"]),
        }

    @staticmethod
    def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
        if type(value) is not int:
            raise LedgerError(f"{label} must be a whole number")
        if value < minimum or value > MAX_SQLITE_INTEGER:
            if minimum == 1 and value < 1:
                raise LedgerError(f"{label} must be greater than zero")
            raise LedgerError(f"{label} is outside the supported range")
        return value

    @staticmethod
    def _dealer_text_values(values: dict[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        for key, value in values.items():
            if not isinstance(value, str):
                raise LedgerError(f"{key.replace('_', ' ').title()} must be text")
            result[key] = value.strip()
        return result

    @staticmethod
    def _iso_date(value: date | str) -> str:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        try:
            return date.fromisoformat(value).isoformat()
        except (TypeError, ValueError) as error:
            raise LedgerError("Enter a valid date in YYYY-MM-DD format") from error
