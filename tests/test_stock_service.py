from datetime import date, timedelta

import pytest

from models.database import Database
from services.stock_service import StockError, StockService


@pytest.fixture
def stock(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    service = StockService(database)
    medicine_id = service.create_medicine("Paracetamol", generic_name="acetaminophen", reorder_level=5)
    return database, service, medicine_id


def test_fefo_uses_nearest_unexpired_batch_and_ignores_expired(stock):
    _database, service, medicine_id = stock
    today = date(2026, 10, 23)
    expired_id = service.add_batch(medicine_id, "OLD", today - timedelta(days=1), 8, 100, 200)
    first_id = service.add_batch(medicine_id, "SOON", today + timedelta(days=10), 3, 100, 200)
    second_id = service.add_batch(medicine_id, "LATER", today + timedelta(days=60), 6, 100, 200)

    allocations = service.deduct_fefo(medicine_id, 5, today=today)

    assert allocations == [{"batch_id": first_id, "quantity": 3}, {"batch_id": second_id, "quantity": 2}]
    batches = {batch["id"]: batch["quantity"] for batch in service.batches_for_medicine(medicine_id)}
    assert batches == {expired_id: 8, first_id: 0, second_id: 4}


def test_fefo_rejects_insufficient_unexpired_stock_without_partial_mutation(stock):
    _database, service, medicine_id = stock
    batch_id = service.add_batch(medicine_id, "A", date(2026, 11, 1), 2, 100, 200)

    with pytest.raises(StockError, match="Insufficient"):
        service.deduct_fefo(medicine_id, 3, today=date(2026, 10, 23))

    assert service.batches_for_medicine(medicine_id)[0]["quantity"] == 2
    assert batch_id > 0


def test_expiry_filter_and_write_off_are_auditable(stock):
    database, service, medicine_id = stock
    today = date(2026, 10, 23)
    expired_id = service.add_batch(medicine_id, "EXPIRED", today - timedelta(days=1), 4, 125, 200)
    current_id = service.add_batch(medicine_id, "CURRENT", today + timedelta(days=100), 9, 125, 200)

    assert [row["name"] for row in service.search_medicines(stock_filter="expired", today=today)] == ["Paracetamol"]
    assert service.write_off_expired(today=today) == 4
    quantities = {batch["id"]: batch["quantity"] for batch in service.batches_for_medicine(medicine_id)}
    assert quantities == {expired_id: 0, current_id: 9}
    with database.connect() as connection:
        adjustment = connection.execute("SELECT quantity_delta, reason FROM stock_adjustments").fetchone()
    assert tuple(adjustment) == (-4, "Expired stock write-off")


def test_expiry_filters_use_selected_horizon(stock):
    _database, service, medicine_id = stock
    today = date(2026, 10, 23)
    service.add_batch(medicine_id, "MIDTERM", today + timedelta(days=45), 2, 100, 200)

    assert service.search_medicines(stock_filter="expiring_30", today=today) == []
    assert len(service.search_medicines(stock_filter="expiring_60", today=today)) == 1
    assert len(service.search_medicines(stock_filter="expiring_90", today=today)) == 1


def test_negative_adjustment_cannot_make_stock_negative(stock):
    _database, service, medicine_id = stock
    batch_id = service.add_batch(medicine_id, "A", date(2027, 1, 1), 2, 100, 200)
    with pytest.raises(StockError, match="negative"):
        service.adjust_stock(batch_id, -3, "damage")


def test_medicine_search_is_paginated_and_reports_total(stock):
    database, service, _medicine_id = stock
    with database.connect() as connection:
        connection.executemany(
            "INSERT INTO medicines (name) VALUES (?)",
            [(f"Medicine {number:03d}",) for number in range(300)],
        )

    first_page = service.search_medicines("Medicine", limit=250, offset=0)
    second_page = service.search_medicines("Medicine", limit=250, offset=250)

    assert len(first_page) == 250
    assert len(second_page) == 50
    assert first_page[0]["total_count"] == 300
    assert second_page[0]["total_count"] == 300
    assert service.search_medicines("Medicine 29", limit=250)[0]["name"].startswith("Medicine 29")
