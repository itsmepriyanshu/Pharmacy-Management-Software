"""Create disposable sample stock data for local testing; never used by the installer."""
from datetime import date, timedelta

from models.database import Database
from services.stock_service import StockService


def main() -> None:
    database = Database()
    database.initialize()
    stock = StockService(database)
    today = date.today()
    examples = [
        ("Paracetamol 500 mg", "Paracetamol", "tablet", 1250, 1500, 20, 120, 200),
        ("Cetirizine 10 mg", "Cetirizine", "tablet", 800, 1000, 10, 60, 90),
        ("Cough Syrup 100 ml", "Dextromethorphan", "syrup", 6500, 7500, 8, 35, 80),
    ]
    for index, (name, generic, category, purchase, selling, reorder, quantity, days) in enumerate(examples, 1):
        medicine_id = stock.create_medicine(name, generic_name=generic, category=category,
                                            mrp_paisa=selling, selling_rate_paisa=selling, reorder_level=reorder)
        stock.add_batch(medicine_id, f"SEED-{index}", today + timedelta(days=days), quantity, purchase, selling)
    print("Added sample medicines. This seed data is for testing only.")


if __name__ == "__main__":
    main()
