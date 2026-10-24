from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from models.database import Database

MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807


class SalesError(ValueError):
    pass


class SalesService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_customer(
        self,
        name: str,
        *,
        phone: str = "",
        address: str = "",
        credit_limit_paisa: int = 0,
    ) -> int:
        if not isinstance(name, str) or not name.strip():
            raise SalesError("Customer name is required")
        if len(name.strip()) > 255:
            raise SalesError("Customer name must be 255 characters or fewer")
        if not isinstance(phone, str) or not isinstance(address, str):
            raise SalesError("Customer phone and address must be text")
        credit_limit_paisa = self._integer(credit_limit_paisa, "Credit limit")
        with self.database.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO customers (name, phone, address, credit_limit_paisa) VALUES (?, ?, ?, ?)",
                (name.strip(), phone.strip(), address.strip(), credit_limit_paisa),
            )
            return int(cursor.lastrowid)

    def update_customer(self, customer_id: int, **values: Any) -> None:
        customer_id = self._integer(customer_id, "Customer id", minimum=1)
        allowed = {"name", "phone", "address", "credit_limit_paisa"}
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        for key in ("name", "phone", "address"):
            if key in updates:
                if not isinstance(updates[key], str):
                    raise SalesError(f"{key.title()} must be text")
                updates[key] = updates[key].strip()
        if "name" in updates and not updates["name"]:
            raise SalesError("Customer name is required")
        if "credit_limit_paisa" in updates:
            updates["credit_limit_paisa"] = self._integer(updates["credit_limit_paisa"], "Credit limit")
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"UPDATE customers SET {', '.join(f'{key} = ?' for key in updates)} WHERE id = ?",
                (*updates.values(), customer_id),
            )
            if cursor.rowcount != 1:
                raise SalesError("Customer was not found")

    def customers(self, search: str = "") -> list[dict[str, Any]]:
        if not isinstance(search, str):
            raise SalesError("Search text must be text")
        term = f"{search.strip()}%"
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT c.*, COALESCE(SUM(l.debit_paisa - l.credit_paisa), 0) AS balance_paisa
                   FROM customers c LEFT JOIN ledger_entries l
                     ON l.party_type = 'customer' AND l.party_id = c.id
                   WHERE c.name LIKE ? OR c.phone LIKE ?
                   GROUP BY c.id ORDER BY c.name COLLATE NOCASE""",
                (term, term),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_sale(
        self,
        bill_no: str,
        sale_date: date | str,
        payment_type: str,
        items: list[dict[str, Any]],
        *,
        customer_id: int | None = None,
        bill_discount_paisa: int = 0,
    ) -> int:
        if not isinstance(bill_no, str) or not bill_no.strip():
            raise SalesError("Bill number is required")
        bill_no = bill_no.strip()
        if len(bill_no) > 100:
            raise SalesError("Bill number must be 100 characters or fewer")
        if not isinstance(payment_type, str) or payment_type not in {"cash", "online", "credit"}:
            raise SalesError("Choose Cash, Online, or Credit payment")
        if payment_type == "credit" and customer_id is None:
            raise SalesError("Choose a customer for a credit sale")
        if customer_id is not None:
            customer_id = self._integer(customer_id, "Customer id", minimum=1)
        if not items:
            raise SalesError("Add at least one item to the bill")
        sold_on = self._iso_date(sale_date)
        bill_discount = self._integer(bill_discount_paisa, "Bill discount")
        prepared: list[dict[str, int]] = []
        gross_total = 0
        net_before_bill_discount = 0
        for item in items:
            medicine_id = self._integer(item["medicine_id"], "Medicine id", minimum=1)
            quantity = self._integer(item["quantity"], "Quantity", minimum=1)
            selling_rate = self._integer(item["selling_rate_paisa"], "Selling rate")
            line_discount = self._integer(item.get("discount_paisa", 0), "Line discount")
            gross = quantity * selling_rate
            if gross > MAX_SQLITE_INTEGER:
                raise SalesError("Line total exceeds the supported limit")
            if line_discount > gross:
                raise SalesError("Line discount cannot exceed the line total")
            with self.database.connect() as connection:
                medicine = connection.execute(
                    "SELECT id, prescription_required FROM medicines WHERE id = ?", (medicine_id,)
                ).fetchone()
            if medicine is None:
                raise SalesError("Medicine was not found")
            net = gross - line_discount
            gross_total += gross
            net_before_bill_discount += net
            if gross_total > MAX_SQLITE_INTEGER:
                raise SalesError("Bill total exceeds the supported limit")
            prepared.append({
                "medicine_id": medicine_id,
                "quantity": quantity,
                "selling_rate_paisa": selling_rate,
                "line_discount_paisa": line_discount,
                "gross_paisa": gross,
                "net_before_bill_discount_paisa": net,
                "prescription_required": int(medicine["prescription_required"]),
            })
        if bill_discount > net_before_bill_discount:
            raise SalesError("Bill discount cannot exceed the bill subtotal")
        if net_before_bill_discount - bill_discount <= 0:
            raise SalesError("Bill total must be greater than zero")

        remaining_discount = bill_discount
        for index, item in enumerate(prepared):
            if index == len(prepared) - 1:
                allocated = remaining_discount
            elif net_before_bill_discount:
                allocated = bill_discount * item["net_before_bill_discount_paisa"] // net_before_bill_discount
                remaining_discount -= allocated
            else:
                allocated = 0
            item["bill_discount_paisa"] = allocated
            item["total_discount_paisa"] = item["line_discount_paisa"] + allocated

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM sales WHERE bill_no = ? COLLATE NOCASE", (bill_no,)).fetchone():
                raise SalesError("This bill number already exists")
            customer = None
            if customer_id is not None:
                customer = connection.execute(
                    "SELECT id, credit_limit_paisa FROM customers WHERE id = ?", (customer_id,)
                ).fetchone()
                if customer is None:
                    raise SalesError("Customer was not found")
            bill_total = net_before_bill_discount - bill_discount
            cursor = connection.execute(
                """INSERT INTO sales
                   (bill_no, sale_date, customer_id, payment_type, subtotal_paisa, discount_paisa, total_paisa)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (bill_no, sold_on, customer_id, payment_type, gross_total,
                 gross_total - bill_total, bill_total),
            )
            sale_id = int(cursor.lastrowid)
            for item in prepared:
                batches = connection.execute(
                    """SELECT id, quantity, purchase_rate_paisa FROM batches
                       WHERE medicine_id = ? AND quantity > 0 AND expiry_date >= ?
                       ORDER BY expiry_date, id""",
                    (item["medicine_id"], sold_on),
                ).fetchall()
                available = sum(int(batch["quantity"]) for batch in batches)
                if available < item["quantity"]:
                    raise SalesError(f"Insufficient unexpired stock: {available} available")
                remaining_quantity = item["quantity"]
                allocations: list[tuple[Any, int]] = []
                for batch in batches:
                    used = min(remaining_quantity, int(batch["quantity"]))
                    if used:
                        allocations.append((batch, used))
                        remaining_quantity -= used
                    if remaining_quantity == 0:
                        break
                remaining_line_discount = item["total_discount_paisa"]
                for allocation_index, (batch, used) in enumerate(allocations):
                    if allocation_index == len(allocations) - 1:
                        discount_share = remaining_line_discount
                    else:
                        discount_share = item["total_discount_paisa"] * used // item["quantity"]
                        remaining_line_discount -= discount_share
                    line_total = used * item["selling_rate_paisa"] - discount_share
                    connection.execute(
                        "UPDATE batches SET quantity = quantity - ? WHERE id = ?",
                        (used, batch["id"]),
                    )
                    connection.execute(
                        """INSERT INTO sale_items
                           (sale_id, medicine_id, batch_id, quantity, selling_rate_paisa,
                            cost_rate_paisa, discount_paisa, line_total_paisa)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (sale_id, item["medicine_id"], batch["id"], used, item["selling_rate_paisa"],
                         batch["purchase_rate_paisa"], discount_share, line_total),
                    )
            if payment_type == "credit":
                connection.execute(
                    """INSERT INTO ledger_entries
                       (party_type, party_id, customer_id, entry_date, invoice_no, debit_paisa, remark)
                       VALUES ('customer', ?, ?, ?, ?, ?, ?)""",
                    (customer_id, customer_id, sold_on, bill_no, bill_total, "Credit sale"),
                )
            return sale_id

    def sales(self, search: str = "", *, limit: int = 250, offset: int = 0) -> list[dict[str, Any]]:
        limit = self._integer(limit, "Page size", minimum=1)
        offset = self._integer(offset, "Page offset")
        if limit > 500:
            raise SalesError("Page size cannot exceed 500 rows")
        if not isinstance(search, str):
            raise SalesError("Search text must be text")
        term = f"{search.strip()}%"
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT s.*, c.name AS customer_name, COUNT(*) OVER() AS total_count
                   FROM sales s LEFT JOIN customers c ON c.id = s.customer_id
                   WHERE s.bill_no LIKE ? OR c.name LIKE ? OR c.phone LIKE ?
                   ORDER BY s.sale_date DESC, s.id DESC LIMIT ? OFFSET ?""",
                (term, term, term, limit, offset),
            ).fetchall()
            return [dict(row) for row in rows]

    def sale_items(self, sale_id: int) -> list[dict[str, Any]]:
        sale_id = self._integer(sale_id, "Sale id", minimum=1)
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT si.*, m.name AS medicine_name, b.batch_number
                   FROM sale_items si JOIN medicines m ON m.id = si.medicine_id
                   JOIN batches b ON b.id = si.batch_id WHERE si.sale_id = ? ORDER BY si.id""",
                (sale_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def return_items(
        self,
        sale_id: int,
        items: list[dict[str, int]],
        *,
        return_date: date | str | None = None,
        remark: str = "",
    ) -> int:
        sale_id = self._integer(sale_id, "Sale id", minimum=1)
        if not items:
            raise SalesError("Choose at least one item to return")
        if not isinstance(remark, str) or len(remark) > 1000:
            raise SalesError("Return remark is invalid or too long")
        returned_on = self._iso_date(return_date or date.today())
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            sale = connection.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if sale is None:
                raise SalesError("Sale was not found")
            prepared: list[dict[str, int]] = []
            total_return = 0
            for item in items:
                item_id = self._integer(item["sale_item_id"], "Sale item id", minimum=1)
                quantity = self._integer(item["quantity"], "Return quantity", minimum=1)
                sale_item = connection.execute(
                    "SELECT * FROM sale_items WHERE id = ? AND sale_id = ?", (item_id, sale_id)
                ).fetchone()
                if sale_item is None:
                    raise SalesError("Sale item was not found")
                remaining_quantity = int(sale_item["quantity"]) - int(sale_item["returned_quantity"])
                if quantity > remaining_quantity:
                    raise SalesError("Return quantity exceeds the unreturned quantity")
                prior_returns = connection.execute(
                    "SELECT COALESCE(SUM(amount_paisa), 0) FROM sale_return_items WHERE sale_item_id = ?",
                    (item_id,),
                ).fetchone()[0]
                remaining_amount = int(sale_item["line_total_paisa"]) - int(prior_returns)
                amount = remaining_amount if quantity == remaining_quantity else (remaining_amount * quantity + remaining_quantity // 2) // remaining_quantity
                if amount <= 0:
                    raise SalesError("Return amount must be greater than zero")
                prepared.append({"sale_item_id": item_id, "quantity": quantity, "amount_paisa": amount,
                                 "batch_id": int(sale_item["batch_id"]), "returned_quantity": int(sale_item["returned_quantity"])})
                total_return += amount
            return_cursor = connection.execute(
                "INSERT INTO sale_returns (sale_id, return_date, total_paisa, remark) VALUES (?, ?, ?, ?)",
                (sale_id, returned_on, total_return, remark.strip()),
            )
            return_id = int(return_cursor.lastrowid)
            for item in prepared:
                connection.execute(
                    "INSERT INTO sale_return_items (return_id, sale_item_id, quantity, amount_paisa) VALUES (?, ?, ?, ?)",
                    (return_id, item["sale_item_id"], item["quantity"], item["amount_paisa"]),
                )
                connection.execute(
                    "UPDATE sale_items SET returned_quantity = returned_quantity + ? WHERE id = ?",
                    (item["quantity"], item["sale_item_id"]),
                )
                connection.execute(
                    "UPDATE batches SET quantity = quantity + ? WHERE id = ?",
                    (item["quantity"], item["batch_id"]),
                )
            if sale["customer_id"] is not None and sale["payment_type"] == "credit":
                connection.execute(
                    """INSERT INTO ledger_entries
                       (party_type, party_id, customer_id, entry_date, payment_date, credit_paisa,
                        linked_invoice_no, payment_method, remark)
                       VALUES ('customer', ?, ?, ?, ?, ?, ?, 'return', ?)""",
                    (sale["customer_id"], sale["customer_id"], returned_on, returned_on,
                     total_return, sale["bill_no"], f"Sales return: {remark.strip()}"),
                )
            all_items = connection.execute(
                "SELECT quantity, returned_quantity FROM sale_items WHERE sale_id = ?", (sale_id,)
            ).fetchall()
            fully_returned = all(int(row["quantity"]) == int(row["returned_quantity"]) for row in all_items)
            connection.execute(
                "UPDATE sales SET status = ? WHERE id = ?",
                ("returned" if fully_returned else "partial_return", sale_id),
            )
            return return_id

    def hold_bill(self, bill_no: str, payload: dict[str, Any]) -> int:
        if not isinstance(bill_no, str) or not bill_no.strip():
            raise SalesError("Bill number is required")
        try:
            serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        except (TypeError, ValueError) as error:
            raise SalesError("Bill contains unsupported data") from error
        if len(serialized) > 1_000_000:
            raise SalesError("Held bill exceeds the supported size")
        with self.database.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO held_bills (bill_no, payload_json) VALUES (?, ?)", (bill_no.strip(), serialized)
            )
            return int(cursor.lastrowid)

    def held_bills(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT id, bill_no, saved_at FROM held_bills ORDER BY saved_at DESC, id DESC"
            ).fetchall()]

    def resume_bill(self, held_id: int) -> dict[str, Any]:
        held_id = self._integer(held_id, "Held bill id", minimum=1)
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM held_bills WHERE id = ?", (held_id,)).fetchone()
            if row is None:
                raise SalesError("Held bill was not found")
            return {"id": int(row["id"]), "bill_no": row["bill_no"], "payload": json.loads(row["payload_json"])}

    def delete_held_bill(self, held_id: int) -> None:
        held_id = self._integer(held_id, "Held bill id", minimum=1)
        with self.database.connect() as connection:
            connection.execute("DELETE FROM held_bills WHERE id = ?", (held_id,))

    @staticmethod
    def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
        if type(value) is not int:
            raise SalesError(f"{label} must be a whole number")
        if value < minimum or value > MAX_SQLITE_INTEGER:
            raise SalesError(f"{label} is outside the supported range")
        return value

    @staticmethod
    def _iso_date(value: date | str) -> str:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        try:
            return date.fromisoformat(value).isoformat()
        except (TypeError, ValueError) as error:
            raise SalesError("Enter a valid date in YYYY-MM-DD format") from error
