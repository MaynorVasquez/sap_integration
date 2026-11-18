import frappe
from frappe import _
from frappe.utils import flt, getdate, get_link_to_form
from erpnext.stock.doctype.delivery_note.delivery_note import DeliveryNote
from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos

class CustomDeliveryNote(DeliveryNote):
    def validate_serialized_batch(self):
        # Si el flag está activo, omitimos SOLO la comprobación de caducidad,
        # pero mantenemos el resto de validaciones de series/lotes.
        if self.get("custom_allow_expired_batch"):
            is_material_issue = False
            if self.doctype == "Stock Entry" and self.purpose in ["Material Issue", "Material Transfer"]:
                is_material_issue = True

            for d in self.get("items"):
                # Validación de que los números de serie pertenecen al lote (se mantiene)
                if hasattr(d, "serial_no") and hasattr(d, "batch_no") and d.serial_no and d.batch_no:
                    serial_nos = frappe.get_all(
                        "Serial No",
                        fields=["batch_no", "name", "warehouse"],
                        filters={"name": ("in", get_serial_nos(d.serial_no))},
                    )
                    for row in serial_nos:
                        if row.warehouse and row.batch_no != d.batch_no:
                            frappe.throw(
                                _("Row #{0}: Serial No {1} does not belong to Batch {2}").format(
                                    d.idx, row.name, d.batch_no
                                )
                            )
                if is_material_issue:
                    continue

                # ⚠️ Aquí se omite deliberadamente el bloque de caducidad
                # (las líneas que lanzaban BatchExpiredError)
        else:
            # Si el flag no está activo, se ejecuta la validación original
            super().validate_serialized_batch()