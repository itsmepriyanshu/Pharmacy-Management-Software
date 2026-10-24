from __future__ import annotations

from datetime import date
from typing import Any

from models.database import Database


class PurchaseError(ValueError):
    pass


MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807


class PurchaseService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_purchase(
        self,
        dealer_id: int,
        invoice_number: str,
        invoice_date: date | str,
        payment_type: str,
        items: list[dict[str, Any]],
        *,
        due_date: date | str | None = None,
        remark: str = "",
    ) -> int:
        dealer_id = self._integer(dealer_id, "Dealer id", minimum=1)
        if not isinstance(invoice_number, str):
            raise PurchaseError("Invoice number is required")
        invoice_no = invoice_number.strip()
        if not invoice_no:
            raise PurchaseError("Invoice number is required")
        if not isinstance(payment_type, str) or payment_type not in {"cash", "credit"}:
            raise PurchaseError("Payment type must be cash or credit")
        if not isinstance(remark, str):
            raise PurchaseError("Remark must be text")
        if not items:
            raise PurchaseError("Add at least one item to the purchase")
        invoice_day = self._iso_date(invoice_date)
        due_day = self._iso_date(due_date) if due_date else None
        if due_day and due_day < invoice_day:
            raise PurchaseError("Due date cannot be before the invoice date")
        prepared: list[dict[str, Any]] = []
        total = 0
        for item in items:
            quantity = self._integer(item["quantity"], "Quantity", minimum=1)
            free_quantity = self._integer(item.get("free_quantity", 0), "Free quantity")
            rate = self._integer(item["purchase_rate_paisa"], "Purchase rate")
            discount = self._integer(item.get("discount_paisa", 0), "Discount")
            tax = self._integer(item.get("tax_paisa", 0), "Tax")
            selling_rate = self._integer(item.get("selling_rate_paisa", 0), "Selling rate")
            medicine_id = self._integer(item["medicine_id"], "Medicine id", minimum=1)
            if quantity <= 0 or free_quantity < 0 or min(rate, discount, tax, selling_rate) < 0:
                raise PurchaseError("Quantities and rates must be valid non-negative values; billed quantity must be positive")
            gross = quantity * rate
            stock_added = quantity + free_quantity
            if gross > MAX_SQLITE_INTEGER or stock_added > MAX_SQLITE_INTEGER:
                raise PurchaseError("Purchase quantities or amounts exceed the supported limit")
            if discount > gross:
                raise PurchaseError("Line discount cannot exceed the billed item amount")
            subtotal = gross - discount + tax
            if subtotal > MAX_SQLITE_INTEGER:
                raise PurchaseError("Purchase line amount exceeds the supported limit")
            expiry = self._iso_date(item["expiry_date"])
            manufacturing = self._iso_date(item["manufacturing_date"]) if item.get("manufacturing_date") else None
            if manufacturing and manufacturing > expiry:
                raise PurchaseError("Manufacturing date must be before expiry date")
            batch_number = item.get("batch_number")
            if not isinstance(batch_number, str) or not batch_number.strip():
                raise PurchaseError("Batch number is required")
            prepared.append({
                **item,
                "medicine_id": medicine_id,
                "batch_number": batch_number.strip(),
                "expiry_date": expiry,
                "manufacturing_date": manufacturing,
                "quantity": quantity,
                "free_quantity": free_quantity,
                "purchase_rate_paisa": rate,
                "selling_rate_paisa": selling_rate,
                "discount_paisa": discount,
                "tax_paisa": tax,
                "subtotal_paisa": subtotal,
            })
            total += subtotal
            if total > MAX_SQLITE_INTEGER:
                raise PurchaseError("Purchase total exceeds the supported limit")
        if total <= 0:
            raise PurchaseError("Purchase total must be greater than zero")

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                """SELECT 1 FROM purchases WHERE dealer_id = ? AND invoice_number = ? COLLATE NOCASE
                   UNION ALL
                   SELECT 1 FROM ledger_entries WHERE party_type = 'dealer' AND party_id = ?
                     AND invoice_no = ? COLLATE NOCASE LIMIT 1""",
                (dealer_id, invoice_no, dealer_id, invoice_no),
            ).fetchone()
            if duplicate:
                raise PurchaseError("This dealer invoice number already exists")
            cursor = connection.execute(
                """INSERT INTO purchases (dealer_id, invoice_number, invoice_date, due_date, total_paisa, payment_type, remark)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (dealer_id, invoice_no, invoice_day, due_day, total, payment_type, remark.strip()),
            )
            purchase_id = int(cursor.lastrowid)
            for item in prepared:
                medicine_id = int(item["medicine_id"])
                stock_added = item["quantity"] + item["free_quantity"]
                batch = connection.execute(
                    "SELECT id, expiry_date, manufacturing_date, quantity, purchase_rate_paisa FROM batches WHERE medicine_id = ? AND batch_number = ?",
                    (medicine_id, item["batch_number"]),
                ).fetchone()
                if batch:
                    if batch["expiry_date"] != item["expiry_date"]:
                        raise PurchaseError("This batch number already exists with a different expiry date")
                    if batch["manufacturing_date"] != item["manufacturing_date"]:
                        raise PurchaseError("This batch number already exists with a different manufacturing date")
                    new_quantity = int(batch["quantity"]) + stock_added
                    new_cost = int(batch["quantity"]) * int(batch["purchase_rate_paisa"]) + item["subtotal_paisa"]
                    if new_quantity > MAX_SQLITE_INTEGER or new_cost > MAX_SQLITE_INTEGER:
                        raise PurchaseError("Updated batch stock value exceeds the supported limit")
                    average_rate = (new_cost + new_quantity // 2) // new_quantity if new_quantity else 0
                    batch_id = int(batch["id"])
                    connection.execute(
                        "UPDATE batches SET quantity = ?, purchase_rate_paisa = ?, selling_rate_paisa = ? WHERE id = ?",
                        (new_quantity, average_rate, item["selling_rate_paisa"], batch_id),
                    )
                else:
                    batch_cursor = connection.execute(
                        """INSERT INTO batches
                           (medicine_id, batch_number, manufacturing_date, expiry_date, quantity, purchase_rate_paisa, selling_rate_paisa)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (medicine_id, item["batch_number"], item["manufacturing_date"], item["expiry_date"], stock_added,
                         (item["subtotal_paisa"] + stock_added // 2) // stock_added, item["selling_rate_paisa"]),
                    )
                    batch_id = int(batch_cursor.lastrowid)
                connection.execute(
                    """INSERT INTO purchase_items
                       (purchase_id, medicine_id, batch_id, quantity, free_quantity, purchase_rate_paisa,
                        discount_paisa, tax_paisa, subtotal_paisa)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (purchase_id, medicine_id, batch_id, item["quantity"], item["free_quantity"],
                     item["purchase_rate_paisa"], item["discount_paisa"], item["tax_paisa"], item["subtotal_paisa"]),
                )
            connection.execute(
                """INSERT INTO ledger_entries
                         (party_type, party_id, dealer_id, entry_date, invoice_no, debit_paisa, due_date, remark)
                           VALUES ('dealer', ?, ?, ?, ?, ?, ?, ?)""",
                     (dealer_id, dealer_id, invoice_day, invoice_no, total, due_day, remark.strip()),
            )
            if payment_type == "cash":
                connection.execute(
                    """INSERT INTO ledger_entries
                              (party_type, party_id, dealer_id, entry_date, payment_date, credit_paisa,
                        linked_invoice_no, payment_method, remark)
                              VALUES ('dealer', ?, ?, ?, ?, ?, ?, 'cash', ?)""",
                          (dealer_id, dealer_id, invoice_day, invoice_day, total, invoice_no, f"Paid with invoice {invoice_no}"),
                )
            return purchase_id

    def purchases(self, search: str = "", *, limit: int = 250, offset: int = 0) -> list[dict[str, Any]]:
        limit = self._integer(limit, "Page size", minimum=1)
        offset = self._integer(offset, "Page offset")
        if limit > 500:
            raise PurchaseError("Page size cannot exceed 500 rows")
        if not isinstance(search, str):
            raise PurchaseError("Search text must be text")
        term = f"{search.strip()}%"
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT p.*, d.name AS dealer_name, COUNT(*) OVER() AS total_count FROM purchases p
                   JOIN dealers d ON d.id = p.dealer_id
                   WHERE p.invoice_number LIKE ? OR d.name LIKE ?
                   ORDER BY p.invoice_date DESC, p.id DESC LIMIT ? OFFSET ?""",
                (term, term, limit, offset),
            ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
        if type(value) is not int:
            raise PurchaseError(f"{label} must be a whole number")
        if value < minimum or value > MAX_SQLITE_INTEGER:
            if minimum == 1 and value < 1:
                raise PurchaseError(f"{label} must be greater than zero")
            raise PurchaseError(f"{label} is outside the supported range")
        return value

    @staticmethod
    def _iso_date(value: date | str) -> str:
        if isinstance(value, date):
            return value.isoformat()
        try:
            return date.fromisoformat(value).isoformat()
        except (TypeError, ValueError) as error:
            raise PurchaseError("Enter a valid date in YYYY-MM-DD format") from error
