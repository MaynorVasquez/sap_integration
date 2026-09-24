# tu_app/overrides/sales_invoice_override.py
import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from frappe.utils import getdate

class CustomSalesInvoice(SalesInvoice):
    def validate_due_date(self):
        # Omitimos la validación de fecha de vencimiento anterior
        # al posting date para permitir integraciones con fechas pasadas.
        # Log opcional para auditoría:
        due_date = getdate(self.due_date) if self.due_date else None
        posting_date = getdate(self.posting_date) if self.posting_date else None

        if due_date and posting_date and due_date < posting_date:
            frappe.log_error(
                f"Factura {self.name or 'NUEVA'}: Due Date {due_date} "
                f"anterior a Posting Date {posting_date} — permitido por override",
                "DEBUG DUE DATE OVERRIDE"
            )
        
        # No llamamos a super() ni a la función de party.py
        pass