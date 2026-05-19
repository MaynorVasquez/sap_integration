import frappe
from frappe import _
from datetime import datetime


def sync_tracker(doctype_padre: str, doctype_hijo: str, codigo, company) -> dict:
    try:
        # Validar existencia de doctypes
        if not frappe.db.exists("DocType", doctype_padre):
            return {"success": False, "error": f"Doctype padre '{doctype_padre}' no existe"}

        if not frappe.db.exists("DocType", doctype_hijo):
            return {"success": False, "error": f"Doctype hijo '{doctype_hijo}' no existe"}

        # Consulta directa (una sola fila)
        registro = frappe.db.sql(f"""
            SELECT 
                company,
                code,
                description,
                last_sync
            FROM `tab{doctype_hijo}`
            WHERE 
                parenttype = %s
                AND company = %s
                AND code = %s
            LIMIT 1
        """, (doctype_padre, company, codigo), as_dict=True)

        if not registro:
            return {"success": False, "data": None, "message": "No se encontró registro"}

        r = registro[0]

        # Formatear fecha si existe
        if r.get("last_sync"):
            r["last_sync"] = r["last_sync"].strftime("%Y-%m-%d %H:%M:%S")

        return {"success": True, "data": r}

    except Exception as e:
        frappe.log_error("Error en obtener_filtro_ultima_sync", str(e))
        return {"success": False, "error": str(e)}
    
def sync_tracker_update(doctype_padre, code: str, company ,fecha_sync: datetime):

    try:
        # Obtener el único registro del Doctype individual 'Sync Tracker'
        tracker = frappe.get_single(doctype_padre)

        # Verificar si ya existe un registro con ese code y tipo_entidad
        encontrado = None
        for fila in tracker.sap_sync_tracker:
            if fila.company == company and fila.code == code:
                encontrado = fila
                break

        if encontrado:
            # Actualizar fecha
            encontrado.last_sync = fecha_sync
        else:
            # Insertar nuevo registro
            tracker.append("sap_sync_tracker", {
                "company": company,
                "code": code,
                "last_sync": fecha_sync
            })

        tracker.save(ignore_permissions=True)
        frappe.db.commit()

    except Exception as e:
        frappe.log_error(f"Error al actualizar Sync Tracker para {code}", str(e))
