from datetime import date, timedelta

import pytest

from models.database import Database
from services.customer_credit_service import CustomerCreditService
from services.sales_service import SalesError, SalesService


@pytest.fixture
def sales(tmp_path):
    database = Database(tmp_path / "sales.sqlite3")
    database.initialize()
    service = SalesService(database)
    customer_id = service.create_customer("Ram Bahadur", phone="9800000000", credit_limit_paisa=50000)
    with database.connect() as connection:
        medicine_id = connection.execute(
            "INSERT INTO medicines (name, generic_name, selling_rate_paisa) VALUES ('Paracetamol', 'Paracetamol', 2000)"
        ).lastrowid
    today = date(2026, 10, 23)
    first_batch = service.database.connect()
    first_batch.execute(
        "INSERT INTO batches (medicine_id, batch_number, expiry_date, quantity, purchase_rate_paisa, selling_rate_paisa) VALUES (?, 'SOON', ?, 3, 800, 2000)",
        (medicine_id, (today + timedelta(days=10)).isoformat()),
    )
    first_batch.execute(
        "INSERT INTO batches (medicine_id, batch_number, expiry_date, quantity, purchase_rate_paisa, selling_rate_paisa) VALUES (?, 'LATER', ?, 8, 900, 2000)",
        (medicine_id, (today + timedelta(days=60)).isoformat()),
    )
    first_batch.commit()
    first_batch.close()
    return database, service, CustomerCreditService(database), customer_id, medicine_id, today


def test_credit_sale_uses_fefo_and_updates_customer_ledger(sales):
    database, service, credit, customer_id, medicine_id, today = sales
    sale_id = service.create_sale(
        "DMH-001", today, "credit",
        [{"medicine_id": medicine_id, "quantity": 5, "selling_rate_paisa": 2000, "discount_paisa": 500}],
        customer_id=customer_id, bill_discount_paisa=500,
    )

    with database.connect() as connection:
        batches = {row["batch_number"]: row["quantity"] for row in connection.execute("SELECT batch_number, quantity FROM batches")}
        sale = connection.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
        sale_items = connection.execute("SELECT * FROM sale_items WHERE sale_id = ? ORDER BY id", (sale_id,)).fetchall()
    assert batches == {"SOON": 0, "LATER": 6}
    assert sale["total_paisa"] == 9000
    assert [row["quantity"] for row in sale_items] == [3, 2]
    report = credit.customer_ledger(customer_id)
    assert report["closing_balance_paisa"] == 9000


def test_cash_sale_requires_available_unexpired_stock_and_rolls_back(sales):
    database, service, _credit, _customer_id, medicine_id, today = sales
    with pytest.raises(SalesError, match="Insufficient unexpired stock"):
        service.create_sale("DMH-002", today, "cash", [{
            "medicine_id": medicine_id, "quantity": 20, "selling_rate_paisa": 2000,
        }])
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
        assert connection.execute("SELECT SUM(quantity) FROM batches").fetchone()[0] == 11


def test_return_restores_exact_batches_and_reduces_credit(sales):
    database, service, credit, customer_id, medicine_id, today = sales
    sale_id = service.create_sale(
        "DMH-003", today, "credit",
        [{"medicine_id": medicine_id, "quantity": 5, "selling_rate_paisa": 2000}],
        customer_id=customer_id,
    )
    sale_items = service.sale_items(sale_id)

    service.return_items(sale_id, [{"sale_item_id": sale_items[0]["id"], "quantity": 2}], return_date=today)

    report = credit.customer_ledger(customer_id)
    assert report["closing_balance_paisa"] == 6000
    with database.connect() as connection:
        batch_quantity = connection.execute("SELECT quantity FROM batches WHERE id = ?", (sale_items[0]["batch_id"],)).fetchone()[0]
        returned = connection.execute("SELECT returned_quantity FROM sale_items WHERE id = ?", (sale_items[0]["id"],)).fetchone()[0]
        status = connection.execute("SELECT status FROM sales WHERE id = ?", (sale_id,)).fetchone()[0]
    assert batch_quantity == 2
    assert returned == 2
    assert status == "partial_return"


def test_held_bill_round_trip_and_duplicate_bill_rejection(sales):
    _database, service, _credit, customer_id, _medicine_id, _today = sales
    held_id = service.hold_bill("DMH-HOLD-1", {"customer_id": customer_id, "lines": [{"qty": 2}]})

    resumed = service.resume_bill(held_id)
    assert resumed["payload"]["customer_id"] == customer_id
    assert resumed["payload"]["lines"] == [{"qty": 2}]
    service.delete_held_bill(held_id)
    assert service.held_bills() == []
    line = {"medicine_id": _medicine_id, "quantity": 1, "selling_rate_paisa": 2000}
    service.create_sale("DMH-004", "2026-10-23", "cash", [line])
    with pytest.raises(SalesError, match="already exists"):
        service.create_sale("DMH-004", "2026-10-23", "cash", [line])


def test_customer_payment_link_and_ageing(sales):
    database, service, credit, customer_id, medicine_id, today = sales
    service.create_sale(
        "DMH-AGE", today - timedelta(days=45), "credit",
        [{"medicine_id": medicine_id, "quantity": 1, "selling_rate_paisa": 2000}],
        customer_id=customer_id,
    )
    credit.receive_payment(customer_id, today, 500, linked_bill_no="DMH-AGE", payment_method="QR")
    with pytest.raises(SalesError, match="exceeds"):
        credit.receive_payment(customer_id, today, 1600, linked_bill_no="DMH-AGE")

    ageing = credit.ageing(today=today)
    assert ageing["31-60"][0]["balance_paisa"] == 1500
    assert credit.reminder_url(customer_id).startswith("sms:9800000000?body=")
