import frappe
from frappe import _
import json

def log_sincronizacion(doctype, docname, company,status="Éxito", total=0, detalles=None, errores=None):
    try:
        if not docname:
            docname = f"LOG-{frappe.utils.now()}"

        if not doctype:
            frappe.log_error("No se especificó doctype para log_sincronizacion")
            return

        if frappe.db.exists(doctype, docname):
            doc = frappe.get_doc(doctype, docname)
        else:
            doc = frappe.new_doc(doctype)
            doc.sincronizacion = docname

        doc.status = status
        doc.total_records = total
        doc.company = company

        # Asegura que 'detalles' siempre sea un JSON válido
        if isinstance(detalles, str):
            detalles = {"mensaje": detalles}
        elif detalles is None:
            detalles = []

        try:
            doc.details = json.dumps(detalles, indent=2, ensure_ascii=False)
            # Validación adicional para evitar errores en MySQL con json_valid()
            json.loads(doc.details)
        except Exception as json_error:
            frappe.log_error(f"Detalles no es JSON válido: {json_error}")
            doc.details = json.dumps({"error": "Formato inválido en detalles"})

        doc.error_log = errores if errores else ""

        doc.save(ignore_permissions=True)
        frappe.db.commit()

    except Exception as e:
        frappe.log_error(f"Error en log_sincronizacion para {doctype} {docname}: {str(e)}")



def filter_sap_response_items(items, exclude_keys=None):
    """Retorna una lista de ítems eliminando las claves especificadas."""
    exclude_keys = exclude_keys or []
    return [
        {k: v for k, v in item.items() if k not in exclude_keys}
        for item in items
    ]

