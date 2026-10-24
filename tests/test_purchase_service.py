import sqlite3
from datetime import date

import pytest

from models.database import Database
from services.dealer_ledger_service import DealerLedgerService
from services.purchase_service import PurchaseError, PurchaseService
from services.stock_service import StockError, StockService


@pytest.fixture
def purchase(tmp_path):
    database = Database(tmp_path / "purchase.sqlite3")
    database.initialize()
    dealer_id = DealerLedgerService(database).create_dealer("Local Wholesaler")
    with database.connect() as connection:
        medicine_id = connection.execute("INSERT INTO medicines (name) VALUES ('Paracetamol')").lastrowid
    return database, PurchaseService(database), dealer_id, medicine_id


def _item(medicine_id, **overrides):
    item = {
        "medicine_id": medicine_id,
        "batch_number": "B-100",
        "manufacturing_date": date(2026, 1, 1),
        "expiry_date": date(2027, 1, 1),
        "quantity": 10,
        "free_quantity": 2,
        "purchase_rate_paisa": 1000,
        "selling_rate_paisa": 1500,
        "discount_paisa": 500,
        "tax_paisa": 250,
    }
    item.update(overrides)
    return item


def test_credit_purchase_receives_stock_and_posts_dealer_debit(purchase):
    database, service, dealer_id, medicine_id = purchase

    purchase_id = service.create_purchase(
        dealer_id, "PUR-001", "2026-10-23", "credit", [_item(medicine_id)], due_date="2026-11-22"
    )

    with database.connect() as connection:
        batch = connection.execute("SELECT * FROM batches WHERE medicine_id = ?", (medicine_id,)).fetchone()
        item = connection.execute("SELECT * FROM purchase_items WHERE purchase_id = ?", (purchase_id,)).fetchone()
    assert batch["quantity"] == 12
    assert item["subtotal_paisa"] == 9750
    assert DealerLedgerService(database).ledger(dealer_id)["closing_balance_paisa"] == 9750


def test_cash_purchase_posts_matching_debit_and_credit(purchase):
    database, service, dealer_id, medicine_id = purchase
    service.create_purchase(dealer_id, "PUR-CASH", "2026-10-23", "cash", [_item(medicine_id)])

    report = DealerLedgerService(database).ledger(dealer_id)
    assert report["total_debit_paisa"] == 9750
    assert report["total_credit_paisa"] == 9750
    assert report["closing_balance_paisa"] == 0


def test_duplicate_purchase_invoice_rolls_back_without_extra_stock(purchase):
    database, service, dealer_id, medicine_id = purchase
    service.create_purchase(dealer_id, "DUP-1", "2026-10-20", "credit", [_item(medicine_id)])
    with pytest.raises(PurchaseError, match="already exists"):
        service.create_purchase(dealer_id, "dup-1", "2026-10-21", "credit", [_item(medicine_id)])

    with database.connect() as connection:
        quantity = connection.execute("SELECT quantity FROM batches WHERE medicine_id = ?", (medicine_id,)).fetchone()[0]
        purchases = connection.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]
    assert quantity == 12
    assert purchases == 1


def test_existing_batch_expiry_mismatch_rolls_back_purchase(purchase):
    database, service, dealer_id, medicine_id = purchase
    service.create_purchase(dealer_id, "EXP-1", "2026-10-20", "credit", [_item(medicine_id)])
    with pytest.raises(PurchaseError, match="different expiry"):
        service.create_purchase(
            dealer_id, "EXP-2", "2026-10-21", "credit",
            [_item(medicine_id, expiry_date=date(2027, 2, 1))],
        )
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] == 1


def test_purchase_linked_batch_cannot_be_deleted(purchase):
    database, service, dealer_id, medicine_id = purchase
    service.create_purchase(dealer_id, "KEEP-BATCH", "2026-10-20", "credit", [_item(medicine_id)])
    with database.connect() as connection:
        batch_id = connection.execute("SELECT id FROM batches WHERE medicine_id = ?", (medicine_id,)).fetchone()[0]
        connection.execute("UPDATE batches SET quantity = 0 WHERE id = ?", (batch_id,))

    with pytest.raises(StockError, match="purchase record"):
        StockService(database).delete_empty_batch(batch_id)


def test_purchase_history_is_paginated(purchase):
    database, service, dealer_id, _medicine_id = purchase
    with database.connect() as connection:
        connection.executemany(
            """INSERT INTO purchases (dealer_id, invoice_number, invoice_date, total_paisa, payment_type)
               VALUES (?, ?, '2026-10-01', 100, 'credit')""",
            [(dealer_id, f"HIST-{number:03d}") for number in range(300)],
        )

    first_page = service.purchases("HIST", limit=250, offset=0)
    second_page = service.purchases("HIST", limit=250, offset=250)

    assert len(first_page) == 250
    assert len(second_page) == 50
    assert first_page[0]["total_count"] == 300
    assert second_page[0]["total_count"] == 300