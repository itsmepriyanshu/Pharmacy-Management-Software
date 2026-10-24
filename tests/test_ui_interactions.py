import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
)

from models.database import Database
from services.sales_service import SalesService
from services.stock_service import StockService
from ui.main_window import (
    BatchDialog,
    CustomerPaymentDialog,
    DealerDialog,
    LedgerEntryDialog,
    MainWindow,
    MedicineDialog,
    PurchaseItemDialog,
)


def test_all_buttons_are_clickable_and_pages_scroll(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "ui.sqlite3")
    database.initialize()
    window = MainWindow(database)
    window.resize(1050, 680)
    window.show()
    app.processEvents()

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: ("", ""))
    monkeypatch.setattr(QDialog, "exec", lambda _self: QDialog.DialogCode.Rejected)

    window._navigate(3)
    app.processEvents()
    page_scrolls = window.findChildren(QScrollArea, "pageScrollArea")
    assert len(page_scrolls) == 6
    assert window.findChild(QScrollArea, "sidebarScrollArea") is not None
    assert page_scrolls[3].verticalScrollBar().maximum() > 0

    buttons = window.findChildren(QPushButton)
    assert buttons
    assert all(button.isEnabled() or button.text() in {"Previous", "Next"} for button in buttons)
    for button in buttons:
        button.click()
        app.processEvents()

    window.close()


def test_purchase_item_inputs_accept_text_dates_and_numbers(tmp_path):
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "input.sqlite3")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO medicines (name) VALUES ('Paracetamol')")

    dialog = PurchaseItemDialog(database)
    dialog.resize(420, 320)
    dialog.show()
    app.processEvents()
    assert dialog.fields_scroll.verticalScrollBar().maximum() > 0
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled()
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel).isEnabled()
    dialog.batch.setText("B-TEST")
    dialog.manufacturing.setDate(QDate(2026, 1, 1))
    dialog.expiry.setDate(QDate(2027, 1, 1))
    dialog.quantity.setValue(12)
    dialog.free_quantity.setValue(2)
    dialog.purchase_rate.setValue(10.25)
    dialog.selling_rate.setValue(15.50)
    dialog.discount.setValue(1.00)
    dialog.tax.setValue(0.75)

    values = dialog.values()
    assert values["batch_number"] == "B-TEST"
    assert values["manufacturing_date"] == date(2026, 1, 1)
    assert values["expiry_date"] == date(2027, 1, 1)
    assert values["quantity"] == 12
    assert values["free_quantity"] == 2
    assert values["purchase_rate_paisa"] == 1025
    assert values["discount_paisa"] == 100
    assert values["tax_paisa"] == 75
    dialog.close()


def test_all_entry_dialog_controls_are_enabled_and_editable():
    app = QApplication.instance() or QApplication([])
    dialogs = [MedicineDialog(), BatchDialog(), DealerDialog(), LedgerEntryDialog("debit"), LedgerEntryDialog("credit")]
    for dialog in dialogs:
        dialog.resize(380, 260)
        dialog.show()
        app.processEvents()
        assert dialog.fields_scroll.isVisible()
        assert dialog.fields_scroll.widget() is not None
        assert all(button.isEnabled() for button in dialog.buttons.buttons())
        for field in dialog.findChildren(QLineEdit):
            assert field.isEnabled()
            field.setText("Test value")
        for field in dialog.findChildren(QComboBox):
            assert field.isEnabled()
            if field.count() > 1:
                field.setCurrentIndex(1)
        for field in dialog.findChildren(QDateEdit):
            assert field.isEnabled()
            field.setDate(QDate(2026, 10, 23))
        for field in dialog.findChildren(QSpinBox):
            assert field.isEnabled()
            field.setValue(2)
        for field in dialog.findChildren(QDoubleSpinBox):
            assert field.isEnabled()
            field.setValue(1.25)
        for field in dialog.findChildren(QCheckBox):
            assert field.isEnabled()
            field.click()
        dialog.close()


def test_language_switch_translates_and_persists(tmp_path):
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "language.sqlite3")
    database.initialize()
    window = MainWindow(database)

    window.language_selector.setCurrentIndex(window.language_selector.findData("ne"))

    assert window.header.text() == "ड्यासबोर्ड"
    assert window.nav_buttons[0].text() == "ड्यासबोर्ड"
    assert window.nav_buttons[3].text() == "खरिद"
    assert window.dashboard_summary.text().startswith("औषधि:")
    with database.connect() as connection:
        assert connection.execute("SELECT language FROM shop_settings WHERE id = 1").fetchone()[0] == "ne"
    window._navigate(3)
    assert window.header.text() == "खरिद"
    window.close()

    reopened = MainWindow(database)
    assert reopened.language == "ne"
    assert reopened.language_selector.currentData() == "ne"
    reopened.language_selector.setCurrentIndex(reopened.language_selector.findData("en"))
    assert reopened.header.text() == "Dashboard"
    reopened.close()


def test_billing_ui_saves_credit_sale_and_updates_customer_balance(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "billing-ui.sqlite3")
    database.initialize()
    sales = SalesService(database)
    customer_id = sales.create_customer("Test customer")
    medicine_id = StockService(database).create_medicine("Paracetamol", selling_rate_paisa=2000)
    StockService(database).add_batch(medicine_id, "BILL-1", date(2027, 1, 1), 6, 800, 2000)

    window = MainWindow(database)
    window.show()
    app.processEvents()
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    window.nav_buttons[4].click()
    window.sale_customer.setCurrentIndex(window.sale_customer.findData(customer_id))
    window.sale_payment_type.setCurrentIndex(window.sale_payment_type.findData("credit"))
    window.sale_quantity.setValue(2)
    next(button for button in window.findChildren(QPushButton) if button.text() == "Add to bill").click()
    assert len(window.sale_lines) == 1
    window.save_sale_button.click()
    app.processEvents()

    assert len(sales.sales()) == 1
    assert sales.customers()[0]["balance_paisa"] == 4000
    window.close()


def test_customer_credit_ui_receives_payment_and_opens_sms_reminder(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "credit-ui.sqlite3")
    database.initialize()
    sales = SalesService(database)
    customer_id = sales.create_customer("Udhaar customer", phone="9800000011")
    medicine_id = StockService(database).create_medicine("Cetirizine", selling_rate_paisa=2000)
    StockService(database).add_batch(medicine_id, "CR-1", date(2027, 1, 1), 5, 800, 2000)
    sales.create_sale("DMH-CREDIT-1", date.today(), "credit", [
        {"medicine_id": medicine_id, "quantity": 1, "selling_rate_paisa": 2000}
    ], customer_id=customer_id)

    window = MainWindow(database)
    window.show()
    app.processEvents()
    window.nav_buttons[5].click()
    app.processEvents()
    assert window.customer_credit_table.rowCount() == 1

    def accept_payment(dialog):
        dialog.amount.setValue(5)
        dialog.bill_no.setText("DMH-CREDIT-1")
        dialog.method.setCurrentText("cash")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CustomerPaymentDialog, "exec", accept_payment)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    window._receive_customer_payment()
    assert sales.customers()[0]["balance_paisa"] == 1500

    opened_urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened_urls.append(url.toString()) or True)
    window._send_customer_reminder()
    assert opened_urls[0].startswith("sms:9800000011?body=")
    assert window.ageing_table.rowCount() == 1
    window.close()


def test_billing_ui_return_restocks_original_batch_and_reduces_credit(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "return-ui.sqlite3")
    database.initialize()
    sales = SalesService(database)
    customer_id = sales.create_customer("Returning customer")
    medicine_id = StockService(database).create_medicine("Amoxicillin", selling_rate_paisa=3000)
    batch_id = StockService(database).add_batch(medicine_id, "RETURN-1", date(2027, 1, 1), 5, 1200, 3000)
    sale_id = sales.create_sale("DMH-RETURN-1", date.today(), "credit", [
        {"medicine_id": medicine_id, "quantity": 2, "selling_rate_paisa": 3000}
    ], customer_id=customer_id)

    window = MainWindow(database)
    window.show()
    app.processEvents()
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window._navigate(4)
    row = window.sale_history.findItems("DMH-RETURN-1", Qt.MatchFlag.MatchExactly)[0].row()
    window.sale_history.selectRow(row)
    window._return_selected_sale()

    with database.connect() as connection:
        assert connection.execute("SELECT quantity FROM batches WHERE id = ?", (batch_id,)).fetchone()[0] == 5
    assert sales.customers()[0]["balance_paisa"] == 0
    assert sales.sales()[0]["status"] == "returned"
    window.close()