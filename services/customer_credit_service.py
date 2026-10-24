from __future__ import annotations

from datetime import date, datetime
from typing import Any
from urllib.parse import quote

from models.database import Database
from services.sales_service import SalesError, SalesService


class CustomerCreditService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.sales = SalesService(database)

    def customers(self, search: str = "") -> list[dict[str, Any]]:
        return self.sales.customers(search)

    def customer_ledger(
        self,
        customer_id: int,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        *,
        limit: int | None = 250,
        offset: int = 0,
    ) -> dict[str, Any]:
        customer_id = self.sales._integer(customer_id, "Customer id", minimum=1)
        if limit is not None:
            limit = self.sales._integer(limit, "Page size", minimum=1)
            if limit > 500:
                raise SalesError("Page size cannot exceed 500 rows")
        offset = self.sales._integer(offset, "Page offset")
        start = self._iso_date(start_date) if start_date else "0001-01-01"
        end = self._iso_date(end_date) if end_date else "9999-12-31"
        if start > end:
            raise SalesError("Start date must be on or before end date")
        with self.database.connect() as connection:
            customer = connection.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
            if customer is None:
                raise SalesError("Customer was not found")
            opening = int(connection.execute(
                """SELECT COALESCE(SUM(debit_paisa - credit_paisa), 0) FROM ledger_entries
                   WHERE party_type = 'customer' AND party_id = ?
                     AND COALESCE(payment_date, entry_date) < ?""",
                (customer_id, start),
            ).fetchone()[0])
            totals = connection.execute(
                """SELECT COUNT(*) AS row_count, COALESCE(SUM(debit_paisa), 0) AS debit_total,
                          COALESCE(SUM(credit_paisa), 0) AS credit_total
                   FROM ledger_entries WHERE party_type = 'customer' AND party_id = ?
                     AND COALESCE(payment_date, entry_date) >= ? AND COALESCE(payment_date, entry_date) <= ?""",
                (customer_id, start, end),
            ).fetchone()
            page_opening = opening
            if offset:
                page_opening += int(connection.execute(
                    """SELECT COALESCE(SUM(debit_paisa - credit_paisa), 0) FROM (
                           SELECT debit_paisa, credit_paisa FROM ledger_entries
                           WHERE party_type = 'customer' AND party_id = ?
                             AND COALESCE(payment_date, entry_date) >= ? AND COALESCE(payment_date, entry_date) <= ?
                           ORDER BY COALESCE(payment_date, entry_date), id LIMIT ?
                       )""",
                    (customer_id, start, end, offset),
                ).fetchone()[0])
            query = """SELECT * FROM ledger_entries WHERE party_type = 'customer' AND party_id = ?
                       AND COALESCE(payment_date, entry_date) >= ? AND COALESCE(payment_date, entry_date) <= ?
                       ORDER BY COALESCE(payment_date, entry_date), id"""
            params: tuple[Any, ...] = (customer_id, start, end)
            if limit is not None:
                query += " LIMIT ? OFFSET ?"
                params += (limit, offset)
            entries = connection.execute(query, params).fetchall()
        balance = page_opening
        result = []
        for row in entries:
            balance += int(row["debit_paisa"]) - int(row["credit_paisa"])
            result.append({
                **dict(row),
                "display_date": row["entry_date"] if row["debit_paisa"] else "",
                "display_payment_date": row["payment_date"] or "",
                "balance_paisa": balance,
            })
        return {
            "customer": dict(customer), "start_date": start, "end_date": end,
            "opening_balance_paisa": opening, "page_opening_balance_paisa": page_opening,
            "entries": result, "total_count": int(totals["row_count"]),
            "total_debit_paisa": int(totals["debit_total"]),
            "total_credit_paisa": int(totals["credit_total"]),
            "closing_balance_paisa": opening + int(totals["debit_total"]) - int(totals["credit_total"]),
        }

    def receive_payment(
        self,
        customer_id: int,
        payment_date: date | str,
        amount_paisa: int,
        *,
        linked_bill_no: str = "",
        payment_method: str = "cash",
        remark: str = "",
    ) -> int:
        customer_id = self.sales._integer(customer_id, "Customer id", minimum=1)
        amount_paisa = self.sales._integer(amount_paisa, "Payment amount", minimum=1)
        if not isinstance(linked_bill_no, str) or len(linked_bill_no) > 100:
            raise SalesError("Linked bill number is invalid")
        if not isinstance(payment_method, str) or payment_method not in {"cash", "online", "bank", "QR"}:
            raise SalesError("Choose a valid payment method")
        if not isinstance(remark, str) or len(remark) > 1000:
            raise SalesError("Payment remark is invalid")
        paid_on = self._iso_date(payment_date)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone() is None:
                raise SalesError("Customer was not found")
            linked_bill = linked_bill_no.strip()
            if linked_bill:
                bill = connection.execute(
                    "SELECT bill_no, total_paisa FROM sales WHERE customer_id = ? AND bill_no = ? COLLATE NOCASE AND payment_type = 'credit'",
                    (customer_id, linked_bill),
                ).fetchone()
                if bill is None:
                    raise SalesError("Credit bill was not found for this customer")
                paid = connection.execute(
                    """SELECT COALESCE(SUM(credit_paisa), 0) FROM ledger_entries
                       WHERE party_type = 'customer' AND party_id = ? AND linked_invoice_no = ? COLLATE NOCASE""",
                    (customer_id, bill["bill_no"]),
                ).fetchone()[0]
                if amount_paisa > int(bill["total_paisa"]) - int(paid):
                    raise SalesError("Payment exceeds the remaining bill balance")
            cursor = connection.execute(
                """INSERT INTO ledger_entries
                   (party_type, party_id, customer_id, entry_date, payment_date, credit_paisa,
                    linked_invoice_no, payment_method, remark)
                   VALUES ('customer', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (customer_id, customer_id, paid_on, paid_on, amount_paisa,
                 bill["bill_no"] if linked_bill else None, payment_method, remark.strip()),
            )
            return int(cursor.lastrowid)

    def ageing(self, *, today: date | None = None) -> dict[str, list[dict[str, Any]]]:
        today = today or date.today()
        buckets = {"0-30": [], "31-60": [], "61-90": [], "90+": []}
        with self.database.connect() as connection:
            customers = connection.execute("SELECT id, name, phone FROM customers ORDER BY name COLLATE NOCASE").fetchall()
            for customer in customers:
                debits = connection.execute(
                    """SELECT invoice_no, entry_date, debit_paisa FROM ledger_entries
                       WHERE party_type = 'customer' AND party_id = ? AND debit_paisa > 0
                       ORDER BY entry_date, id""",
                    (customer["id"],),
                ).fetchall()
                credits = connection.execute(
                    """SELECT linked_invoice_no, credit_paisa FROM ledger_entries
                       WHERE party_type = 'customer' AND party_id = ? AND credit_paisa > 0
                       ORDER BY COALESCE(payment_date, entry_date), id""",
                    (customer["id"],),
                ).fetchall()
                invoice_balances = [{"invoice_no": row["invoice_no"], "entry_date": row["entry_date"],
                                     "balance": int(row["debit_paisa"])} for row in debits]
                for credit in credits:
                    remaining = int(credit["credit_paisa"])
                    linked = credit["linked_invoice_no"]
                    targets = [row for row in invoice_balances if row["invoice_no"] == linked] if linked else invoice_balances
                    for invoice in targets:
                        applied = min(remaining, invoice["balance"])
                        invoice["balance"] -= applied
                        remaining -= applied
                        if remaining <= 0:
                            break
                for invoice in invoice_balances:
                    if invoice["balance"] <= 0:
                        continue
                    age = max(0, (today - date.fromisoformat(invoice["entry_date"])).days)
                    bucket = "0-30" if age <= 30 else "31-60" if age <= 60 else "61-90" if age <= 90 else "90+"
                    buckets[bucket].append({
                        "customer_id": int(customer["id"]), "customer_name": customer["name"],
                        "phone": customer["phone"], "invoice_no": invoice["invoice_no"],
                        "date": invoice["entry_date"], "age_days": age, "balance_paisa": invoice["balance"],
                    })
        return buckets

    def reminder_url(self, customer_id: int) -> str:
        customer_id = self.sales._integer(customer_id, "Customer id", minimum=1)
        with self.database.connect() as connection:
            customer = connection.execute(
                """SELECT c.name, c.phone, COALESCE(SUM(l.debit_paisa-l.credit_paisa),0) AS balance
                   FROM customers c LEFT JOIN ledger_entries l ON l.party_type='customer' AND l.party_id=c.id
                   WHERE c.id=? GROUP BY c.id""", (customer_id,),
            ).fetchone()
        if customer is None:
            raise SalesError("Customer was not found")
        message = f"Namaste {customer['name']}, your outstanding balance at Dipesh Medical Hall is Rs. {customer['balance'] / 100:,.2f}. Thank you."
        recipient = customer["phone"].strip()
        return f"sms:{recipient}?body={quote(message)}" if recipient else f"sms:?body={quote(message)}"

    @staticmethod
    def _iso_date(value: date | str) -> str:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        try:
            return date.fromisoformat(value).isoformat()
        except (TypeError, ValueError) as error:
            raise SalesError("Enter a valid date in YYYY-MM-DD format") from error
