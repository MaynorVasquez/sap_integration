import frappe
from datetime import datetime

DOCTYPE_CONFIG = "Configuracion Sincronizacion SAP"
FIELD_DATE = "ultima_fecha"
FIELD_TIME = "ultima_hora"


def get_ultima_sincronizacion():
    """
    Devuelve la fecha y hora de la última sincronización exitosa como string (YYYY-MM-DD, HH:MM:SS).
    Si no existe, devuelve un valor por defecto.
    """
    try:
        config = frappe.get_single(DOCTYPE_CONFIG)
        fecha = config.get(FIELD_DATE) or "2000-01-01"
        hora = config.get(FIELD_TIME) or "00:00:00"
        return fecha, hora
    except Exception:
        return "2000-01-01", "00:00:00"


def set_ultima_sincronizacion(nueva_fecha, nueva_hora):
    """
    Guarda la fecha y hora de la última sincronización exitosa.
    """
    try:
        config = frappe.get_single(DOCTYPE_CONFIG)
        config.set(FIELD_DATE, nueva_fecha)
        config.set(FIELD_TIME, nueva_hora)
        config.save(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Error actualizando timestamp de sincronización: {str(e)}")


def construir_filtro_por_fecha(fecha, hora):
    """
    Construye la condición de filtro para SAP basado en UpdateDate y UpdateTime.
    """
    return f"(UpdateDate gt '{fecha}') or (UpdateDate eq '{fecha}' and UpdateTime gt '{hora}')"
