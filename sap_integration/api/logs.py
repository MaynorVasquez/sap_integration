import frappe
import json

def log_sincronizacion(doctype,docname,status="Éxito",total=0,detalles=None,errores=None):
    """
    Registra logs en cualquier Doctype de sincronización con los campos estándar:
    status, total_records, details, error_log
    """
    try:
        if not doctype or not docname:
            frappe.log_error("No se especificó doctype o docname para log_sincronizacion")
            return
        
        if frappe.db.exists(doctype, docname):
            # Actualiza registro existente
            doc = frappe.get_doc(doctype, docname)
        else:
            # Crea nuevo registro
            doc = frappe.new_doc(doctype)
            doc.sincronizacion = docname

        doc.status = status
        doc.total_records = total
        doc.details = json.dumps(detalles or [], indent=2, ensure_ascii=False)
        doc.error_log = "\n".join(errores) if errores else ""

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

