from __future__ import annotations

import sqlite3
from datetime import date, datetime
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtCore import QLocale, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter

from models.database import Database
from reports.dealer_ledger_export import export_dealer_ledger_excel, export_dealer_ledger_pdf
from services.dealer_ledger_service import DealerLedgerService, LedgerError
from services.purchase_service import PurchaseError, PurchaseService
from services.customer_credit_service import CustomerCreditService
from services.sales_service import SalesError, SalesService
from services.stock_service import StockError, StockService
from ui.translations import translate_text

STYLE = """
QWidget { background: #f4f8f7; color: #193332; font-family: 'Segoe UI'; font-size: 11pt; }
QMainWindow { background: #f4f8f7; }
QLabel#shopTitle { font-size: 19pt; font-weight: 700; color: #123e3b; }
QLabel#pageTitle { font-size: 17pt; font-weight: 650; }
QLabel#muted { color: #607875; }
QPushButton { background: #087f78; color: white; border: 0; border-radius: 5px; padding: 9px 14px; font-weight: 600; }
QPushButton:hover { background: #066a64; }
QPushButton[secondary="true"] { background: #e1efed; color: #155d58; }
QPushButton[secondary="true"]:hover { background: #cce5e2; }
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #c6d8d5; border-radius: 4px; padding: 7px; min-height: 22px; }
QTableWidget { background: white; alternate-background-color: #f7fbfa; border: 1px solid #d7e4e2; gridline-color: #e6efed; }
QHeaderView::section { background: #e8f2f0; color: #255754; padding: 9px; border: 0; font-weight: 650; }
QPushButton#navButton { text-align: left; background: transparent; color: #d8ece9; padding: 11px 14px; }
QPushButton#navButton:hover, QPushButton#navButton[active="true"] { background: #17625c; color: white; }
QFrame#sidebar { background: #123e3b; }
QScrollArea#pageScrollArea { border: 0; background: transparent; }
QScrollArea#pageScrollArea QScrollBar:vertical { width: 12px; background: #e8f2f0; margin: 0; }
QScrollArea#pageScrollArea QScrollBar::handle:vertical { background: #78aaa5; border-radius: 5px; min-height: 28px; }
QScrollArea#sidebarScrollArea { border: 0; background: #123e3b; }
QScrollArea#sidebarScrollArea QScrollBar:vertical { width: 10px; background: #123e3b; margin: 0; }
QScrollArea#sidebarScrollArea QScrollBar::handle:vertical { background: #47837d; border-radius: 4px; min-height: 26px; }
"""


class EntryDialog(QDialog):
    current_language = "en"

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(translate_text(title, self.current_language))
        outer_layout = QVBoxLayout(self)
        self.fields_scroll = QScrollArea(self)
        self.fields_scroll.setObjectName("dialogFieldsScrollArea")
        self.fields_scroll.setWidgetResizable(True)
        fields = QWidget()
        self.form = QFormLayout(fields)
        self.fields_scroll.setWidget(fields)
        outer_layout.addWidget(self.fields_scroll, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(translate_text("Save", self.current_language))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(translate_text("Cancel", self.current_language))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        outer_layout.addWidget(self.buttons)
        self.resize(560, 600)

    def add_row(self, label: str, widget: QWidget) -> None:
        self.form.addRow(translate_text(label, self.current_language), widget)


class MedicineDialog(EntryDialog):
    def __init__(self, parent: QWidget | None = None, medicine: dict | None = None) -> None:
        super().__init__("Edit medicine" if medicine else "Add medicine", parent)
        self.name = QLineEdit(medicine["name"] if medicine else "")
        self.generic = QLineEdit(medicine["generic_name"] if medicine else "")
        self.category = QComboBox()
        self.category.addItems([translate_text(category, self.current_language) for category in ("tablet", "syrup", "injection", "ointment", "drops", "other")])
        if medicine:
            self.category.setCurrentText(medicine["category"])
        self.manufacturer = QLineEdit(medicine["manufacturer"] if medicine else "")
        self.pack_size = QLineEdit(medicine["unit_pack_size"] if medicine else "")
        self.barcode = QLineEdit(medicine["barcode"] or "" if medicine else "")
        self.mrp = self._money(medicine["mrp_paisa"] / 100 if medicine else 0)
        self.selling = self._money(medicine["selling_rate_paisa"] / 100 if medicine else 0)
        self.reorder = QSpinBox()
        self.reorder.setMaximum(10_000_000)
        self.reorder.setValue(medicine["reorder_level"] if medicine else 0)
        self.rack = QLineEdit(medicine["rack_location"] if medicine else "")
        self.prescription = QCheckBox("Prescription required")
        self.prescription.setChecked(bool(medicine["prescription_required"]) if medicine else False)
        for label, widget in (("Name", self.name), ("Generic / salt", self.generic), ("Category", self.category),
                              ("Manufacturer", self.manufacturer), ("Pack size", self.pack_size), ("Barcode", self.barcode),
                              ("MRP (Rs.)", self.mrp), ("Selling rate (Rs.)", self.selling),
                              ("Reorder level", self.reorder), ("Rack / shelf", self.rack), ("Prescription", self.prescription)):
            self.add_row(label, widget)

    @staticmethod
    def _money(value: float) -> QDoubleSpinBox:
        field = QDoubleSpinBox()
        field.setDecimals(2)
        field.setMaximum(999_999_999)
        field.setValue(value)
        return field

    def values(self) -> dict:
        return {
            "name": self.name.text(), "generic_name": self.generic.text(), "category": self.category.currentText(),
            "manufacturer": self.manufacturer.text(), "unit_pack_size": self.pack_size.text(),
            "barcode": self.barcode.text() or None, "mrp_paisa": round(self.mrp.value() * 100),
            "selling_rate_paisa": round(self.selling.value() * 100), "reorder_level": self.reorder.value(),
            "rack_location": self.rack.text(), "prescription_required": self.prescription.isChecked(),
        }


class BatchDialog(EntryDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Add stock batch", parent)
        self.batch = QLineEdit()
        self.expiry = QDateEdit()
        self.expiry.setCalendarPopup(True)
        self.expiry.setDate(date.today())
        self.manufactured = QDateEdit()
        self.manufactured.setCalendarPopup(True)
        self.manufactured.setDate(date.today())
        self.quantity = QSpinBox()
        self.quantity.setMaximum(10_000_000)
        self.purchase_rate = MedicineDialog._money(0)
        self.selling_rate = MedicineDialog._money(0)
        for label, widget in (("Batch number", self.batch), ("Manufacturing date", self.manufactured),
                              ("Expiry date", self.expiry), ("Quantity", self.quantity),
                              ("Purchase rate (Rs.)", self.purchase_rate), ("Selling rate (Rs.)", self.selling_rate)):
            self.add_row(label, widget)


class DealerDialog(EntryDialog):
    def __init__(self, parent: QWidget | None = None, dealer: dict | None = None) -> None:
        super().__init__("Edit dealer" if dealer else "Add dealer", parent)
        self.name = QLineEdit(dealer["name"] if dealer else "")
        self.company = QLineEdit(dealer["company"] if dealer else "")
        self.contact = QLineEdit(dealer["contact_person"] if dealer else "")
        self.phone = QLineEdit(dealer["phone"] if dealer else "")
        self.address = QLineEdit(dealer["address"] if dealer else "")
        self.pan_vat = QLineEdit(dealer["pan_vat"] if dealer else "")
        self.terms = QSpinBox()
        self.terms.setMaximum(3650)
        self.terms.setValue(dealer["credit_terms_days"] if dealer else 0)
        for label, widget in (("Dealer name", self.name), ("Company", self.company),
                              ("Contact person", self.contact), ("Phone", self.phone),
                              ("Address", self.address), ("PAN / VAT", self.pan_vat),
                              ("Credit terms (days)", self.terms)):
            self.add_row(label, widget)

    def values(self) -> dict:
        return {
            "name": self.name.text(), "company": self.company.text(),
            "contact_person": self.contact.text(), "phone": self.phone.text(),
            "address": self.address.text(), "pan_vat": self.pan_vat.text(),
            "credit_terms_days": self.terms.value(),
        }


class LedgerEntryDialog(EntryDialog):
    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        title = "Add invoice debit" if kind == "debit" else "Record payment credit"
        super().__init__(title, parent)
        self.kind = kind
        self.entry_date = QDateEdit()
        self.entry_date.setCalendarPopup(True)
        self.entry_date.setDate(date.today())
        self.amount = MedicineDialog._money(0)
        self.remark = QLineEdit()
        self.due_date = QDateEdit()
        self.due_date.setCalendarPopup(True)
        self.due_date.setDate(date.today())
        self.linked_invoice = QLineEdit()
        self.payment_method = QComboBox()
        self.payment_method.addItems(["cash", "cheque", "bank", "QR"])
        if kind == "debit":
            self.invoice_no = QLineEdit()
            self.add_row("Invoice date", self.entry_date)
            self.add_row("Invoice number", self.invoice_no)
            self.add_row("Amount (Rs.)", self.amount)
            self.add_row("Due date", self.due_date)
            self.add_row("Remark", self.remark)
        else:
            self.add_row("Payment date", self.entry_date)
            self.add_row("Amount (Rs.)", self.amount)
            self.add_row("Link to invoice (optional)", self.linked_invoice)
            self.add_row("Method", self.payment_method)
            self.add_row("Remark", self.remark)


class PurchaseItemDialog(EntryDialog):
    def __init__(self, database: Database, parent: QWidget | None = None) -> None:
        super().__init__("Add purchase item", parent)
        self.medicine = QComboBox()
        with database.connect() as connection:
            medicines = connection.execute("SELECT id, name FROM medicines ORDER BY name COLLATE NOCASE").fetchall()
        for medicine in medicines:
            self.medicine.addItem(medicine["name"], medicine["id"])
        self.batch = QLineEdit()
        self.manufacturing = QDateEdit()
        self.manufacturing.setCalendarPopup(True)
        self.manufacturing.setDate(date.today())
        self.expiry = QDateEdit()
        self.expiry.setCalendarPopup(True)
        self.expiry.setDate(date.today())
        self.quantity = QSpinBox()
        self.quantity.setMaximum(10_000_000)
        self.free_quantity = QSpinBox()
        self.free_quantity.setMaximum(10_000_000)
        self.purchase_rate = MedicineDialog._money(0)
        self.selling_rate = MedicineDialog._money(0)
        self.discount = MedicineDialog._money(0)
        self.tax = MedicineDialog._money(0)
        for label, widget in (("Medicine", self.medicine), ("Batch number", self.batch),
                              ("Manufacturing date", self.manufacturing), ("Expiry date", self.expiry),
                              ("Billed quantity", self.quantity), ("Free quantity", self.free_quantity),
                              ("Purchase rate (Rs.)", self.purchase_rate), ("Selling rate (Rs.)", self.selling_rate),
                              ("Discount (Rs.)", self.discount), ("Tax (Rs.)", self.tax)):
            self.add_row(label, widget)

    def values(self) -> dict | None:
        medicine_id = self.medicine.currentData()
        if medicine_id is None:
            return None
        return {
            "medicine_id": int(medicine_id), "medicine_name": self.medicine.currentText(),
            "batch_number": self.batch.text(), "manufacturing_date": self.manufacturing.date().toPython(),
            "expiry_date": self.expiry.date().toPython(), "quantity": self.quantity.value(),
            "free_quantity": self.free_quantity.value(),
            "purchase_rate_paisa": round(self.purchase_rate.value() * 100),
            "selling_rate_paisa": round(self.selling_rate.value() * 100),
            "discount_paisa": round(self.discount.value() * 100), "tax_paisa": round(self.tax.value() * 100),
        }


class CustomerDialog(EntryDialog):
    def __init__(self, parent: QWidget | None = None, customer: dict | None = None) -> None:
        super().__init__("Edit customer" if customer else "Add customer", parent)
        self.name = QLineEdit(customer["name"] if customer else "")
        self.phone = QLineEdit(customer["phone"] if customer else "")
        self.address = QLineEdit(customer["address"] if customer else "")
        self.credit_limit = MedicineDialog._money(customer["credit_limit_paisa"] / 100 if customer else 0)
        self.add_row("Customer name", self.name)
        self.add_row("Phone", self.phone)
        self.add_row("Address", self.address)
        self.add_row("Credit limit (Rs.)", self.credit_limit)

    def values(self) -> dict:
        return {
            "name": self.name.text(), "phone": self.phone.text(), "address": self.address.text(),
            "credit_limit_paisa": round(self.credit_limit.value() * 100),
        }


class CustomerPaymentDialog(EntryDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Receive customer payment", parent)
        self.paid_on = QDateEdit()
        self.paid_on.setCalendarPopup(True)
        self.paid_on.setDate(date.today())
        self.amount = MedicineDialog._money(0)
        self.bill_no = QLineEdit()
        self.method = QComboBox()
        self.method.addItems(["cash", "online", "bank", "QR"])
        self.remark = QLineEdit()
        for label, widget in (("Payment date", self.paid_on), ("Amount (Rs.)", self.amount),
                              ("Link to bill (optional)", self.bill_no), ("Method", self.method),
                              ("Remark", self.remark)):
            self.add_row(label, widget)


class MainWindow(QMainWindow):
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self.stock = StockService(database)
        self.ledger_service = DealerLedgerService(database)
        self.purchase_service = PurchaseService(database)
        self.sales_service = SalesService(database)
        self.customer_credit_service = CustomerCreditService(database)
        with self.database.connect() as connection:
            self.language = connection.execute("SELECT language FROM shop_settings WHERE id = 1").fetchone()[0]
        self.setWindowTitle("Dipesh Medical Hall")
        self.resize(1360, 820)
        self.setMinimumSize(1050, 680)
        self.setStyleSheet(STYLE)
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(225)
        sidebar.setStyleSheet("QWidget#sidebar { background: #123e3b; }")
        nav_layout = QVBoxLayout(sidebar)
        nav_layout.setContentsMargins(12, 18, 12, 16)
        nav_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        shop = QLabel("DIPESH\nMEDICAL HALL")
        shop.setStyleSheet("font-size: 15pt; font-weight: 700; color: #ffffff; background: transparent; padding: 5px 8px;")
        nav_layout.addWidget(shop)
        address = QLabel("Biratnagar-11, Morang, Nepal")
        address.setStyleSheet("color: #b7d8d4; background: transparent; font-size: 9pt; padding: 0 8px;")
        nav_layout.addWidget(address, alignment=Qt.AlignmentFlag.AlignLeft)
        language_label = QLabel("Language / भाषा")
        language_label.setStyleSheet("color: #b7d8d4; background: transparent; font-size: 9pt; padding: 10px 8px 2px;")
        nav_layout.addWidget(language_label)
        self.language_selector = QComboBox()
        self.language_selector.addItem("English", "en")
        self.language_selector.addItem("नेपाली", "ne")
        self.language_selector.setCurrentIndex(self.language_selector.findData(self.language))
        self.language_selector.setAccessibleName("Language / भाषा")
        nav_layout.addWidget(self.language_selector)
        self.language_selector.currentIndexChanged.connect(self._change_language)
        nav_layout.addSpacing(18)
        self.pages = QStackedWidget()
        self.nav_buttons: list[QPushButton] = []
        for index, (label, page) in enumerate((
            ("Dashboard", self._dashboard()),
            ("Medicines & Stock", self._medicines_page()),
            ("Dealer Ledger", self._dealer_ledger_page()),
            ("Purchases", self._purchases_page()),
            ("Billing (Sales)", self._billing_page()),
            ("Customer Credit", self._customer_credit_page()),
        )):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setProperty("active", index == 0)
            button.clicked.connect(lambda _checked=False, page_index=index: self._navigate(page_index))
            nav_layout.addWidget(button)
            self.nav_buttons.append(button)
            page_scroll = QScrollArea()
            page_scroll.setObjectName("pageScrollArea")
            page_scroll.setWidgetResizable(True)
            if page.layout() is not None:
                page.layout().setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
            page_scroll.setWidget(page)
            self.pages.addWidget(page_scroll)
        for label in ("Expenses", "Reports", "Settings"):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setToolTip("Not available yet; planned for a later build phase")
            button.clicked.connect(lambda _checked=False, feature=label: self._show_deferred_feature(feature))
            nav_layout.addWidget(button)
        nav_layout.addStretch(1)
        version = QLabel("Offline · local database")
        version.setStyleSheet("color: #a8ceca; background: transparent; padding: 8px;")
        nav_layout.addWidget(version)
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setObjectName("sidebarScrollArea")
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFixedWidth(245)
        sidebar_scroll.setWidget(sidebar)
        outer.addWidget(sidebar_scroll)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 24, 28, 22)
        self.header = QLabel("Dashboard")
        self.header.setObjectName("pageTitle")
        content_layout.addWidget(self.header)
        address = QLabel("Dipesh Medical Hall  ·  Biratnagar-11, Morang, Nepal")
        address.setObjectName("muted")
        content_layout.addWidget(address)
        content_layout.addSpacing(16)
        content_layout.addWidget(self.pages)
        outer.addWidget(content, 1)
        self.setCentralWidget(root)
        self.pages.currentChanged.connect(self._update_page_title)
        self._apply_language()

    def _change_language(self, _index: int) -> None:
        language = self.language_selector.currentData()
        if language not in {"en", "ne"}:
            return
        self.language = language
        EntryDialog.current_language = language
        with self.database.connect() as connection:
            connection.execute("UPDATE shop_settings SET language = ? WHERE id = 1", (language,))
        self._apply_language()

    def _update_page_title(self, index: int) -> None:
        title = ["Dashboard", "Medicines & Stock", "Dealer Ledger", "Purchases", "Billing (Sales)", "Customer Credit"][index]
        self.header.setText(translate_text(title, self.language))

    def _apply_language(self) -> None:
        EntryDialog.current_language = self.language
        for label in self.findChildren(QLabel):
            label.setText(translate_text(translate_text(label.text(), "en"), self.language))
        for button in self.findChildren(QPushButton):
            button.setText(translate_text(translate_text(button.text(), "en"), self.language))
            button.setToolTip(translate_text(translate_text(button.toolTip(), "en"), self.language))
        for field in self.findChildren(QLineEdit):
            field.setPlaceholderText(translate_text(translate_text(field.placeholderText(), "en"), self.language))
        for combo in self.findChildren(QComboBox):
            current_data = combo.currentData()
            combo.blockSignals(True)
            for item_index in range(combo.count()):
                current_text = combo.itemText(item_index)
                combo.setItemText(item_index, translate_text(translate_text(current_text, "en"), self.language))
            if current_data is not None:
                combo.setCurrentIndex(combo.findData(current_data))
            combo.blockSignals(False)
        for table in self.findChildren(QTableWidget):
            for column in range(table.columnCount()):
                item = table.horizontalHeaderItem(column)
                if item:
                    item.setText(translate_text(translate_text(item.text(), "en"), self.language))
        self._update_page_title(self.pages.currentIndex())
        self._refresh_dashboard()
        if self.pages.currentIndex() == 1:
            self._refresh_stock_table()
        elif self.pages.currentIndex() == 2:
            self._refresh_ledger_table()
        elif self.pages.currentIndex() == 3:
            self._refresh_purchase_lines()
            self._refresh_purchases()
        elif self.pages.currentIndex() == 4:
            self._refresh_sale_medicines()
            self._refresh_sales()
        elif self.pages.currentIndex() == 5:
            self._refresh_credit_customers()
            self._refresh_customer_credit_ledger()
            self._refresh_ageing()

    def _show_deferred_feature(self, feature: str) -> None:
        if self.language == "ne":
            feature = translate_text(feature, "ne")
            self._information(f"{feature} तयार छैन", f"{feature} पछिल्लो चरणमा उपलब्ध हुनेछ; यो संस्करणमा उपलब्ध छैन।")
            return
        self._information(
            f"{feature} is not ready",
            f"{feature} is planned for a later build phase and is not available in this version.",
        )

    def _localized_text(self, text: str) -> str:
        translated = translate_text(text, self.language)
        if self.language == "ne" and text.startswith("Written off "):
            count = text.split(" ", 2)[2].split(" ", 1)[0]
            return f"म्याद सकिएका {count} वटा स्टक हटाइयो।"
        if self.language == "ne" and text.startswith("Dealer ledger saved to:"):
            return text.replace("Dealer ledger saved to:", "डिलर खाता यहाँ सुरक्षित भयो:")
        if self.language == "ne" and text.startswith("Bill ") and text.endswith(" saved."):
            return f"बिल {text[5:-7]} सुरक्षित भयो।"
        return translated

    def _information(self, title: str, message: str) -> None:
        QMessageBox.information(self, self._localized_text(title), self._localized_text(message))

    def _warning(self, title: str, message: str) -> None:
        QMessageBox.warning(self, self._localized_text(title), self._localized_text(message))

    def _confirm(self, title: str, message: str) -> QMessageBox.StandardButton:
        return QMessageBox.question(self, self._localized_text(title), self._localized_text(message))

    def _navigate(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setProperty("active", button_index == index)
            button.style().unpolish(button)
            button.style().polish(button)
        if index == 0:
            self._refresh_dashboard()
        elif index == 1:
            self._refresh_stock_table()
        elif index == 2:
            self._refresh_ledger_dealers()
        elif index == 3:
            self._refresh_purchases()
        elif index == 4:
            self._refresh_sale_medicines()
            self._refresh_sales()
        else:
            self._refresh_credit_customers()
            self._refresh_customer_credit_ledger()
            self._refresh_ageing()

    def _billing_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        self.sale_lines: list[dict[str, int]] = []
        self.last_sale_id: int | None = None
        self.resumed_held_id: int | None = None
        line_row = QHBoxLayout()
        self.sale_search = QLineEdit()
        self.sale_search.setPlaceholderText("Search / scan medicine barcode")
        self.sale_search.textChanged.connect(self._refresh_sale_medicines)
        self.sale_medicine = QComboBox()
        self.sale_quantity = QSpinBox()
        self.sale_quantity.setRange(1, 10_000_000)
        self.sale_quantity.setValue(1)
        self.sale_line_discount = MedicineDialog._money(0)
        add_line = QPushButton("Add to bill")
        add_line.clicked.connect(self._add_sale_line)
        for widget in (self.sale_search, self.sale_medicine, self.sale_quantity, self.sale_line_discount, add_line):
            line_row.addWidget(widget)
        layout.addLayout(line_row)
        self.sale_table = QTableWidget(0, 6)
        self.sale_table.setHorizontalHeaderLabels(["Medicine", "Qty", "Rate", "Discount", "Line total", "Batch allocation"])
        self.sale_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sale_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sale_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.sale_table, 2)
        sale_actions = QHBoxLayout()
        remove_line = QPushButton("Remove selected item")
        remove_line.setProperty("secondary", True)
        remove_line.clicked.connect(self._remove_sale_line)
        self.sale_bill_discount = MedicineDialog._money(0)
        self.sale_total = QLabel("Bill total: Rs. 0.00")
        sale_actions.addWidget(remove_line)
        sale_actions.addWidget(QLabel("Bill discount (Rs.)"))
        sale_actions.addWidget(self.sale_bill_discount)
        sale_actions.addStretch(1)
        sale_actions.addWidget(self.sale_total)
        layout.addLayout(sale_actions)
        payment_row = QHBoxLayout()
        self.sale_payment_type = QComboBox()
        self.sale_payment_type.addItem("Cash", "cash")
        self.sale_payment_type.addItem("Online / QR", "online")
        self.sale_payment_type.addItem("Credit", "credit")
        self.sale_customer = QComboBox()
        add_customer = QPushButton("+ Customer")
        add_customer.setProperty("secondary", True)
        add_customer.clicked.connect(self._add_customer)
        self.held_bill_selector = QComboBox()
        resume_bill = QPushButton("Resume held bill")
        resume_bill.setProperty("secondary", True)
        resume_bill.clicked.connect(self._resume_held_bill)
        hold_bill = QPushButton("Hold bill")
        hold_bill.setProperty("secondary", True)
        hold_bill.clicked.connect(self._hold_bill)
        payment_row.addWidget(QLabel("Payment"))
        payment_row.addWidget(self.sale_payment_type)
        payment_row.addWidget(QLabel("Customer"))
        payment_row.addWidget(self.sale_customer, 1)
        payment_row.addWidget(add_customer)
        payment_row.addWidget(self.held_bill_selector)
        payment_row.addWidget(resume_bill)
        payment_row.addWidget(hold_bill)
        layout.addLayout(payment_row)
        save_row = QHBoxLayout()
        self.save_sale_button = QPushButton("Save bill (F2)")
        self.save_sale_button.clicked.connect(self._save_sale)
        print_sale_button = QPushButton("Print selected (F5)")
        print_sale_button.setProperty("secondary", True)
        print_sale_button.clicked.connect(self._print_selected_sale)
        save_row.addStretch(1)
        save_row.addWidget(print_sale_button)
        save_row.addWidget(self.save_sale_button)
        layout.addLayout(save_row)
        save_shortcut = QShortcut(QKeySequence("F2"), page)
        save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        save_shortcut.activated.connect(self._save_sale)
        print_shortcut = QShortcut(QKeySequence("F5"), page)
        print_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        print_shortcut.activated.connect(self._print_selected_sale)
        history_header = QHBoxLayout()
        history_header.addWidget(QLabel("Sales history"))
        self.sale_history_search = QLineEdit()
        self.sale_history_search.setPlaceholderText("Search bill or customer")
        self.sale_history_search.textChanged.connect(self._refresh_sales)
        history_header.addStretch(1)
        history_header.addWidget(self.sale_history_search)
        return_sale = QPushButton("Return remaining items")
        return_sale.setProperty("secondary", True)
        return_sale.clicked.connect(self._return_selected_sale)
        history_header.addWidget(return_sale)
        layout.addLayout(history_header)
        self.sale_history = QTableWidget(0, 6)
        self.sale_history.setHorizontalHeaderLabels(["Date", "Bill No.", "Customer", "Payment", "Total", "Status"])
        self.sale_history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sale_history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sale_history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sale_history.setMinimumHeight(160)
        layout.addWidget(self.sale_history, 1)
        self.sale_bill_discount.valueChanged.connect(self._refresh_sale_lines)
        self._refresh_customers_for_sale()
        self._refresh_held_bills()
        self._refresh_sale_medicines()
        return page

    def _customer_credit_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        customer_row = QHBoxLayout()
        self.credit_customer = QComboBox()
        self.credit_customer.currentIndexChanged.connect(self._refresh_customer_credit_ledger)
        add_customer = QPushButton("+ Customer")
        add_customer.clicked.connect(self._add_customer)
        edit_customer = QPushButton("Edit customer")
        edit_customer.setProperty("secondary", True)
        edit_customer.clicked.connect(self._edit_customer)
        receive_payment = QPushButton("Receive payment")
        receive_payment.clicked.connect(self._receive_customer_payment)
        send_reminder = QPushButton("Send reminder")
        send_reminder.setProperty("secondary", True)
        send_reminder.clicked.connect(self._send_customer_reminder)
        for widget in (QLabel("Customer"), self.credit_customer, add_customer, edit_customer, receive_payment, send_reminder):
            customer_row.addWidget(widget)
        layout.addLayout(customer_row)
        filter_row = QHBoxLayout()
        self.credit_start = QDateEdit()
        self.credit_start.setCalendarPopup(True)
        self.credit_start.setDate(date.today().replace(day=1))
        self.credit_end = QDateEdit()
        self.credit_end.setCalendarPopup(True)
        self.credit_end.setDate(date.today())
        self.credit_start.dateChanged.connect(self._refresh_customer_credit_ledger)
        self.credit_end.dateChanged.connect(self._refresh_customer_credit_ledger)
        filter_row.addWidget(QLabel("From"))
        filter_row.addWidget(self.credit_start)
        filter_row.addWidget(QLabel("To"))
        filter_row.addWidget(self.credit_end)
        self.customer_credit_summary = QLabel("Select a customer to view credit")
        filter_row.addStretch(1)
        filter_row.addWidget(self.customer_credit_summary)
        layout.addLayout(filter_row)
        self.customer_credit_table = QTableWidget(0, 7)
        self.customer_credit_table.setHorizontalHeaderLabels(["Date", "Bill No.", "Debit", "Date", "Credit", "Remarks", "Balance"])
        self.customer_credit_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.customer_credit_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.customer_credit_table, 2)
        age_row = QHBoxLayout()
        age_row.addWidget(QLabel("Ageing"))
        self.ageing_bucket = QComboBox()
        self.ageing_bucket.addItems(["0-30", "31-60", "61-90", "90+"])
        self.ageing_bucket.currentIndexChanged.connect(self._refresh_ageing)
        self.ageing_total = QLabel()
        age_row.addWidget(self.ageing_bucket)
        age_row.addStretch(1)
        age_row.addWidget(self.ageing_total)
        layout.addLayout(age_row)
        self.ageing_table = QTableWidget(0, 5)
        self.ageing_table.setHorizontalHeaderLabels(["Customer", "Phone", "Bill No.", "Age (days)", "Due"])
        self.ageing_table.setMaximumHeight(180)
        self.ageing_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.ageing_table)
        self._refresh_credit_customers()
        self._refresh_customer_credit_ledger()
        self._refresh_ageing()
        return page

    def _refresh_customers_for_sale(self) -> None:
        if not hasattr(self, "sale_customer"):
            return
        selected = self.sale_customer.currentData()
        self.sale_customer.blockSignals(True)
        self.sale_customer.clear()
        self.sale_customer.addItem("Walk-in customer", None)
        for customer in self.sales_service.customers():
            self.sale_customer.addItem(customer["name"], customer["id"])
        if selected is not None:
            index = self.sale_customer.findData(selected)
            if index >= 0:
                self.sale_customer.setCurrentIndex(index)
        self.sale_customer.blockSignals(False)

    def _refresh_credit_customers(self, *_args) -> None:
        if not hasattr(self, "credit_customer"):
            return
        selected = self.credit_customer.currentData()
        self.credit_customer.blockSignals(True)
        self.credit_customer.clear()
        for customer in self.sales_service.customers():
            self.credit_customer.addItem(customer["name"], customer["id"])
        if selected is not None:
            index = self.credit_customer.findData(selected)
            if index >= 0:
                self.credit_customer.setCurrentIndex(index)
        self.credit_customer.blockSignals(False)

    def _add_customer(self) -> None:
        dialog = CustomerDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            customer_id = self.sales_service.create_customer(**dialog.values())
        except SalesError as error:
            self._show_error(error)
            return
        self._refresh_customers_for_sale()
        self._refresh_credit_customers()
        for selector in (getattr(self, "sale_customer", None), getattr(self, "credit_customer", None)):
            if selector is not None:
                index = selector.findData(customer_id)
                if index >= 0:
                    selector.setCurrentIndex(index)

    def _edit_customer(self) -> None:
        customer_id = self.credit_customer.currentData()
        if customer_id is None:
            self._information("Select customer", "Select a customer to edit.")
            return
        customer = next((row for row in self.sales_service.customers() if row["id"] == customer_id), None)
        if not customer:
            return
        dialog = CustomerDialog(self, customer)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.sales_service.update_customer(int(customer_id), **dialog.values())
        except SalesError as error:
            self._show_error(error)
            return
        self._refresh_credit_customers()
        self._refresh_customers_for_sale()

    def _refresh_sale_medicines(self, *_args) -> None:
        if not hasattr(self, "sale_medicine"):
            return
        selected = self.sale_medicine.currentData()
        self.sale_medicine.blockSignals(True)
        self.sale_medicine.clear()
        for medicine in self.stock.search_medicines(self.sale_search.text(), limit=250):
            if medicine["usable_quantity"] > 0:
                self.sale_medicine.addItem(
                    f"{medicine['name']}  ·  {medicine['usable_quantity']} available",
                    int(medicine["id"]),
                )
                self.sale_medicine.setItemData(self.sale_medicine.count() - 1, medicine["selling_rate_paisa"], Qt.ItemDataRole.UserRole + 1)
        if selected is not None:
            index = self.sale_medicine.findData(selected)
            if index >= 0:
                self.sale_medicine.setCurrentIndex(index)
        self.sale_medicine.blockSignals(False)

    def _add_sale_line(self) -> None:
        medicine_id = self.sale_medicine.currentData()
        if medicine_id is None:
            self._information("No medicines", "No medicine with usable stock matches this search.")
            return
        rate = int(self.sale_medicine.currentData(Qt.ItemDataRole.UserRole + 1) or 0)
        discount = round(self.sale_line_discount.value() * 100)
        self.sale_lines.append({
            "medicine_id": int(medicine_id), "quantity": self.sale_quantity.value(),
            "selling_rate_paisa": rate, "discount_paisa": discount,
            "medicine_name": self.sale_medicine.currentText().split("  ·  ")[0],
        })
        self._refresh_sale_lines()

    def _remove_sale_line(self) -> None:
        row = self.sale_table.currentRow()
        if row >= 0:
            self.sale_lines.pop(row)
            self._refresh_sale_lines()

    def _refresh_sale_lines(self) -> None:
        if not hasattr(self, "sale_table"):
            return
        self.sale_table.setRowCount(len(self.sale_lines))
        subtotal = 0
        for row_index, item in enumerate(self.sale_lines):
            total = item["quantity"] * item["selling_rate_paisa"] - item["discount_paisa"]
            subtotal += total
            values = [item["medicine_name"], str(item["quantity"]), f"Rs. {item['selling_rate_paisa'] / 100:,.2f}",
                      f"Rs. {item['discount_paisa'] / 100:,.2f}", f"Rs. {total / 100:,.2f}", "FEFO"]
            for column, value in enumerate(values):
                self.sale_table.setItem(row_index, column, QTableWidgetItem(str(value)))
        total = max(0, subtotal - round(self.sale_bill_discount.value() * 100))
        if self.language == "ne":
            self.sale_total.setText(f"बिल जम्मा: रु. {total / 100:,.2f}")
        else:
            self.sale_total.setText(f"Bill total: Rs. {total / 100:,.2f}")

    def _hold_bill(self) -> None:
        if not self.sale_lines:
            self._information("Add items", "Add at least one item before holding the bill.")
            return
        bill_no = f"HOLD-{datetime.now():%Y%m%d-%H%M%S-%f}"
        payload = {
            "items": [{key: value for key, value in item.items() if key != "medicine_name"} for item in self.sale_lines],
            "customer_id": self.sale_customer.currentData(),
            "payment_type": self.sale_payment_type.currentData(),
            "bill_discount_paisa": round(self.sale_bill_discount.value() * 100),
        }
        try:
            self.sales_service.hold_bill(bill_no, payload)
        except SalesError as error:
            self._show_error(error)
            return
        self.sale_lines.clear()
        self._refresh_sale_lines()
        self._refresh_held_bills()
        self._information("Bill held", "The bill was held and can be resumed later.")

    def _refresh_held_bills(self) -> None:
        if not hasattr(self, "held_bill_selector"):
            return
        self.held_bill_selector.clear()
        for bill in self.sales_service.held_bills():
            self.held_bill_selector.addItem(bill["bill_no"], bill["id"])

    def _resume_held_bill(self) -> None:
        held_id = self.held_bill_selector.currentData()
        if held_id is None:
            self._information("Select held bill", "There are no held bills to resume.")
            return
        try:
            held = self.sales_service.resume_bill(int(held_id))
        except SalesError as error:
            self._show_error(error)
            return
        payload = held["payload"]
        self.sale_lines = []
        for line in payload["items"]:
            with self.database.connect() as connection:
                medicine = connection.execute("SELECT name FROM medicines WHERE id = ?", (line["medicine_id"],)).fetchone()
            if medicine:
                self.sale_lines.append({**line, "medicine_name": medicine["name"]})
        self.sale_bill_discount.setValue(payload.get("bill_discount_paisa", 0) / 100)
        payment_index = self.sale_payment_type.findData(payload.get("payment_type", "cash"))
        if payment_index >= 0:
            self.sale_payment_type.setCurrentIndex(payment_index)
        customer_index = self.sale_customer.findData(payload.get("customer_id"))
        if customer_index >= 0:
            self.sale_customer.setCurrentIndex(customer_index)
        self._refresh_sale_lines()
        self.resumed_held_id = int(held_id)

    def _save_sale(self) -> None:
        if not self.sale_lines:
            self._information("Add items", "Add at least one item to the bill.")
            return
        payment_type = self.sale_payment_type.currentData()
        customer_id = self.sale_customer.currentData()
        bill_total = max(0, sum(item["quantity"] * item["selling_rate_paisa"] - item["discount_paisa"] for item in self.sale_lines) - round(self.sale_bill_discount.value() * 100))
        if payment_type == "credit":
            if customer_id is None:
                self._information("Select customer", "A customer is required for credit sales.")
                return
            customer = next((row for row in self.sales_service.customers() if row["id"] == customer_id), None)
            if customer and customer["credit_limit_paisa"] and customer["balance_paisa"] + bill_total > customer["credit_limit_paisa"]:
                answer = self._confirm("Credit limit exceeded", "This sale will exceed the customer's credit limit. Continue?")
                if answer != QMessageBox.StandardButton.Yes:
                    return
        bill_no = f"DMH-{datetime.now():%Y%m%d-%H%M%S-%f}"
        try:
            sale_id = self.sales_service.create_sale(
                bill_no, date.today(), payment_type,
                [{key: value for key, value in item.items() if key != "medicine_name"} for item in self.sale_lines],
                customer_id=int(customer_id) if customer_id is not None else None,
                bill_discount_paisa=round(self.sale_bill_discount.value() * 100),
            )
        except (SalesError, sqlite3.IntegrityError) as error:
            self._show_error(error)
            return
        self.last_sale_id = sale_id
        if self.resumed_held_id is not None:
            self.sales_service.delete_held_bill(self.resumed_held_id)
            self.resumed_held_id = None
            self._refresh_held_bills()
        self.sale_lines.clear()
        self.sale_bill_discount.setValue(0)
        self._refresh_sale_lines()
        self._refresh_sale_medicines()
        self._refresh_sales()
        self._refresh_customer_credit_ledger()
        self._refresh_ageing()
        self._information("Sale saved", f"Bill {bill_no} saved.")

    def _refresh_sales(self, *_args) -> None:
        if not hasattr(self, "sale_history"):
            return
        rows = self.sales_service.sales(self.sale_history_search.text(), limit=250)
        self.sale_history.setRowCount(len(rows))
        for row_index, sale in enumerate(rows):
            payment_text = sale["payment_type"].title()
            status_text = sale["status"].replace("_", " ").title()
            values = [sale["sale_date"], sale["bill_no"], sale["customer_name"] or translate_text("Walk-in customer", self.language),
                      translate_text(payment_text, self.language), f"Rs. {sale['total_paisa'] / 100:,.2f}", translate_text(status_text, self.language)]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column == 1:
                    cell.setData(Qt.ItemDataRole.UserRole, int(sale["id"]))
                self.sale_history.setItem(row_index, column, cell)

    def _selected_sale_id(self) -> int | None:
        row = self.sale_history.currentRow()
        if row < 0:
            return None
        return self.sale_history.item(row, 1).data(Qt.ItemDataRole.UserRole)

    def _return_selected_sale(self) -> None:
        sale_id = self._selected_sale_id()
        if sale_id is None:
            self._information("Select sale", "Select a sale bill to return.")
            return
        remaining = [
            {"sale_item_id": item["id"], "quantity": item["quantity"] - item["returned_quantity"]}
            for item in self.sales_service.sale_items(int(sale_id))
            if item["quantity"] > item["returned_quantity"]
        ]
        if not remaining:
            self._information("Already returned", "All items on this bill have already been returned.")
            return
        if self._confirm("Confirm return", "Return all remaining quantities on this bill and restock their original batches?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.sales_service.return_items(int(sale_id), remaining, remark="Customer return")
        except SalesError as error:
            self._show_error(error)
            return
        self._refresh_sales()
        self._refresh_sale_medicines()
        self._refresh_customer_credit_ledger()
        self._refresh_ageing()
        self._information("Return saved", "Returned quantities were put back in their original batches.")

    def _print_selected_sale(self) -> None:
        sale_id = self._selected_sale_id() or self.last_sale_id
        if sale_id is None:
            self._information("Select sale", "Save or select a bill before printing.")
            return
        with self.database.connect() as connection:
            sale = connection.execute(
                """SELECT s.*, c.name AS customer_name FROM sales s LEFT JOIN customers c ON c.id=s.customer_id WHERE s.id=?""",
                (sale_id,),
            ).fetchone()
        if sale is None:
            return
        rows = self.sales_service.sale_items(int(sale_id))
        body = "".join(
            f"<tr><td>{escape(str(item['medicine_name']))}</td><td>{item['quantity']}</td><td>{item['selling_rate_paisa'] / 100:,.2f}</td><td>{item['line_total_paisa'] / 100:,.2f}</td></tr>"
            for item in rows
        )
        document = QTextDocument()
        document.setHtml(
            f"<h2>Dipesh Medical Hall</h2><p>Biratnagar-11, Morang, Nepal</p>"
            f"<p>Bill: {escape(str(sale['bill_no']))} &nbsp; Date: {escape(str(sale['sale_date']))}</p>"
            f"<p>Customer: {escape(str(sale['customer_name'] or 'Walk-in'))}</p>"
            f"<table border='1' cellspacing='0' cellpadding='5'><tr><th>Medicine</th><th>Qty</th><th>Rate</th><th>Amount</th></tr>{body}</table>"
            f"<h3>Total: Rs. {sale['total_paisa'] / 100:,.2f}</h3>"
        )
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        preview = QPrintPreviewDialog(printer, self)
        preview.paintRequested.connect(document.print)
        preview.exec()

    def _refresh_customer_credit_ledger(self, *_args) -> None:
        if not hasattr(self, "customer_credit_table"):
            return
        customer_id = self.credit_customer.currentData()
        if customer_id is None:
            self.customer_credit_table.setRowCount(0)
            self.customer_credit_summary.setText(translate_text("Select or add a customer", self.language))
            return
        try:
            report = self.customer_credit_service.customer_ledger(
                int(customer_id), self.credit_start.date().toPython(), self.credit_end.date().toPython(), limit=250,
            )
        except SalesError as error:
            self._show_error(error)
            return
        entries = report["entries"]
        self.customer_credit_table.setRowCount(len(entries))
        for row_index, entry in enumerate(entries):
            values = [entry["display_date"], entry["invoice_no"] or "",
                      f"Rs. {entry['debit_paisa'] / 100:,.2f}" if entry["debit_paisa"] else "",
                      entry["display_payment_date"], f"Rs. {entry['credit_paisa'] / 100:,.2f}" if entry["credit_paisa"] else "",
                      entry["remark"], f"Rs. {entry['balance_paisa'] / 100:,.2f}"]
            for column, value in enumerate(values):
                self.customer_credit_table.setItem(row_index, column, QTableWidgetItem(str(value)))
        if self.language == "ne":
            self.customer_credit_summary.setText(
                f"सुरु बाँकी रु. {report['opening_balance_paisa'] / 100:,.2f} | डेबिट रु. {report['total_debit_paisa'] / 100:,.2f} | "
                f"क्रेडिट रु. {report['total_credit_paisa'] / 100:,.2f} | तिर्न बाँकी रु. {report['closing_balance_paisa'] / 100:,.2f}"
            )
        else:
            self.customer_credit_summary.setText(
                f"Opening Rs. {report['opening_balance_paisa'] / 100:,.2f} | Debit Rs. {report['total_debit_paisa'] / 100:,.2f} | "
                f"Credit Rs. {report['total_credit_paisa'] / 100:,.2f} | Due Rs. {report['closing_balance_paisa'] / 100:,.2f}"
            )

    def _receive_customer_payment(self) -> None:
        customer_id = self.credit_customer.currentData()
        if customer_id is None:
            self._information("Select customer", "Select a customer before receiving payment.")
            return
        dialog = CustomerPaymentDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.customer_credit_service.receive_payment(
                int(customer_id), dialog.paid_on.date().toPython(), round(dialog.amount.value() * 100),
                linked_bill_no=dialog.bill_no.text(), payment_method=dialog.method.currentText(),
                remark=dialog.remark.text(),
            )
        except (SalesError, sqlite3.IntegrityError) as error:
            self._show_error(error)
            return
        self._refresh_customer_credit_ledger()
        self._refresh_ageing()

    def _refresh_ageing(self, *_args) -> None:
        if not hasattr(self, "ageing_table"):
            return
        bucket = self.ageing_bucket.currentText()
        if bucket not in {"0-30", "31-60", "61-90", "90+"}:
            return
        rows = self.customer_credit_service.ageing().get(bucket, [])
        self.ageing_table.setRowCount(len(rows))
        total = 0
        for row_index, item in enumerate(rows):
            total += item["balance_paisa"]
            values = [item["customer_name"], item["phone"], item["invoice_no"], str(item["age_days"]),
                      f"Rs. {item['balance_paisa'] / 100:,.2f}"]
            for column, value in enumerate(values):
                self.ageing_table.setItem(row_index, column, QTableWidgetItem(str(value)))
        self.ageing_total.setText(
            f"{len(rows)} ग्राहक · रु. {total / 100:,.2f}" if self.language == "ne"
            else f"{len(rows)} customers · Rs. {total / 100:,.2f}"
        )

    def _send_customer_reminder(self) -> None:
        customer_id = self.credit_customer.currentData()
        if customer_id is None:
            self._information("Select customer", "Select a customer to send a reminder.")
            return
        try:
            url = self.customer_credit_service.reminder_url(int(customer_id))
        except SalesError as error:
            self._show_error(error)
            return
        if not QDesktopServices.openUrl(QUrl(url)):
            self._warning("No SMS application", "No default SMS application is configured on this computer.")

    def _dashboard(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        summary = QLabel("Stock overview")
        summary.setStyleSheet("font-size: 13pt; font-weight: 650;")
        layout.addWidget(summary)
        self.dashboard_summary = QLabel()
        self.dashboard_summary.setStyleSheet("font-size: 12pt; background: white; border: 1px solid #d7e4e2; border-radius: 5px; padding: 18px;")
        layout.addWidget(self.dashboard_summary)
        alert_title = QLabel("Stock alerts")
        alert_title.setStyleSheet("font-size: 13pt; font-weight: 650; margin-top: 14px;")
        layout.addWidget(alert_title)
        self.dashboard_alerts = QLabel()
        self.dashboard_alerts.setStyleSheet("font-size: 11pt; background: white; border: 1px solid #d7e4e2; border-radius: 5px; padding: 18px; line-height: 1.5;")
        layout.addWidget(self.dashboard_alerts)
        button = QPushButton("Open Medicines & Stock")
        button.clicked.connect(lambda: self._navigate(1))
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self._refresh_dashboard()
        return page

    def _refresh_dashboard(self) -> None:
        with self.database.connect() as connection:
            today = date.today().isoformat()
            summary = connection.execute(
                """SELECT COUNT(DISTINCT m.id) AS medicines,
                          COALESCE(SUM(CASE WHEN b.expiry_date >= ? THEN b.quantity ELSE 0 END), 0) AS units,
                          COALESCE(SUM(b.quantity * b.purchase_rate_paisa), 0) AS value
                   FROM medicines m LEFT JOIN batches b ON b.medicine_id = m.id""", (today,)
            ).fetchone()
            expired = connection.execute("SELECT COUNT(*) FROM batches WHERE quantity > 0 AND expiry_date < ?", (today,)).fetchone()[0]
            expiry_counts = {
                days: connection.execute(
                    "SELECT COUNT(*) FROM batches WHERE quantity > 0 AND expiry_date BETWEEN ? AND ?",
                    (today, date.fromordinal(date.today().toordinal() + days).isoformat()),
                ).fetchone()[0]
                for days in (30, 60, 90)
            }
            low = connection.execute(
                """SELECT COUNT(*) FROM medicines m WHERE m.reorder_level > 0 AND
                   COALESCE((SELECT SUM(quantity) FROM batches b WHERE b.medicine_id=m.id AND b.expiry_date>=?),0) <= m.reorder_level""",
                (today,),
            ).fetchone()[0]
        if self.language == "ne":
            self.dashboard_summary.setText(
                f"औषधि: {summary['medicines']}     प्रयोगयोग्य संख्या: {summary['units']}     "
                f"खरिद दरमा स्टक मूल्य: रु. {summary['value'] / 100:,.2f}"
            )
            self.dashboard_alerts.setText(
                f"म्याद सकिएका ब्याच: {expired}\n३० दिनभित्र म्याद सकिने: {expiry_counts[30]}\n"
                f"६० दिनभित्र म्याद सकिने: {expiry_counts[60]}\n९० दिनभित्र म्याद सकिने: {expiry_counts[90]}\n"
                f"कम स्टक भएका औषधि: {low}"
            )
        else:
            self.dashboard_summary.setText(
                f"Medicines: {summary['medicines']}     Usable units: {summary['units']}     "
                f"Stock value at purchase rate: Rs. {summary['value'] / 100:,.2f}"
            )
            self.dashboard_alerts.setText(
                f"Expired batches: {expired}\nExpiring within 30 days: {expiry_counts[30]}\n"
                f"Expiring within 60 days: {expiry_counts[60]}\nExpiring within 90 days: {expiry_counts[90]}\n"
                f"Low-stock medicines: {low}"
            )

    def _medicines_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        toolbar = QHBoxLayout()
        self.stock_page = 0
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search medicine, generic, barcode or batch")
        self.search.textChanged.connect(self._reset_stock_page)
        self.stock_filter = QComboBox()
        self.stock_filter.addItem("All stock", "all")
        self.stock_filter.addItem("Expired", "expired")
        self.stock_filter.addItem("Expiring within 30 days", "expiring")
        self.stock_filter.addItem("Expiring within 60 days", "expiring_60")
        self.stock_filter.addItem("Expiring within 90 days", "expiring_90")
        self.stock_filter.addItem("Low stock", "low")
        self.stock_filter.addItem("Out of stock", "out")
        self.stock_filter.currentIndexChanged.connect(self._reset_stock_page)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.stock_filter)
        layout.addLayout(toolbar)
        actions = QHBoxLayout()
        for label, handler, secondary in (
            ("+ Medicine", self._add_medicine, False), ("Edit", self._edit_medicine, True),
            ("Substitutes", self._show_substitutes, True),
            ("Delete", self._delete_medicine, True), ("+ Batch", self._add_batch, False),
            ("Adjust stock", self._adjust_stock, True), ("Write off expired", self._write_off, True),
        ):
            button = QPushButton(label)
            if secondary:
                button.setProperty("secondary", True)
            button.clicked.connect(handler)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Medicine", "Generic / salt", "Category", "Usable qty", "Reorder", "Stock value", "Nearest expiry", "Status"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(240)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._refresh_batches)
        layout.addWidget(self.table, 2)
        stock_paging = QHBoxLayout()
        self.stock_page_label = QLabel("0 medicines")
        self.stock_previous = QPushButton("Previous")
        self.stock_previous.setProperty("secondary", True)
        self.stock_previous.clicked.connect(lambda: self._move_stock_page(-1))
        self.stock_next = QPushButton("Next")
        self.stock_next.setProperty("secondary", True)
        self.stock_next.clicked.connect(lambda: self._move_stock_page(1))
        stock_paging.addWidget(self.stock_page_label)
        stock_paging.addStretch(1)
        stock_paging.addWidget(self.stock_previous)
        stock_paging.addWidget(self.stock_next)
        layout.addLayout(stock_paging)
        self.batch_label = QLabel("Select a medicine to view its batches")
        self.batch_label.setStyleSheet("font-weight: 650; margin-top: 5px;")
        layout.addWidget(self.batch_label)
        batch_actions = QHBoxLayout()
        batch_actions.addStretch(1)
        for label, handler in (("Edit batch", self._edit_batch), ("Delete empty batch", self._delete_batch)):
            button = QPushButton(label)
            button.setProperty("secondary", True)
            button.clicked.connect(handler)
            batch_actions.addWidget(button)
        layout.addLayout(batch_actions)
        self.batch_table = QTableWidget(0, 5)
        self.batch_table.setHorizontalHeaderLabels(["Batch", "Expiry", "Quantity", "Purchase rate", "Selling rate"])
        self.batch_table.setMaximumHeight(190)
        self.batch_table.setMinimumHeight(120)
        self.batch_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.batch_table)
        self._refresh_stock_table()
        return page

    def _reset_stock_page(self, *_args) -> None:
        self.stock_page = 0
        self._refresh_stock_table()

    def _move_stock_page(self, delta: int) -> None:
        self.stock_page = max(0, self.stock_page + delta)
        self._refresh_stock_table()

    def _dealer_ledger_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        self.ledger_page = 0
        dealer_row = QHBoxLayout()
        self.ledger_dealer = QComboBox()
        self.ledger_dealer.setMinimumWidth(260)
        self.ledger_dealer.currentIndexChanged.connect(self._refresh_ledger_table)
        dealer_row.addWidget(QLabel("Dealer"))
        dealer_row.addWidget(self.ledger_dealer, 1)
        for label, handler, secondary in (("+ Dealer", self._add_dealer, False), ("Edit dealer", self._edit_dealer, True),
                                          ("+ Invoice debit", self._add_invoice_debit, False), ("+ Payment credit", self._add_payment_credit, True)):
            button = QPushButton(label)
            if secondary:
                button.setProperty("secondary", True)
            button.clicked.connect(handler)
            dealer_row.addWidget(button)
        layout.addLayout(dealer_row)

        filter_row = QHBoxLayout()
        self.ledger_start = QDateEdit()
        self.ledger_start.setCalendarPopup(True)
        self.ledger_start.setDate(date.today().replace(day=1))
        self.ledger_start.dateChanged.connect(self._reset_ledger_page)
        self.ledger_end = QDateEdit()
        self.ledger_end.setCalendarPopup(True)
        self.ledger_end.setDate(date.today())
        self.ledger_end.dateChanged.connect(self._reset_ledger_page)
        for label, field in (("From", self.ledger_start), ("To", self.ledger_end)):
            filter_row.addWidget(QLabel(label))
            filter_row.addWidget(field)
        refresh_button = QPushButton("Refresh")
        refresh_button.setProperty("secondary", True)
        refresh_button.clicked.connect(self._refresh_ledger_table)
        excel_button = QPushButton("Export Excel")
        excel_button.setProperty("secondary", True)
        excel_button.clicked.connect(lambda: self._export_ledger("excel"))
        pdf_button = QPushButton("Export PDF")
        pdf_button.clicked.connect(lambda: self._export_ledger("pdf"))
        filter_row.addStretch(1)
        filter_row.addWidget(refresh_button)
        filter_row.addWidget(excel_button)
        filter_row.addWidget(pdf_button)
        layout.addLayout(filter_row)

        self.ledger_totals = QLabel("Select a dealer to view the ledger")
        self.ledger_totals.setStyleSheet("font-weight: 650; background: white; border: 1px solid #d7e4e2; padding: 10px;")
        layout.addWidget(self.ledger_totals)
        self.ledger_table = QTableWidget(0, 7)
        self.ledger_table.setHorizontalHeaderLabels(["Date", "Invoice No.", "Debit", "Date", "Credit", "Remarks", "Balance"])
        self.ledger_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ledger_table.setMinimumHeight(250)
        self.ledger_table.setAlternatingRowColors(True)
        self.ledger_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ledger_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.ledger_table, 1)
        ledger_paging = QHBoxLayout()
        self.ledger_page_label = QLabel("0 entries")
        self.ledger_previous = QPushButton("Previous")
        self.ledger_previous.setProperty("secondary", True)
        self.ledger_previous.clicked.connect(lambda: self._move_ledger_page(-1))
        self.ledger_next = QPushButton("Next")
        self.ledger_next.setProperty("secondary", True)
        self.ledger_next.clicked.connect(lambda: self._move_ledger_page(1))
        ledger_paging.addWidget(self.ledger_page_label)
        ledger_paging.addStretch(1)
        ledger_paging.addWidget(self.ledger_previous)
        ledger_paging.addWidget(self.ledger_next)
        layout.addLayout(ledger_paging)
        self._refresh_ledger_dealers()
        return page

    def _refresh_ledger_dealers(self, *_args) -> None:
        if not hasattr(self, "ledger_dealer"):
            return
        selected_id = self.ledger_dealer.currentData()
        dealers = self.ledger_service.dealers()
        self.ledger_dealer.blockSignals(True)
        self.ledger_dealer.clear()
        for dealer in dealers:
            self.ledger_dealer.addItem(dealer["name"], dealer["id"])
        if selected_id is not None:
            index = self.ledger_dealer.findData(selected_id)
            if index >= 0:
                self.ledger_dealer.setCurrentIndex(index)
        self.ledger_dealer.blockSignals(False)
        self._refresh_ledger_table()

    def _reset_ledger_page(self, *_args) -> None:
        self.ledger_page = 0
        self._refresh_ledger_table()

    def _move_ledger_page(self, delta: int) -> None:
        self.ledger_page = max(0, self.ledger_page + delta)
        self._refresh_ledger_table()

    def _purchases_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        self.purchase_page = 0
        form = QFormLayout()
        self.purchase_dealer = QComboBox()
        self.purchase_invoice = QLineEdit()
        self.purchase_date = QDateEdit()
        self.purchase_date.setCalendarPopup(True)
        self.purchase_date.setDate(date.today())
        self.purchase_due_date = QDateEdit()
        self.purchase_due_date.setCalendarPopup(True)
        self.purchase_due_date.setDate(date.today())
        self.purchase_payment = QComboBox()
        self.purchase_payment.addItem("Cash", "cash")
        self.purchase_payment.addItem("Credit", "credit")
        self.purchase_remark = QLineEdit()
        form.addRow("Dealer", self.purchase_dealer)
        form.addRow("Invoice number", self.purchase_invoice)
        form.addRow("Invoice date", self.purchase_date)
        form.addRow("Due date", self.purchase_due_date)
        form.addRow("Payment type", self.purchase_payment)
        form.addRow("Remark", self.purchase_remark)
        layout.addLayout(form)

        item_actions = QHBoxLayout()
        add_item = QPushButton("+ Add item")
        add_item.clicked.connect(self._add_purchase_item)
        remove_item = QPushButton("Remove selected item")
        remove_item.setProperty("secondary", True)
        remove_item.clicked.connect(self._remove_purchase_item)
        item_actions.addWidget(add_item)
        item_actions.addWidget(remove_item)
        item_actions.addStretch(1)
        self.purchase_total = QLabel("Bill total: Rs. 0.00")
        self.purchase_total.setStyleSheet("font-size: 12pt; font-weight: 700;")
        item_actions.addWidget(self.purchase_total)
        layout.addLayout(item_actions)
        self.purchase_lines: list[dict] = []
        self.purchase_items_table = QTableWidget(0, 7)
        self.purchase_items_table.setHorizontalHeaderLabels(["Medicine", "Batch", "Expiry", "Qty", "Free", "Rate", "Line total"])
        self.purchase_items_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.purchase_items_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.purchase_items_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.purchase_items_table.setMaximumHeight(230)
        self.purchase_items_table.setMinimumHeight(150)
        layout.addWidget(self.purchase_items_table)
        save_purchase = QPushButton("Save purchase and update stock")
        save_purchase.clicked.connect(self._save_purchase)
        layout.addWidget(save_purchase, alignment=Qt.AlignmentFlag.AlignRight)

        history_header = QHBoxLayout()
        history_header.addWidget(QLabel("Purchase history"))
        self.purchase_search = QLineEdit()
        self.purchase_search.setPlaceholderText("Search invoice or dealer")
        self.purchase_search.textChanged.connect(self._reset_purchase_page)
        history_header.addStretch(1)
        history_header.addWidget(self.purchase_search)
        layout.addLayout(history_header)
        self.purchase_history_table = QTableWidget(0, 6)
        self.purchase_history_table.setHorizontalHeaderLabels(["Date", "Invoice", "Dealer", "Payment", "Total", "Due date"])
        self.purchase_history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.purchase_history_table.setMinimumHeight(180)
        self.purchase_history_table.setAlternatingRowColors(True)
        self.purchase_history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.purchase_history_table, 1)
        purchase_paging = QHBoxLayout()
        self.purchase_page_label = QLabel("0 purchases")
        self.purchase_previous = QPushButton("Previous")
        self.purchase_previous.setProperty("secondary", True)
        self.purchase_previous.clicked.connect(lambda: self._move_purchase_page(-1))
        self.purchase_next = QPushButton("Next")
        self.purchase_next.setProperty("secondary", True)
        self.purchase_next.clicked.connect(lambda: self._move_purchase_page(1))
        purchase_paging.addWidget(self.purchase_page_label)
        purchase_paging.addStretch(1)
        purchase_paging.addWidget(self.purchase_previous)
        purchase_paging.addWidget(self.purchase_next)
        layout.addLayout(purchase_paging)
        self._refresh_purchase_dealers()
        self._refresh_purchases()
        page.setMinimumHeight(760)
        return page

    def _refresh_purchase_dealers(self) -> None:
        selected = self.purchase_dealer.currentData()
        self.purchase_dealer.blockSignals(True)
        self.purchase_dealer.clear()
        for dealer in self.ledger_service.dealers():
            self.purchase_dealer.addItem(dealer["name"], dealer["id"])
        if selected is not None:
            index = self.purchase_dealer.findData(selected)
            if index >= 0:
                self.purchase_dealer.setCurrentIndex(index)
        self.purchase_dealer.blockSignals(False)

    def _add_purchase_item(self) -> None:
        dialog = PurchaseItemDialog(self.database, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        item = dialog.values()
        if item is None:
            self._information("No medicines", "Add a medicine in Medicines & Stock before creating a purchase.")
            return
        if not item["batch_number"].strip() or item["quantity"] <= 0:
            self._warning("Invalid item", "Enter a batch number and a billed quantity greater than zero.")
            return
        line_total = item["quantity"] * item["purchase_rate_paisa"] - item["discount_paisa"] + item["tax_paisa"]
        if line_total < 0:
            self._warning("Invalid discount", "The item discount cannot exceed its billed amount.")
            return
        self.purchase_lines.append(item)
        self._refresh_purchase_lines()

    def _remove_purchase_item(self) -> None:
        row = self.purchase_items_table.currentRow()
        if row >= 0:
            self.purchase_lines.pop(row)
            self._refresh_purchase_lines()

    def _refresh_purchase_lines(self) -> None:
        self.purchase_items_table.setRowCount(len(self.purchase_lines))
        total = 0
        for row_index, item in enumerate(self.purchase_lines):
            line_total = item["quantity"] * item["purchase_rate_paisa"] - item["discount_paisa"] + item["tax_paisa"]
            total += line_total
            values = [item["medicine_name"], item["batch_number"], item["expiry_date"].isoformat(),
                      str(item["quantity"]), str(item["free_quantity"]),
                      f"Rs. {item['purchase_rate_paisa'] / 100:,.2f}", f"Rs. {line_total / 100:,.2f}"]
            for column, value in enumerate(values):
                self.purchase_items_table.setItem(row_index, column, QTableWidgetItem(str(value)))
        if self.language == "ne":
            self.purchase_total.setText(f"बिल जम्मा: रु. {total / 100:,.2f}")
        else:
            self.purchase_total.setText(f"Bill total: Rs. {total / 100:,.2f}")

    def _save_purchase(self) -> None:
        dealer_id = self.purchase_dealer.currentData()
        if dealer_id is None:
            self._information("Select dealer", "Add or select a dealer before saving a purchase.")
            return
        if not self.purchase_lines:
            self._information("Add items", "Add at least one purchase item.")
            return
        try:
            self.purchase_service.create_purchase(
                int(dealer_id), self.purchase_invoice.text(), self.purchase_date.date().toPython(),
                self.purchase_payment.currentData(), self.purchase_lines,
                due_date=self.purchase_due_date.date().toPython(), remark=self.purchase_remark.text(),
            )
        except (PurchaseError, sqlite3.IntegrityError) as error:
            self._show_error(error)
            return
        self._information("Purchase saved", "Purchase, stock batches, and dealer ledger were updated.")
        self.purchase_invoice.clear()
        self.purchase_remark.clear()
        self.purchase_lines.clear()
        self._refresh_purchase_lines()
        self._refresh_purchases()
        self._refresh_purchase_dealers()
        self._refresh_ledger_dealers()
        self._refresh_stock_table()
        self._refresh_dashboard()

    def _refresh_purchases(self, *_args) -> None:
        if not hasattr(self, "purchase_history_table"):
            return
        rows = self.purchase_service.purchases(
            self.purchase_search.text(), limit=250, offset=self.purchase_page * 250
        )
        if not rows and self.purchase_page > 0:
            self.purchase_page = 0
            self._refresh_purchases()
            return
        self.purchase_history_table.setRowCount(len(rows))
        for row_index, purchase in enumerate(rows):
            values = [purchase["invoice_date"], purchase["invoice_number"], purchase["dealer_name"],
                      purchase["payment_type"].title(), f"Rs. {purchase['total_paisa'] / 100:,.2f}", purchase["due_date"] or ""]
            for column, value in enumerate(values):
                self.purchase_history_table.setItem(row_index, column, QTableWidgetItem(str(value)))
        total_count = int(rows[0]["total_count"]) if rows else 0
        first_shown = self.purchase_page * 250 + (1 if rows else 0)
        last_shown = self.purchase_page * 250 + len(rows)
        if self.language == "ne":
            self.purchase_page_label.setText(f"{total_count} मध्ये {first_shown}-{last_shown} खरिद" if rows else "० खरिद")
        else:
            self.purchase_page_label.setText(f"Showing {first_shown}-{last_shown} of {total_count} purchases" if rows else "0 purchases")
        self.purchase_previous.setEnabled(self.purchase_page > 0)
        self.purchase_next.setEnabled(last_shown < total_count)

    def _reset_purchase_page(self, *_args) -> None:
        self.purchase_page = 0
        self._refresh_purchases()

    def _move_purchase_page(self, delta: int) -> None:
        self.purchase_page = max(0, self.purchase_page + delta)
        self._refresh_purchases()

    def _refresh_ledger_table(self, *_args) -> None:
        if not hasattr(self, "ledger_table"):
            return
        dealer_id = self.ledger_dealer.currentData()
        if dealer_id is None:
            self.ledger_table.setRowCount(0)
            self.ledger_totals.setText("Add or select a dealer to view the ledger")
            return
        try:
            report = self.ledger_service.ledger(
                int(dealer_id), self.ledger_start.date().toPython(), self.ledger_end.date().toPython(),
                limit=250, offset=self.ledger_page * 250,
            )
        except LedgerError as error:
            self._show_error(error)
            return
        if not entries and self.ledger_page > 0:
            self.ledger_page = 0
            self._refresh_ledger_table()
            return
        entries = report["entries"]
        self.ledger_table.setRowCount(len(entries))
        for row_index, entry in enumerate(entries):
            values = [
                entry["display_date"], entry["invoice_no"] or "",
                f"Rs. {entry['debit_paisa'] / 100:,.2f}" if entry["debit_paisa"] else "",
                entry["display_payment_date"],
                f"Rs. {entry['credit_paisa'] / 100:,.2f}" if entry["credit_paisa"] else "",
                entry["remark"], f"Rs. {entry['balance_paisa'] / 100:,.2f}",
            ]
            for column, value in enumerate(values):
                self.ledger_table.setItem(row_index, column, QTableWidgetItem(str(value)))
        if self.language == "ne":
            self.ledger_totals.setText(
                f"सुरु बाँकी: रु. {report['opening_balance_paisa'] / 100:,.2f}     "
                f"डेबिट जम्मा: रु. {report['total_debit_paisa'] / 100:,.2f}     "
                f"क्रेडिट जम्मा: रु. {report['total_credit_paisa'] / 100:,.2f}     "
                f"अन्तिम बाँकी: रु. {report['closing_balance_paisa'] / 100:,.2f}"
            )
        else:
            self.ledger_totals.setText(
                f"Opening: Rs. {report['opening_balance_paisa'] / 100:,.2f}     "
                f"Debit total: Rs. {report['total_debit_paisa'] / 100:,.2f}     "
                f"Credit total: Rs. {report['total_credit_paisa'] / 100:,.2f}     "
                f"Closing balance: Rs. {report['closing_balance_paisa'] / 100:,.2f}"
            )
        first_shown = self.ledger_page * 250 + (1 if entries else 0)
        last_shown = self.ledger_page * 250 + len(entries)
        if self.language == "ne":
            self.ledger_page_label.setText(f"{report['total_count']} मध्ये {first_shown}-{last_shown} विवरण" if entries else "० विवरण")
        else:
            self.ledger_page_label.setText(f"Showing {first_shown}-{last_shown} of {report['total_count']} entries" if entries else "0 entries")
        self.ledger_previous.setEnabled(self.ledger_page > 0)
        self.ledger_next.setEnabled(last_shown < report["total_count"])

    def _add_dealer(self) -> None:
        dialog = DealerDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            dealer_id = self.ledger_service.create_dealer(**dialog.values())
        except (LedgerError, sqlite3.IntegrityError) as error:
            self._show_error(error)
            return
        self._refresh_ledger_dealers()
        index = self.ledger_dealer.findData(dealer_id)
        if index >= 0:
            self.ledger_dealer.setCurrentIndex(index)

    def _edit_dealer(self) -> None:
        dealer_id = self.ledger_dealer.currentData()
        if dealer_id is None:
            self._information("Select dealer", "Select a dealer to edit.")
            return
        dealer = next((row for row in self.ledger_service.dealers() if row["id"] == dealer_id), None)
        if not dealer:
            return
        dialog = DealerDialog(self, dealer)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.ledger_service.update_dealer(int(dealer_id), **dialog.values())
        except (LedgerError, sqlite3.IntegrityError) as error:
            self._show_error(error)
            return
        self._refresh_ledger_dealers()

    def _add_invoice_debit(self) -> None:
        dealer_id = self.ledger_dealer.currentData()
        if dealer_id is None:
            self._information("Select dealer", "Add or select a dealer first.")
            return
        dialog = LedgerEntryDialog("debit", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.ledger_service.add_invoice(
                int(dealer_id), dialog.entry_date.date().toPython(), dialog.invoice_no.text(),
                round(dialog.amount.value() * 100), due_date=dialog.due_date.date().toPython(),
                remark=dialog.remark.text(),
            )
        except (LedgerError, sqlite3.IntegrityError) as error:
            self._show_error(error)
            return
        self._refresh_ledger_dealers()

    def _add_payment_credit(self) -> None:
        dealer_id = self.ledger_dealer.currentData()
        if dealer_id is None:
            self._information("Select dealer", "Add or select a dealer first.")
            return
        dialog = LedgerEntryDialog("credit", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.ledger_service.add_payment(
                int(dealer_id), dialog.entry_date.date().toPython(), round(dialog.amount.value() * 100),
                linked_invoice_no=dialog.linked_invoice.text(), payment_method=dialog.payment_method.currentText(),
                remark=dialog.remark.text(),
            )
        except (LedgerError, sqlite3.IntegrityError) as error:
            self._show_error(error)
            return
        self._refresh_ledger_dealers()

    def _export_ledger(self, file_type: str) -> None:
        dealer_id = self.ledger_dealer.currentData()
        if dealer_id is None:
            self._information("Select dealer", "Select a dealer before exporting.")
            return
        report = self.ledger_service.ledger(
            int(dealer_id), self.ledger_start.date().toPython(), self.ledger_end.date().toPython(), limit=None
        )
        dealer_name = report["dealer"]["name"].replace("/", "-").replace("\\", "-")
        if file_type == "excel":
            path, _ = QFileDialog.getSaveFileName(self, "Export dealer ledger to Excel", f"{dealer_name}-ledger.xlsx", "Excel workbook (*.xlsx)")
            if not path:
                return
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            exporter = export_dealer_ledger_excel
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Export dealer ledger to PDF", f"{dealer_name}-ledger.pdf", "PDF file (*.pdf)")
            if not path:
                return
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            exporter = export_dealer_ledger_pdf
        try:
            exporter(report, path)
        except Exception as error:
            self._show_error(error)
            return
        self._information("Export complete", f"Dealer ledger saved to:\n{path}")

    def _refresh_stock_table(self, *_args) -> None:
        if not hasattr(self, "table"):
            return
        try:
            rows = self.stock.search_medicines(
                self.search.text(), self.stock_filter.currentData(), limit=250, offset=self.stock_page * 250
            )
        except Exception as error:
            self._show_error(error)
            return
        if not rows and self.stock_page > 0:
            self.stock_page = 0
            self._refresh_stock_table()
            return
        self.table.setRowCount(len(rows))
        today = date.today()
        for row_index, row in enumerate(rows):
            values = [row["name"], row["generic_name"], translate_text(row["category"], self.language), str(row["usable_quantity"]),
                      str(row["reorder_level"]), f"Rs. {row['stock_value_paisa'] / 100:,.2f}", row["nearest_expiry"] or "-", ""]
            status = "OK"
            expiry = row["nearest_expiry"]
            if row["usable_quantity"] == 0:
                status = "Out of stock"
            elif row["reorder_level"] and row["usable_quantity"] <= row["reorder_level"]:
                status = "Low stock"
            if expiry:
                days_left = (date.fromisoformat(expiry) - today).days
                if days_left < 0:
                    status = "Expired batch present"
                elif days_left <= 30:
                    status = "Expiring soon"
            values[-1] = translate_text(status, self.language)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row["id"])
                if status == "Expired batch present":
                    item.setBackground(QColor("#b83c35"))
                    item.setForeground(Qt.GlobalColor.white)
                elif status == "Expiring soon":
                    item.setBackground(QColor("#f4a261"))
                elif status == "Low stock" or status == "Out of stock":
                    item.setBackground(Qt.GlobalColor.lightGray)
                self.table.setItem(row_index, column, item)
            total_count = int(rows[0]["total_count"]) if rows else 0
            first_shown = self.stock_page * 250 + (1 if rows else 0)
            last_shown = self.stock_page * 250 + len(rows)
            if self.language == "ne":
                self.stock_page_label.setText(f"{total_count} मध्ये {first_shown}-{last_shown} औषधि" if rows else "० औषधि")
            else:
                self.stock_page_label.setText(f"Showing {first_shown}-{last_shown} of {total_count} medicines" if rows else "0 medicines")
            self.stock_previous.setEnabled(self.stock_page > 0)
            self.stock_next.setEnabled(last_shown < total_count)
        self._refresh_batches()

    def _selected_medicine(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        medicine_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        with self.database.connect() as connection:
            result = connection.execute("SELECT * FROM medicines WHERE id = ?", (medicine_id,)).fetchone()
            return dict(result) if result else None

    def _selected_batch_id(self) -> int | None:
        row = self.batch_table.currentRow()
        return self.batch_table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None

    def _refresh_batches(self) -> None:
        if not hasattr(self, "batch_table"):
            return
        medicine = self._selected_medicine()
        batches = self.stock.batches_for_medicine(medicine["id"]) if medicine else []
        self.batch_label.setText(f"Batches for {medicine['name']}" if medicine else "Select a medicine to view its batches")
        self.batch_table.setRowCount(len(batches))
        for row_index, batch in enumerate(batches):
            values = [batch["batch_number"], batch["expiry_date"], str(batch["quantity"]),
                      f"Rs. {batch['purchase_rate_paisa'] / 100:,.2f}", f"Rs. {batch['selling_rate_paisa'] / 100:,.2f}"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, batch["id"])
                expiry = date.fromisoformat(batch["expiry_date"])
                days_left = (expiry - date.today()).days
                if days_left < 0:
                    item.setBackground(QColor("#b83c35"))
                    item.setForeground(Qt.GlobalColor.white)
                elif days_left <= 30:
                    item.setBackground(QColor("#f4a261"))
                elif days_left <= 60:
                    item.setBackground(QColor("#f6d365"))
                elif days_left <= 90:
                    item.setBackground(QColor("#fff0a6"))
                self.batch_table.setItem(row_index, column, item)

    def _add_medicine(self) -> None:
        dialog = MedicineDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.stock.create_medicine(**dialog.values())
        except (StockError, sqlite3.IntegrityError) as error:
            self._show_error(error)
            return
        self._refresh_stock_table()
        self._refresh_dashboard()

    def _edit_medicine(self) -> None:
        medicine = self._selected_medicine()
        if not medicine:
            self._information("Select medicine", "Select a medicine to edit.")
            return
        dialog = MedicineDialog(self, medicine)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.stock.update_medicine(medicine["id"], **dialog.values())
        except (StockError, sqlite3.IntegrityError) as error:
            self._show_error(error)
            return
        self._refresh_stock_table()

    def _show_substitutes(self) -> None:
        medicine = self._selected_medicine()
        if not medicine:
            self._information("Select medicine", "Select a medicine to find substitutes.")
            return
        if not medicine["generic_name"].strip():
            self._information("No generic name", "Add a generic / salt name to this medicine first.")
            return
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT name, manufacturer, category FROM medicines WHERE generic_name = ? COLLATE NOCASE AND id != ? ORDER BY name COLLATE NOCASE",
                (medicine["generic_name"].strip(), medicine["id"]),
            ).fetchall()
        text = "\n".join(f"{row['name']}  ·  {row['manufacturer'] or 'Manufacturer not set'}" for row in rows)
        self._information("Same generic / salt", text or "No other medicines use this generic / salt name.")

    def _delete_medicine(self) -> None:
        medicine = self._selected_medicine()
        if not medicine:
            self._information("Select medicine", "Select a medicine to delete.")
            return
        if self._confirm("Confirm deletion", f"Delete {medicine['name']}? This cannot be undone.") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.stock.delete_medicine(medicine["id"])
        except StockError as error:
            self._show_error(error)
        self._refresh_stock_table()

    def _add_batch(self) -> None:
        medicine = self._selected_medicine()
        if not medicine:
            self._information("Select medicine", "Select a medicine before adding a batch.")
            return
        dialog = BatchDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.stock.add_batch(
                medicine["id"], dialog.batch.text(), dialog.expiry.date().toPython(), dialog.quantity.value(),
                round(dialog.purchase_rate.value() * 100), round(dialog.selling_rate.value() * 100),
                manufacturing_date=dialog.manufactured.date().toPython(),
            )
        except (StockError, sqlite3.IntegrityError) as error:
            self._show_error(error)
            return
        self._refresh_stock_table()
        self._refresh_dashboard()

    def _edit_batch(self) -> None:
        batch_id = self._selected_batch_id()
        if not batch_id:
            self._information("Select batch", "Select a batch to edit.")
            return
        medicine = self._selected_medicine()
        batch = next((item for item in self.stock.batches_for_medicine(medicine["id"]) if item["id"] == batch_id), None)
        if not batch:
            return
        dialog = BatchDialog(self)
        dialog.setWindowTitle("Edit batch details")
        dialog.batch.setText(batch["batch_number"])
        dialog.manufactured.setDate(date.fromisoformat(batch["manufacturing_date"]) if batch["manufacturing_date"] else date.today())
        dialog.expiry.setDate(date.fromisoformat(batch["expiry_date"]))
        dialog.quantity.setValue(batch["quantity"])
        dialog.quantity.setEnabled(False)
        dialog.purchase_rate.setValue(batch["purchase_rate_paisa"] / 100)
        dialog.selling_rate.setValue(batch["selling_rate_paisa"] / 100)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.stock.update_batch(
                batch_id,
                batch_number=dialog.batch.text(),
                manufacturing_date=dialog.manufactured.date().toPython(),
                expiry_date=dialog.expiry.date().toPython(),
                purchase_rate_paisa=round(dialog.purchase_rate.value() * 100),
                selling_rate_paisa=round(dialog.selling_rate.value() * 100),
            )
        except (StockError, sqlite3.IntegrityError) as error:
            self._show_error(error)
            return
        self._refresh_stock_table()

    def _delete_batch(self) -> None:
        batch_id = self._selected_batch_id()
        if not batch_id:
            self._information("Select batch", "Select an empty batch to delete.")
            return
        if self._confirm("Confirm deletion", "Delete this batch? Only empty batches without adjustment history can be deleted.") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.stock.delete_empty_batch(batch_id)
        except StockError as error:
            self._show_error(error)
            return
        self._refresh_stock_table()

    def _adjust_stock(self) -> None:
        batch_id = self._selected_batch_id()
        if not batch_id:
            self._information("Select batch", "Select a batch to adjust its stock.")
            return
        quantity, accepted = self._signed_quantity("Stock adjustment", "Enter quantity change (negative to remove stock):")
        if not accepted:
            return
        reason, accepted = self._text_input("Adjustment reason", "Reason (damage, loss, correction):")
        if not accepted:
            return
        try:
            self.stock.adjust_stock(batch_id, quantity, reason)
        except StockError as error:
            self._show_error(error)
            return
        self._refresh_stock_table()
        self._refresh_dashboard()

    def _write_off(self) -> None:
        answer = self._confirm("Write off expired stock", "Set all expired batch quantities to zero and record adjustments?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            count = self.stock.write_off_expired()
        except Exception as error:
            self._show_error(error)
            return
        self._information("Write-off complete", f"Written off {count} units from expired batches.")
        self._refresh_stock_table()
        self._refresh_dashboard()

    @staticmethod
    def _signed_quantity(title: str, prompt: str) -> tuple[int, bool]:
        from PySide6.QtWidgets import QInputDialog
        return QInputDialog.getInt(None, title, prompt, 1, -10_000_000, 10_000_000)

    @staticmethod
    def _text_input(title: str, prompt: str) -> tuple[str, bool]:
        from PySide6.QtWidgets import QInputDialog
        return QInputDialog.getText(None, title, prompt)

    def _show_error(self, error: Exception | str) -> None:
        QMessageBox.warning(self, self._localized_text("Unable to complete action"), self._localized_text(str(error)))
