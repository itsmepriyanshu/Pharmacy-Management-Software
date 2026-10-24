# Project guidance

- This is an offline Windows desktop application built with Python 3.11+, PySide6, and local SQLite. Do not introduce a browser, web server, cloud service, or runtime network dependency.
- Keep money as integer paisa in persistence and calculations.
- Keep database changes migration-safe and preserve financial/stock history; never delete historical records silently.
- Put database behavior in `models/` and domain operations in `services/`; keep Qt presentation in `ui/`.
- Add focused tests for stock, expiry, and ledger invariants. Tests must use temporary databases.
- Follow the phased delivery: stop after each tested milestone for the owner's trial before continuing.
