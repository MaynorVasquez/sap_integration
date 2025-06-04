import frappe
from frappe import _
from datetime import datetime


def obtener_filtro_ultima_sync(doctype_padre: str, doctype_hijo: str, tipo_entidad: str) -> dict:
    """
    Obtiene el filtro para SAP con base en la última fecha y hora de sincronización por entidad.
    Devuelve el dict: {"code": "YYYY-MM-DD HH:MM:SS", ...}
    
    Args:
        doctype_padre (str): Nombre del Doctype padre (ej: "Sync Tracker")
        doctype_hijo (str): Nombre del Doctype hijo (tabla) (ej: "Sync Record")
        tipo_entidad (str): Tipo de entidad a consultar (Clientes, Articulos, etc.)
    
    Returns:
        dict: {"success": bool, "data": {code: 'YYYY-MM-DD HH:MM:SS'}, "error": str}
    """
    try:
        if not frappe.db.exists("DocType", doctype_padre):
            return {"success": False, "error": f"Doctype padre '{doctype_padre}' no existe"}
        if not frappe.db.exists("DocType", doctype_hijo):
            return {"success": False, "error": f"Doctype hijo '{doctype_hijo}' no existe"}

        registros = frappe.db.sql(f"""
            SELECT code, last_sync
            FROM `tab{doctype_hijo}`
            WHERE parenttype = %s AND parent = %s AND tipo_entidad = %s
        """, (doctype_padre, doctype_padre, tipo_entidad), as_dict=True)

        resultado = {}
        for r in registros:
            if r.last_sync:
                # Convertir datetime a string con el formato que espera SAP
                fecha_formateada = r.last_sync.strftime("%Y-%m-%d %H:%M:%S")
                resultado[r.code] = fecha_formateada

        return {"success": True, "data": resultado, "count": len(resultado)}

    except Exception as e:
        frappe.log_error("Error en obtener_filtro_ultima_sync", str(e))
        return {"success": False, "error": str(e)}


def actualizar_last_sync(tipo_entidad: str, code: str, fecha_sync: datetime):
    """
    Inserta o actualiza la fecha de sincronización (last_sync) para una entidad específica.
    Los datos se guardan en el Doctype 'Sync Tracker' con registros en la tabla hija 'Sync Record'.
    """
    if not (tipo_entidad and code and fecha_sync):
        frappe.log_error("Datos insuficientes para Sync Tracker", f"{tipo_entidad} | {code} | {fecha_sync}")
        return

    try:
        # Obtener el único registro del Doctype individual 'Sync Tracker'
        tracker = frappe.get_single("Sync Tracker")

        # Verificar si ya existe un registro con ese code y tipo_entidad
        encontrado = None
        for fila in tracker.sincronizaciones:
            if fila.tipo_entidad == tipo_entidad and fila.code == code:
                encontrado = fila
                break

        if encontrado:
            # Actualizar fecha
            encontrado.last_sync = fecha_sync
        else:
            # Insertar nuevo registro
            tracker.append("sincronizaciones", {
                "tipo_entidad": tipo_entidad,
                "code": code,
                "last_sync": fecha_sync
            })

        tracker.save(ignore_permissions=True)
        frappe.db.commit()

    except Exception as e:
        frappe.log_error(f"Error al actualizar Sync Tracker para {code}", str(e))

