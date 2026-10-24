from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from models.database import Database


class StockError(ValueError):
    pass


MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807


class StockService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_medicine(
        self,
        name: str,
        *,
        generic_name: str = "",
        category: str = "other",
        manufacturer: str = "",
        unit_pack_size: str = "",
        barcode: str | None = None,
        mrp_paisa: int = 0,
        selling_rate_paisa: int = 0,
        reorder_level: int = 0,
        rack_location: str = "",
        prescription_required: bool = False,
    ) -> int:
        if not isinstance(name, str):
            raise StockError("Medicine name is required")
        cleaned_name = name.strip()
        if not cleaned_name:
            raise StockError("Medicine name is required")
        if not isinstance(category, str) or category not in {"tablet", "syrup", "injection", "ointment", "drops", "other"}:
            raise StockError("Choose a valid medicine category")
        if len(cleaned_name) > 255:
            raise StockError("Medicine name must be 255 characters or fewer")
        text_values = {
            "generic_name": generic_name,
            "manufacturer": manufacturer,
            "unit_pack_size": unit_pack_size,
            "rack_location": rack_location,
        }
        for field, value in text_values.items():
            if not isinstance(value, str):
                raise StockError(f"{field.replace('_', ' ').title()} must be text")
            if len(value) > 255:
                raise StockError(f"{field.replace('_', ' ').title()} must be 255 characters or fewer")
        if barcode is not None and not isinstance(barcode, str):
            raise StockError("Barcode must be text")
        if barcode is not None and len(barcode) > 128:
            raise StockError("Barcode must be 128 characters or fewer")
        mrp_paisa = self._integer(mrp_paisa, "MRP")
        selling_rate_paisa = self._integer(selling_rate_paisa, "Selling rate")
        reorder_level = self._integer(reorder_level, "Reorder level")
        if not isinstance(prescription_required, (bool, int)) or prescription_required not in (False, True, 0, 1):
            raise StockError("Prescription-required must be a boolean value")
        with self.database.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO medicines
                   (name, generic_name, category, manufacturer, unit_pack_size, barcode,
                    mrp_paisa, selling_rate_paisa, reorder_level, rack_location, prescription_required)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (cleaned_name, generic_name.strip(), category, manufacturer.strip(), unit_pack_size.strip(),
                 barcode.strip() or None if barcode else None, mrp_paisa, selling_rate_paisa,
                 reorder_level, rack_location.strip(), int(prescription_required)),
            )
            return int(cursor.lastrowid)

    def update_medicine(self, medicine_id: int, **values: Any) -> None:
        allowed = {
            "name", "generic_name", "category", "manufacturer", "unit_pack_size", "barcode",
            "mrp_paisa", "selling_rate_paisa", "reorder_level", "rack_location", "prescription_required",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        medicine_id = self._integer(medicine_id, "Medicine id", minimum=1)
        for key in ("name", "generic_name", "manufacturer", "unit_pack_size", "rack_location"):
            if key in updates:
                if not isinstance(updates[key], str):
                    raise StockError(f"{key.replace('_', ' ').title()} must be text")
                updates[key] = updates[key].strip()
                if len(updates[key]) > 255:
                    raise StockError(f"{key.replace('_', ' ').title()} must be 255 characters or fewer")
        if "name" in updates and not updates["name"]:
            raise StockError("Medicine name is required")
        if "category" in updates and (not isinstance(updates["category"], str) or updates["category"] not in {"tablet", "syrup", "injection", "ointment", "drops", "other"}):
            raise StockError("Choose a valid medicine category")
        for key in ("mrp_paisa", "selling_rate_paisa", "reorder_level"):
            if key in updates:
                updates[key] = self._integer(updates[key], key.replace("_", " "))
        if "prescription_required" in updates:
            value = updates["prescription_required"]
            if not isinstance(value, (bool, int)) or value not in (False, True, 0, 1):
                raise StockError("Prescription-required must be a boolean value")
            updates["prescription_required"] = int(value)
        if "barcode" in updates and not updates["barcode"]:
            updates["barcode"] = None
        elif "barcode" in updates:
            if not isinstance(updates["barcode"], str):
                raise StockError("Barcode must be text")
            updates["barcode"] = updates["barcode"].strip() or None
            if updates["barcode"] and len(updates["barcode"]) > 128:
                raise StockError("Barcode must be 128 characters or fewer")
        fields = ", ".join(f"{key} = ?" for key in updates)
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"UPDATE medicines SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (*updates.values(), medicine_id),
            )
            if cursor.rowcount != 1:
                raise StockError("Medicine was not found")

    def add_batch(
        self,
        medicine_id: int,
        batch_number: str,
        expiry_date: date | str,
        quantity: int,
        purchase_rate_paisa: int,
        selling_rate_paisa: int,
        *,
        manufacturing_date: date | str | None = None,
        dealer_id: int | None = None,
    ) -> int:
        medicine_id = self._integer(medicine_id, "Medicine id", minimum=1)
        if dealer_id is not None:
            dealer_id = self._integer(dealer_id, "Dealer id", minimum=1)
        if not isinstance(batch_number, str) or not batch_number.strip():
            raise StockError("Batch number is required")
        if len(batch_number.strip()) > 100:
            raise StockError("Batch number must be 100 characters or fewer")
        quantity = self._integer(quantity, "Quantity")
        purchase_rate_paisa = self._integer(purchase_rate_paisa, "Purchase rate")
        selling_rate_paisa = self._integer(selling_rate_paisa, "Selling rate")
        if quantity * purchase_rate_paisa > MAX_SQLITE_INTEGER:
            raise StockError("Batch stock value exceeds the supported limit")
        expiry = self._iso_date(expiry_date)
        manufactured = self._iso_date(manufacturing_date) if manufacturing_date else None
        if manufactured and manufactured > expiry:
            raise StockError("Manufacturing date must be before expiry date")
        with self.database.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO batches
                   (medicine_id, dealer_id, batch_number, manufacturing_date, expiry_date,
                    quantity, purchase_rate_paisa, selling_rate_paisa)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (medicine_id, dealer_id, batch_number.strip(), manufactured, expiry,
                 quantity, purchase_rate_paisa, selling_rate_paisa),
            )
            return int(cursor.lastrowid)

    def search_medicines(
        self,
        search: str = "",
        stock_filter: str = "all",
        *,
        today: date | None = None,
        limit: int = 250,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        limit = self._integer(limit, "Page size", minimum=1)
        offset = self._integer(offset, "Page offset")
        if limit > 500:
            raise StockError("Page size cannot exceed 500 rows")
        if not isinstance(search, str):
            raise StockError("Search text must be text")
        today = today or date.today()
        term = f"{search.strip()}%"
        clauses = ["(m.name LIKE ? OR m.generic_name LIKE ? OR m.barcode = ? OR m.barcode LIKE ? OR EXISTS (SELECT 1 FROM batches sb WHERE sb.medicine_id = m.id AND sb.batch_number LIKE ?))"]
        params: list[Any] = [term, term, search.strip(), term, term]
        if stock_filter == "expired":
            clauses.append("EXISTS (SELECT 1 FROM batches eb WHERE eb.medicine_id = m.id AND eb.quantity > 0 AND eb.expiry_date < ?)")
            params.append(today.isoformat())
        elif stock_filter in {"expiring", "expiring_30", "expiring_60", "expiring_90"}:
            days = int(stock_filter.rsplit("_", 1)[1]) if "_" in stock_filter else 30
            clauses.append("EXISTS (SELECT 1 FROM batches eb WHERE eb.medicine_id = m.id AND eb.quantity > 0 AND eb.expiry_date >= ? AND eb.expiry_date <= ?)")
            cutoff = (today + timedelta(days=days)).isoformat()
            params.extend([today.isoformat(), cutoff])
        elif stock_filter == "low":
            clauses.append("COALESCE((SELECT SUM(b.quantity) FROM batches b WHERE b.medicine_id = m.id AND b.expiry_date >= ?), 0) <= m.reorder_level AND m.reorder_level > 0")
            params.append(today.isoformat())
        elif stock_filter == "out":
            clauses.append("COALESCE((SELECT SUM(b.quantity) FROM batches b WHERE b.medicine_id = m.id AND b.expiry_date >= ?), 0) = 0")
            params.append(today.isoformat())
        elif stock_filter != "all":
            raise StockError("Unknown stock filter")
        query = f"""SELECT m.*,
            COALESCE(SUM(CASE WHEN b.expiry_date >= ? THEN b.quantity ELSE 0 END), 0) AS usable_quantity,
            COALESCE(SUM(b.quantity * b.purchase_rate_paisa), 0) AS stock_value_paisa,
            MIN(CASE WHEN b.quantity > 0 THEN b.expiry_date END) AS nearest_expiry,
            COUNT(*) OVER() AS total_count
            FROM medicines m LEFT JOIN batches b ON b.medicine_id = m.id
            WHERE {' AND '.join(clauses)} GROUP BY m.id ORDER BY m.name COLLATE NOCASE
            LIMIT ? OFFSET ?"""
        with self.database.connect() as connection:
            rows = connection.execute(query, [today.isoformat(), *params, limit, offset]).fetchall()
            return [dict(row) for row in rows]

    def batches_for_medicine(self, medicine_id: int) -> list[dict[str, Any]]:
        medicine_id = self._integer(medicine_id, "Medicine id", minimum=1)
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT b.*, d.name AS dealer_name FROM batches b
                   LEFT JOIN dealers d ON d.id = b.dealer_id
                   WHERE b.medicine_id = ? ORDER BY b.expiry_date, b.id""",
                (medicine_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_batch(self, batch_id: int, **values: Any) -> None:
        allowed = {"batch_number", "manufacturing_date", "expiry_date", "purchase_rate_paisa", "selling_rate_paisa"}
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        batch_id = self._integer(batch_id, "Batch id", minimum=1)
        if "batch_number" in updates:
            if not isinstance(updates["batch_number"], str) or not updates["batch_number"].strip():
                raise StockError("Batch number is required")
            updates["batch_number"] = updates["batch_number"].strip()
            if len(updates["batch_number"]) > 100:
                raise StockError("Batch number must be 100 characters or fewer")
        for key in ("manufacturing_date", "expiry_date"):
            if key in updates and updates[key] is not None:
                updates[key] = self._iso_date(updates[key])
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT batch_number, manufacturing_date, expiry_date, purchase_rate_paisa, quantity FROM batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
            if current is None:
                raise StockError("Batch was not found")
            manufacturing_date = updates.get("manufacturing_date", current["manufacturing_date"])
            expiry_date = updates.get("expiry_date", current["expiry_date"])
            if manufacturing_date and manufacturing_date > expiry_date:
                raise StockError("Manufacturing date must be before expiry date")
            for key in ("purchase_rate_paisa", "selling_rate_paisa"):
                if key in updates:
                    updates[key] = self._integer(updates[key], key.replace("_", " "))
            has_purchase_history = connection.execute(
                "SELECT 1 FROM purchase_items WHERE batch_id = ? LIMIT 1", (batch_id,)
            ).fetchone()
            historical_values = {
                "batch_number": current["batch_number"],
                "manufacturing_date": current["manufacturing_date"],
                "expiry_date": current["expiry_date"],
                "purchase_rate_paisa": current["purchase_rate_paisa"],
            }
            changes_history = any(
                key in updates and updates[key] != historical_values[key]
                for key in historical_values
            )
            if has_purchase_history and changes_history:
                raise StockError("Batch has purchase history; historical batch details cannot be changed")
            resulting_purchase_rate = updates.get("purchase_rate_paisa", current["purchase_rate_paisa"])
            if current["quantity"] * resulting_purchase_rate > MAX_SQLITE_INTEGER:
                raise StockError("Batch stock value exceeds the supported limit")
            cursor = connection.execute(
                f"UPDATE batches SET {', '.join(f'{key} = ?' for key in updates)} WHERE id = ?",
                (*updates.values(), batch_id),
            )
            if cursor.rowcount != 1:
                raise StockError("Batch was not found")

    def delete_empty_batch(self, batch_id: int) -> None:
        batch_id = self._integer(batch_id, "Batch id", minimum=1)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            batch = connection.execute("SELECT quantity FROM batches WHERE id = ?", (batch_id,)).fetchone()
            if batch is None:
                raise StockError("Batch was not found")
            if batch["quantity"] != 0:
                raise StockError("Only an empty batch can be deleted")
            if connection.execute("SELECT 1 FROM stock_adjustments WHERE batch_id = ?", (batch_id,)).fetchone():
                raise StockError("Batch has stock adjustment history and cannot be deleted")
            if connection.execute("SELECT 1 FROM purchase_items WHERE batch_id = ?", (batch_id,)).fetchone():
                raise StockError("Batch is referenced by a purchase record and cannot be deleted")
            connection.execute("DELETE FROM batches WHERE id = ?", (batch_id,))

    def adjust_stock(self, batch_id: int, quantity_delta: int, reason: str, remark: str = "") -> None:
        batch_id = self._integer(batch_id, "Batch id", minimum=1)
        quantity_delta = self._integer(quantity_delta, "Adjustment quantity", allow_negative=True)
        if quantity_delta == 0:
            raise StockError("Adjustment quantity cannot be zero")
        if not isinstance(reason, str) or not reason.strip():
            raise StockError("A reason is required for stock adjustments")
        if not isinstance(remark, str):
            raise StockError("Adjustment remark must be text")
        if len(reason.strip()) > 255 or len(remark) > 1000:
            raise StockError("Adjustment reason or remark is too long")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT quantity FROM batches WHERE id = ?", (batch_id,)).fetchone()
            if row is None:
                raise StockError("Batch was not found")
            resulting_quantity = row["quantity"] + quantity_delta
            if resulting_quantity < 0:
                raise StockError("Adjustment would make stock negative")
            connection.execute("UPDATE batches SET quantity = ? WHERE id = ?", (resulting_quantity, batch_id))
            connection.execute(
                "INSERT INTO stock_adjustments (batch_id, adjustment_date, quantity_delta, reason, remark) VALUES (?, ?, ?, ?, ?)",
                (batch_id, date.today().isoformat(), quantity_delta, reason.strip(), remark.strip()),
            )

    def write_off_expired(self, *, today: date | None = None) -> int:
        today = today or date.today()
        total_written_off = 0
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            batches = connection.execute(
                "SELECT id, quantity FROM batches WHERE quantity > 0 AND expiry_date < ?",
                (today.isoformat(),),
            ).fetchall()
            for batch in batches:
                quantity = int(batch["quantity"])
                connection.execute("UPDATE batches SET quantity = 0 WHERE id = ?", (batch["id"],))
                connection.execute(
                    "INSERT INTO stock_adjustments (batch_id, adjustment_date, quantity_delta, reason) VALUES (?, ?, ?, ?)",
                    (batch["id"], today.isoformat(), -quantity, "Expired stock write-off"),
                )
                total_written_off += quantity
        return total_written_off

    def deduct_fefo(self, medicine_id: int, quantity: int, *, today: date | None = None) -> list[dict[str, int]]:
        medicine_id = self._integer(medicine_id, "Medicine id", minimum=1)
        quantity = self._integer(quantity, "Quantity", minimum=1)
        if quantity <= 0:
            raise StockError("Quantity must be greater than zero")
        today = today or date.today()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            batches = connection.execute(
                """SELECT id, quantity FROM batches
                   WHERE medicine_id = ? AND quantity > 0 AND expiry_date >= ?
                   ORDER BY expiry_date, id""",
                (medicine_id, today.isoformat()),
            ).fetchall()
            available = sum(int(batch["quantity"]) for batch in batches)
            if available < quantity:
                raise StockError(f"Insufficient unexpired stock: {available} available")
            remaining = quantity
            allocations: list[dict[str, int]] = []
            for batch in batches:
                taken = min(remaining, int(batch["quantity"]))
                if taken:
                    connection.execute("UPDATE batches SET quantity = quantity - ? WHERE id = ?", (taken, batch["id"]))
                    allocations.append({"batch_id": int(batch["id"]), "quantity": taken})
                    remaining -= taken
                if remaining == 0:
                    break
            return allocations

    def delete_medicine(self, medicine_id: int) -> None:
        medicine_id = self._integer(medicine_id, "Medicine id", minimum=1)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM medicines WHERE id = ?", (medicine_id,)).fetchone() is None:
                raise StockError("Medicine was not found")
            if connection.execute("SELECT 1 FROM batches WHERE medicine_id = ? LIMIT 1", (medicine_id,)).fetchone():
                raise StockError("Medicine has batch history and cannot be deleted")
            connection.execute("DELETE FROM medicines WHERE id = ?", (medicine_id,))

    @staticmethod
    def _integer(value: Any, label: str, *, minimum: int = 0, allow_negative: bool = False) -> int:
        if type(value) is not int:
            raise StockError(f"{label} must be a whole number")
        lower_bound = -MAX_SQLITE_INTEGER if allow_negative else minimum
        if value < lower_bound or value > MAX_SQLITE_INTEGER:
            qualifier = "within the supported range" if allow_negative else "non-negative and within the supported range"
            raise StockError(f"{label} must be {qualifier}")
        return value

    @staticmethod
    def _iso_date(value: date | str) -> str:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        try:
            return date.fromisoformat(value).isoformat()
        except (TypeError, ValueError) as error:
            raise StockError("Enter a valid date in YYYY-MM-DD format") from error
