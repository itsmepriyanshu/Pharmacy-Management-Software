# Dipesh Medical Hall

Offline-first Windows desktop pharmacy application. The current checkpoint includes stock, Purchases, Dealer Ledger, Billing, and Customer Credit workflows.

## Requirements

- Windows 10 or 11
- Python 3.11 or newer
- A local Python environment with the packages in `requirements.txt`

No browser or network connection is used at runtime. The SQLite database is created under `%LOCALAPPDATA%\Dipesh Medical Hall\pharmacy.sqlite3`; application logs are written to `%LOCALAPPDATA%\Dipesh Medical Hall\logs\application.log`.

## Setup and run

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

On first start, the application creates and versions the database automatically. Medicine prices are stored as integer paisa, not floating-point values.

Use the **Language / भाषा** selector in the left sidebar to switch between English and नेपाली. The selected language is saved locally and restored on the next launch.

## Phase 1 features

- Medicine master data and batch entry, with duplicate barcode and batch checks
- Search by medicine name, generic/salt, barcode, or batch number
- Expired, expiring-within-30-days, low-stock, and out-of-stock filters
- Expiry highlighting, usable stock counts, and purchase-rate stock valuation
- Audited manual stock adjustments and confirmed expired-stock write-off
- Transactional FEFO stock allocation that refuses expired stock and insufficient quantities
- Local sample-data seed script for testing only
- English and Nepali labels, prompts, validation messages, dashboard counts, and active page summaries

## Phase 2 features

- Dealer master records with contact, PAN/VAT, address, and credit terms
- Dealer ledger with the paper-book columns: Date, Invoice No., Debit, Date, Credit, Remarks, and running Balance
- Date-range opening/closing balances and debit/credit totals
- Excel and landscape A4 PDF exports using the paper-book layout
- Purchase entry with dealer invoice, items, batches, expiry, billed/free quantity, discount, tax, and cash/credit type
- Purchase save updates stock batches and dealer ledger atomically; cash purchases are recorded as same-day payments

## Phase 3 features

- Billing with barcode/name search, line and bill discounts, cash/online/credit payment, FEFO stock deduction, and insufficient-stock protection
- F2 bill save and F5 print preview, held/resumed bills, sales history, and returns to original batches
- Customer credit ledger, credit-limit warnings, payment collection, ageing buckets, and prefilled system SMS reminders
- Customer-credit sales and returns update the customer ledger in the same SQLite transaction as stock/sale records

## Test

```powershell
python -m pytest
```

The tests use temporary SQLite databases and do not touch the live pharmacy database.

## Build and install

With Python dependencies installed, run:

```powershell
.\build.ps1
```

The one-folder output is placed in `dist\DipeshMedicalHall`. To create a Windows installer, install Inno Setup 6 and compile `installer.iss` after the build. The sample seed script is not included in the packaged application.

## Project layout

- `models/`: database schema and initialization
- `services/`: stock, dealer ledger, and purchase operations
- `ui/`: PySide6 desktop interface
- `reports/`: report module foundation
- `tests/`: isolated automated tests
- `main.py`: desktop application entry point
- `seed.py`: optional local test data generator; do not use for production records

## Current checkpoint

Expenses, full reports, backup/restore, PIN settings, recurring expenses, and dealer purchase returns remain deferred to later phases. Purchases and Dealer Ledger are operational, but purchase bills do not yet attach scanned invoices.
