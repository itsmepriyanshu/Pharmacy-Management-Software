from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from models.database import Database
from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Dipesh Medical Hall")
    app.setOrganizationName("Dipesh Medical Hall")
    log_dir = Path.home() / "AppData" / "Local" / "Dipesh Medical Hall" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_dir / "application.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        database = Database()
        database.initialize()
        window = MainWindow(database)
    except Exception as error:
        logging.exception("Application startup failed")
        QMessageBox.critical(None, "Startup error", f"The application could not start.\n\n{error}")
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
