import frappe
from frappe import _
import json


def log_sincronizacion(
    doctype,
    docname,
    company,
    status="Éxito",
    total=0,
    detalles=None,
    errores=None
):
    try:
        MAX_LOG_SIZE = 100000  # caracteres máximos

        if not docname:
            docname = f"LOG-{frappe.utils.now()}"

        if not doctype:
            print("No se especificó doctype para log_sincronizacion")
            return

        if frappe.db.exists(doctype, docname):
            doc = frappe.get_doc(doctype, docname)
        else:
            doc = frappe.new_doc(doctype)
            doc.sincronizacion = docname

        doc.status = status
        doc.total_records = total
        doc.company = company

        # Normalizar detalles
        if isinstance(detalles, str):
            detalles = {"mensaje": detalles}

        elif detalles is None:
            detalles = []

        try:
            payload = json.dumps(
                detalles,
                indent=2,
                ensure_ascii=False,
                default=str
            )

            original_size = len(payload)

            if original_size > MAX_LOG_SIZE:
                payload = (
                    payload[:MAX_LOG_SIZE]
                    + f"\n\n... TRUNCADO ..."
                    + f"\nTamaño original: {original_size} caracteres"
                )

            doc.details = payload

        except Exception as json_error:

            doc.details = (
                f"Error serializando detalles: {str(json_error)}"
            )

        doc.error_log = (
            str(errores)[:5000]
            if errores else ""
        )

        doc.save(ignore_permissions=True)
        frappe.db.commit()

    except Exception as e:
        # Evitar frappe.log_error porque puede fallar si DB murió
        print(
            f"Error en log_sincronizacion "
            f"para {doctype} {docname}: {str(e)}"
        )



def filter_sap_response_items(items, exclude_keys=None):
    """Retorna una lista de ítems eliminando las claves especificadas."""
    exclude_keys = exclude_keys or []
    return [
        {k: v for k, v in item.items() if k not in exclude_keys}
        for item in items
    ]

