from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 7


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()

SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    shop_name TEXT NOT NULL DEFAULT 'Dipesh Medical Hall',
    address TEXT NOT NULL DEFAULT 'Biratnagar-11, Morang, Nepal',
    phone TEXT NOT NULL DEFAULT '',
    pan_vat TEXT NOT NULL DEFAULT '',
    currency_symbol TEXT NOT NULL DEFAULT 'Rs.',
    bill_prefix TEXT NOT NULL DEFAULT 'DMH-'
);
CREATE TABLE IF NOT EXISTS medicines (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    generic_name TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'other' CHECK (category IN ('tablet','syrup','injection','ointment','drops','other')),
    manufacturer TEXT NOT NULL DEFAULT '',
    unit_pack_size TEXT NOT NULL DEFAULT '',
    barcode TEXT UNIQUE,
    mrp_paisa INTEGER NOT NULL DEFAULT 0 CHECK (mrp_paisa >= 0),
    selling_rate_paisa INTEGER NOT NULL DEFAULT 0 CHECK (selling_rate_paisa >= 0),
    reorder_level INTEGER NOT NULL DEFAULT 0 CHECK (reorder_level >= 0),
    rack_location TEXT NOT NULL DEFAULT '',
    prescription_required INTEGER NOT NULL DEFAULT 0 CHECK (prescription_required IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS dealers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id) ON DELETE RESTRICT,
    dealer_id INTEGER REFERENCES dealers(id) ON DELETE RESTRICT,
    batch_number TEXT NOT NULL,
    manufacturing_date TEXT,
    expiry_date TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    purchase_rate_paisa INTEGER NOT NULL DEFAULT 0 CHECK (purchase_rate_paisa >= 0),
    selling_rate_paisa INTEGER NOT NULL DEFAULT 0 CHECK (selling_rate_paisa >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(medicine_id, batch_number)
);
CREATE TABLE IF NOT EXISTS stock_adjustments (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE RESTRICT,
    adjustment_date TEXT NOT NULL,
    quantity_delta INTEGER NOT NULL,
    reason TEXT NOT NULL,
    remark TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY,
    owner_type TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    original_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_medicines_name ON medicines(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_medicines_generic ON medicines(generic_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_medicines_barcode ON medicines(barcode);
CREATE INDEX IF NOT EXISTS idx_batches_expiry ON batches(expiry_date);
CREATE INDEX IF NOT EXISTS idx_batches_medicine_expiry ON batches(medicine_id, expiry_date, id);
CREATE INDEX IF NOT EXISTS idx_batches_batch_number ON batches(batch_number COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_stock_adjustments_date ON stock_adjustments(adjustment_date);
"""


def default_database_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Dipesh Medical Hall"
    base.mkdir(parents=True, exist_ok=True)
    return base / "pharmacy.sqlite3"


class Database:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, factory=_ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"Database version {version} is newer than this application supports")
            connection.executescript(SCHEMA)
            connection.execute("INSERT OR IGNORE INTO shop_settings (id) VALUES (1)")
            if version < 2:
                self._migrate_to_v2(connection)
            if version < 3:
                self._migrate_to_v3(connection)
            if version < 4:
                self._migrate_to_v4(connection)
            if version < 5:
                self._migrate_to_v5(connection)
            if version < 6:
                self._migrate_to_v6(connection)
            if version < 7:
                self._migrate_to_v7(connection)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @staticmethod
    def _migrate_to_v2(connection: sqlite3.Connection) -> None:
        dealer_columns = {row["name"] for row in connection.execute("PRAGMA table_info(dealers)")}
        for name, definition in (
            ("contact_person", "TEXT NOT NULL DEFAULT ''"),
            ("address", "TEXT NOT NULL DEFAULT ''"),
            ("pan_vat", "TEXT NOT NULL DEFAULT ''"),
            ("credit_terms_days", "INTEGER NOT NULL DEFAULT 0 CHECK (credit_terms_days >= 0)"),
        ):
            if name not in dealer_columns:
                connection.execute(f"ALTER TABLE dealers ADD COLUMN {name} {definition}")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ledger_entries (
                id INTEGER PRIMARY KEY,
                party_type TEXT NOT NULL DEFAULT 'dealer' CHECK (party_type = 'dealer'),
                party_id INTEGER NOT NULL REFERENCES dealers(id) ON DELETE RESTRICT,
                entry_date TEXT NOT NULL,
                invoice_no TEXT,
                debit_paisa INTEGER NOT NULL DEFAULT 0 CHECK (debit_paisa >= 0),
                payment_date TEXT,
                credit_paisa INTEGER NOT NULL DEFAULT 0 CHECK (credit_paisa >= 0),
                linked_invoice_no TEXT,
                due_date TEXT,
                payment_method TEXT,
                remark TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK ((debit_paisa > 0 AND credit_paisa = 0 AND invoice_no IS NOT NULL AND payment_date IS NULL)
                    OR (credit_paisa > 0 AND debit_paisa = 0 AND payment_date IS NOT NULL))
            );
            CREATE INDEX IF NOT EXISTS idx_ledger_party_date ON ledger_entries(party_type, party_id, entry_date, payment_date);
            CREATE INDEX IF NOT EXISTS idx_ledger_due_date ON ledger_entries(due_date);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_dealer_invoice ON ledger_entries(party_id, invoice_no)
                WHERE party_type = 'dealer' AND debit_paisa > 0;
            """
        )

    @staticmethod
    def _migrate_to_v3(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY,
                dealer_id INTEGER NOT NULL REFERENCES dealers(id) ON DELETE RESTRICT,
                invoice_number TEXT NOT NULL,
                invoice_date TEXT NOT NULL,
                due_date TEXT,
                total_paisa INTEGER NOT NULL CHECK (total_paisa >= 0),
                payment_type TEXT NOT NULL CHECK (payment_type IN ('cash', 'credit')),
                remark TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(dealer_id, invoice_number)
            );
            CREATE TABLE IF NOT EXISTS purchase_items (
                id INTEGER PRIMARY KEY,
                purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE RESTRICT,
                medicine_id INTEGER NOT NULL REFERENCES medicines(id) ON DELETE RESTRICT,
                batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE RESTRICT,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                free_quantity INTEGER NOT NULL DEFAULT 0 CHECK (free_quantity >= 0),
                purchase_rate_paisa INTEGER NOT NULL CHECK (purchase_rate_paisa >= 0),
                discount_paisa INTEGER NOT NULL DEFAULT 0 CHECK (discount_paisa >= 0),
                tax_paisa INTEGER NOT NULL DEFAULT 0 CHECK (tax_paisa >= 0),
                subtotal_paisa INTEGER NOT NULL CHECK (subtotal_paisa >= 0)
            );
            CREATE INDEX IF NOT EXISTS idx_purchases_date ON purchases(invoice_date);
            CREATE INDEX IF NOT EXISTS idx_purchases_dealer_date ON purchases(dealer_id, invoice_date);
            CREATE INDEX IF NOT EXISTS idx_purchase_items_medicine ON purchase_items(medicine_id);
            """
        )

    @staticmethod
    def _migrate_to_v4(connection: sqlite3.Connection) -> None:
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_ledger_effective_date
               ON ledger_entries(party_type, party_id, COALESCE(payment_date, entry_date), id)"""
        )

    @staticmethod
    def _migrate_to_v5(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE INDEX IF NOT EXISTS idx_purchases_invoice_number ON purchases(invoice_number COLLATE NOCASE)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_dealers_name ON dealers(name COLLATE NOCASE)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_dealers_company ON dealers(company COLLATE NOCASE)")

    @staticmethod
    def _migrate_to_v6(connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(shop_settings)")}
        if "language" not in columns:
            connection.execute("ALTER TABLE shop_settings ADD COLUMN language TEXT NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'ne'))")

    @staticmethod
    def _migrate_to_v7(connection: sqlite3.Connection) -> None:
        connection.execute(
            """CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                credit_limit_paisa INTEGER NOT NULL DEFAULT 0 CHECK (credit_limit_paisa >= 0),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        connection.execute(
            """CREATE TABLE ledger_entries_v7 (
                id INTEGER PRIMARY KEY,
                party_type TEXT NOT NULL CHECK (party_type IN ('dealer', 'customer')),
                party_id INTEGER NOT NULL,
                dealer_id INTEGER REFERENCES dealers(id) ON DELETE RESTRICT,
                customer_id INTEGER REFERENCES customers(id) ON DELETE RESTRICT,
                entry_date TEXT NOT NULL,
                invoice_no TEXT,
                debit_paisa INTEGER NOT NULL DEFAULT 0 CHECK (debit_paisa >= 0),
                payment_date TEXT,
                credit_paisa INTEGER NOT NULL DEFAULT 0 CHECK (credit_paisa >= 0),
                linked_invoice_no TEXT,
                due_date TEXT,
                payment_method TEXT,
                remark TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK ((party_type = 'dealer' AND dealer_id = party_id AND customer_id IS NULL)
                    OR (party_type = 'customer' AND customer_id = party_id AND dealer_id IS NULL)),
                CHECK ((debit_paisa > 0 AND credit_paisa = 0 AND invoice_no IS NOT NULL AND payment_date IS NULL)
                    OR (credit_paisa > 0 AND debit_paisa = 0 AND payment_date IS NOT NULL))
            )"""
        )
        connection.execute(
            """INSERT INTO ledger_entries_v7
               (id, party_type, party_id, dealer_id, entry_date, invoice_no, debit_paisa,
                payment_date, credit_paisa, linked_invoice_no, due_date, payment_method, remark, created_at)
               SELECT id, 'dealer', party_id, party_id, entry_date, invoice_no, debit_paisa,
                      payment_date, credit_paisa, linked_invoice_no, due_date, payment_method, remark, created_at
               FROM ledger_entries"""
        )
        for index_name in (
            "idx_ledger_party_date", "idx_ledger_due_date", "idx_ledger_dealer_invoice", "idx_ledger_effective_date"
        ):
            connection.execute(f"DROP INDEX IF EXISTS {index_name}")
        connection.execute("DROP TABLE ledger_entries")
        connection.execute("ALTER TABLE ledger_entries_v7 RENAME TO ledger_entries")
        connection.execute(
            """CREATE TABLE sales (
                id INTEGER PRIMARY KEY,
                bill_no TEXT NOT NULL UNIQUE,
                sale_date TEXT NOT NULL,
                customer_id INTEGER REFERENCES customers(id) ON DELETE RESTRICT,
                payment_type TEXT NOT NULL CHECK (payment_type IN ('cash', 'online', 'credit')),
                subtotal_paisa INTEGER NOT NULL CHECK (subtotal_paisa >= 0),
                discount_paisa INTEGER NOT NULL DEFAULT 0 CHECK (discount_paisa >= 0),
                total_paisa INTEGER NOT NULL CHECK (total_paisa >= 0),
                status TEXT NOT NULL DEFAULT 'complete' CHECK (status IN ('complete', 'partial_return', 'returned')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        connection.execute(
            """CREATE TABLE sale_items (
                id INTEGER PRIMARY KEY,
                sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE RESTRICT,
                medicine_id INTEGER NOT NULL REFERENCES medicines(id) ON DELETE RESTRICT,
                batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE RESTRICT,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                returned_quantity INTEGER NOT NULL DEFAULT 0 CHECK (returned_quantity >= 0),
                selling_rate_paisa INTEGER NOT NULL CHECK (selling_rate_paisa >= 0),
                cost_rate_paisa INTEGER NOT NULL CHECK (cost_rate_paisa >= 0),
                discount_paisa INTEGER NOT NULL DEFAULT 0 CHECK (discount_paisa >= 0),
                line_total_paisa INTEGER NOT NULL CHECK (line_total_paisa >= 0)
            )"""
        )
        connection.execute(
            """CREATE TABLE sale_returns (
                id INTEGER PRIMARY KEY,
                sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE RESTRICT,
                return_date TEXT NOT NULL,
                total_paisa INTEGER NOT NULL CHECK (total_paisa > 0),
                remark TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        connection.execute(
            """CREATE TABLE sale_return_items (
                id INTEGER PRIMARY KEY,
                return_id INTEGER NOT NULL REFERENCES sale_returns(id) ON DELETE RESTRICT,
                sale_item_id INTEGER NOT NULL REFERENCES sale_items(id) ON DELETE RESTRICT,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                amount_paisa INTEGER NOT NULL CHECK (amount_paisa > 0)
            )"""
        )
        connection.execute(
            """CREATE TABLE held_bills (
                id INTEGER PRIMARY KEY,
                bill_no TEXT NOT NULL UNIQUE,
                saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                payload_json TEXT NOT NULL
            )"""
        )
        for statement in (
            "CREATE INDEX idx_customers_name ON customers(name COLLATE NOCASE)",
            "CREATE INDEX idx_customers_phone ON customers(phone)",
            "CREATE INDEX idx_sales_date ON sales(sale_date)",
            "CREATE INDEX idx_sales_customer_date ON sales(customer_id, sale_date)",
            "CREATE INDEX idx_sale_items_medicine ON sale_items(medicine_id)",
            "CREATE INDEX idx_sale_items_batch ON sale_items(batch_id)",
            "CREATE INDEX idx_ledger_party_date ON ledger_entries(party_type, party_id, entry_date, payment_date)",
            "CREATE INDEX idx_ledger_due_date ON ledger_entries(due_date)",
            "CREATE INDEX idx_ledger_effective_date ON ledger_entries(party_type, party_id, COALESCE(payment_date, entry_date), id)",
            "CREATE UNIQUE INDEX idx_ledger_dealer_invoice ON ledger_entries(party_id, invoice_no COLLATE NOCASE) WHERE party_type = 'dealer' AND debit_paisa > 0",
            "CREATE UNIQUE INDEX idx_ledger_customer_invoice ON ledger_entries(party_id, invoice_no COLLATE NOCASE) WHERE party_type = 'customer' AND debit_paisa > 0",
        ):
            connection.execute(statement)
