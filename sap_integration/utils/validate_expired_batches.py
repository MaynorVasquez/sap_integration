# tu_app/overrides/stock_entry_override.py
from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry

class CustomStockEntry(StockEntry):
    def validate_expired_batches(self):
        # Sobrescribir para permitir lotes vencidos
        # Simplemente no hacemos nada (pass) o registramos una advertencia
        pass