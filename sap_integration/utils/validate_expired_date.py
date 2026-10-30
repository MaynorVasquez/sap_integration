# tu_app/overrides/sales_invoice_override.py
import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from frappe.utils import getdate

class CustomSalesInvoice(SalesInvoice):
    def validate_due_date(self):
        """Allow a past due date only for invoices imported from SAP.

        All invoices created by users or other integrations keep ERPNext's
        standard validation, including payment-term validation.
        """
        due_date = getdate(self.due_date) if self.due_date else None
        posting_date = getdate(self.posting_date) if self.posting_date else None

        if (
            self.flags.get("sap_sales_invoice")
            and due_date
            and posting_date
            and due_date < posting_date
        ):
            frappe.logger("sap_integration").warning(
                "SAP invoice %s has due date %s before posting date %s",
                self.name or "NEW",
                due_date,
                posting_date,
            )
            return

        return super().validate_due_date()
