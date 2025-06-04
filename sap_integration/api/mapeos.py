# /apps/tu_app/tu_app/mapeos.py
import frappe
from frappe import _


def obtener_mapeo(doctype_padre, doctype_hijo, campos_mapeo):
    """
    Función genérica para obtener mapeos entre sistemas
    
    Args:
        doctype_padre (str): Nombre del Doctype padre (ej: "Mapeo Cliente")
        doctype_hijo (str): Nombre del Doctype hijo/table (ej: "Mapeo Campos SAP")
        campos_mapeo (dict): Diccionario con los campos a mapear 
                             (ej: {"campo_erp": "campo_erpnext", "campo_externo": "campo_sap"})
    
    Returns:
        dict: {"success": bool, "data": list, "count": int, "error": str}
    """
    try:
        # Validación de existencia de Doctypes
        if not frappe.db.exists("DocType", doctype_padre):
            return {"success": False, "error": _(f"Doctype padre '{doctype_padre}' no existe")}
            
        if not frappe.db.exists("DocType", doctype_hijo):
            return {"success": False, "error": _(f"Doctype hijo '{doctype_hijo}' no existe")}

        # Construcción dinámica de campos para la consulta
        campos_select = [
            f"parent AS documento_padre",
            f"{campos_mapeo['campo_erp']} AS campo_erpnext",
            f"{campos_mapeo['campo_externo']} AS campo_sap"
        ]
        
        # Consulta a la base de datos
        registros = frappe.db.sql(f"""
            SELECT {', '.join(campos_select)}
            FROM `tab{doctype_hijo}`
            WHERE parenttype = %s
        """, doctype_padre, as_dict=True)

        return {
            "success": True,
            "count": len(registros),
            "data": registros
        }

    except Exception as e:
        frappe.log_error(_("Error en obtener_mapeo"), f"Doctypes: {doctype_padre}/{doctype_hijo}\nError: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_mapeo_cliente():
    """Función adaptada para procesar la estructura actual del mapeo"""
    resultado = obtener_mapeo (
        doctype_padre="Mapeo Cliente",
        doctype_hijo="Mapeo Campos SAP",
        campos_mapeo={
            "campo_erp": "campo_erpnext",
            "campo_externo": "campo_sap"
        }
    )
    
    if not resultado or not resultado.get('success') or not resultado.get('data'):
        frappe.throw("No se pudo obtener el mapeo de campos para clientes o la estructura es inválida")
    
    # Procesar la estructura de datos recibida
    mapeo = {
        "key_field": "CardCode",  # Campo clave en SAP
        "erp_key_field": "custom_cardcode",  # Campo clave en ERPNext
        "sap_fields": {},  # Diccionario para mapeos campo_erp: campo_sap
        "defaults": {}  # Valores por defecto si es necesario
    }
    
    for item in resultado['data']:
        # Verificamos que tenga los campos necesarios y no esté duplicado
        if all(key in item for key in ['campo_erpnext', 'campo_sap']):
            campo_erp = item['campo_erpnext'].strip()  # Eliminamos espacios en blanco
            campo_sap = item['campo_sap'].strip()
            
            if campo_erp not in mapeo["sap_fields"]:
                mapeo["sap_fields"][campo_erp] = campo_sap
    
    if not mapeo["sap_fields"]:
        frappe.throw("El mapeo obtenido no contiene campos válidos")
    
    return mapeo




@frappe.whitelist()
def get_mapeo_cliente_direcciones():
    """Función adaptada para procesar la estructura actual del mapeo"""
    resultado = obtener_mapeo(
        doctype_padre="Mapeo Cliente Direcciones",
        doctype_hijo="Mapeo Campos SAP",
        campos_mapeo={
            "campo_erp": "campo_erpnext",
            "campo_externo": "campo_sap"
        }
    )
    
    if not resultado or not resultado.get('success') or not resultado.get('data'):
        frappe.throw("No se pudo obtener el mapeo de campos para clientes o la estructura es inválida")
    
    # Procesar la estructura de datos recibida
    mapeo = {
        "key_field": "CardCode",  # Campo clave en SAP
        "erp_key_field": "custom_cardcode",  # Campo clave en ERPNext
        "sap_fields": {},  # Diccionario para mapeos campo_erp: campo_sap
        "defaults": {}  # Valores por defecto si es necesario
    }
    
    for item in resultado['data']:
        # Verificamos que tenga los campos necesarios y no esté duplicado
        if all(key in item for key in ['campo_erpnext', 'campo_sap']):
            campo_erp = item['campo_erpnext'].strip()  # Eliminamos espacios en blanco
            campo_sap = item['campo_sap'].strip()
            
            if campo_erp not in mapeo["sap_fields"]:
                mapeo["sap_fields"][campo_erp] = campo_sap
    
    if not mapeo["sap_fields"]:
        frappe.throw("El mapeo obtenido no contiene campos válidos")
    
    return mapeo

@frappe.whitelist()
def get_mapeo_lista_precio():
    """Función adaptada para procesar la estructura actual del mapeo"""
    resultado = obtener_mapeo(
        doctype_padre="Mapeo Lista De Precios",
        doctype_hijo="Mapeo Campos SAP",
        campos_mapeo={
            "campo_erp": "campo_erpnext",
            "campo_externo": "campo_sap"
        }
    )
    
    if not resultado or not resultado.get('success') or not resultado.get('data'):
        frappe.throw("No se pudo obtener el mapeo de campos para clientes o la estructura es inválida")
    
    # Procesar la estructura de datos recibida
    mapeo = {
        "key_field": "PriceListNo",  # Campo clave en SAP
        "erp_key_field": "custom_pricelistno",  # Campo clave en ERPNext
        "sap_fields": {},  # Diccionario para mapeos campo_erp: campo_sap
        "defaults": {}  # Valores por defecto si es necesario
    }
    
    for item in resultado['data']:
        # Verificamos que tenga los campos necesarios y no esté duplicado
        if all(key in item for key in ['campo_erpnext', 'campo_sap']):
            campo_erp = item['campo_erpnext'].strip()  # Eliminamos espacios en blanco
            campo_sap = item['campo_sap'].strip()
            
            if campo_erp not in mapeo["sap_fields"]:
                mapeo["sap_fields"][campo_erp] = campo_sap
    
    if not mapeo["sap_fields"]:
        frappe.throw("El mapeo obtenido no contiene campos válidos")
    
    return mapeo


def get_mapeo_vendedores():
    """Función adaptada para procesar la estructura actual del mapeo"""
    resultado = obtener_mapeo(
        doctype_padre="Mapeo Vendedores",
        doctype_hijo="Mapeo Campos SAP",
        campos_mapeo={
            "campo_erp": "campo_erpnext",
            "campo_externo": "campo_sap"
        }
    )
    
    if not resultado or not resultado.get('success') or not resultado.get('data'):
        frappe.throw("No se pudo obtener el mapeo de campos para clientes o la estructura es inválida")
    
    # Procesar la estructura de datos recibida
    mapeo = {
        "key_field": "SalesEmployeeCode",  # Campo clave en SAP
        "erp_key_field": "custom_salesemployeecode",  # Campo clave en ERPNext
        "sap_fields": {},  # Diccionario para mapeos campo_erp: campo_sap
        "defaults": {}  # Valores por defecto si es necesario
    }
    
    for item in resultado['data']:
        # Verificamos que tenga los campos necesarios y no esté duplicado
        if all(key in item for key in ['campo_erpnext', 'campo_sap']):
            campo_erp = item['campo_erpnext'].strip()  # Eliminamos espacios en blanco
            campo_sap = item['campo_sap'].strip()
            
            if campo_erp not in mapeo["sap_fields"]:
                mapeo["sap_fields"][campo_erp] = campo_sap
    
    if not mapeo["sap_fields"]:
        frappe.throw("El mapeo obtenido no contiene campos válidos")
    
    return mapeo

def get_mapeo_categoria_uom():
    """Función adaptada para procesar la estructura actual del mapeo"""
    resultado = obtener_mapeo(
        doctype_padre="Mapeo Categoria UOM",
        doctype_hijo="Mapeo Campos SAP",
        campos_mapeo={
            "campo_erp": "campo_erpnext",
            "campo_externo": "campo_sap"
        }
    )
    
    if not resultado or not resultado.get('success') or not resultado.get('data'):
        frappe.throw("No se pudo obtener el mapeo de campos para clientes o la estructura es inválida")
    
    # Procesar la estructura de datos recibida
    mapeo = {
        "key_field": "AbsEntry",  # Campo clave en SAP
        "erp_key_field": "custom_absentry",  # Campo clave en ERPNext
        "sap_fields": {},  # Diccionario para mapeos campo_erp: campo_sap
        "defaults": {}  # Valores por defecto si es necesario
    }
    
    for item in resultado['data']:
        # Verificamos que tenga los campos necesarios y no esté duplicado
        if all(key in item for key in ['campo_erpnext', 'campo_sap']):
            campo_erp = item['campo_erpnext'].strip()  # Eliminamos espacios en blanco
            campo_sap = item['campo_sap'].strip()
            
            if campo_erp not in mapeo["sap_fields"]:
                mapeo["sap_fields"][campo_erp] = campo_sap
    
    if not mapeo["sap_fields"]:
        frappe.throw("El mapeo obtenido no contiene campos válidos")
    
    return mapeo

def get_mapeo_uom():
    """Función adaptada para procesar la estructura actual del mapeo"""
    resultado = obtener_mapeo(
        doctype_padre="Mapeo UOM",
        doctype_hijo="Mapeo Campos SAP",
        campos_mapeo={
            "campo_erp": "campo_erpnext",
            "campo_externo": "campo_sap"
        }
    )
    
    if not resultado or not resultado.get('success') or not resultado.get('data'):
        frappe.throw("No se pudo obtener el mapeo de campos para clientes o la estructura es inválida")
    
    # Procesar la estructura de datos recibida
    mapeo = {
        "key_field": "AbsEntry",  # Campo clave en SAP
        "erp_key_field": "custom_absentry",  # Campo clave en ERPNext
        "sap_fields": {},  # Diccionario para mapeos campo_erp: campo_sap
        "defaults": {}  # Valores por defecto si es necesario
    }
    
    for item in resultado['data']:
        # Verificamos que tenga los campos necesarios y no esté duplicado
        if all(key in item for key in ['campo_erpnext', 'campo_sap']):
            campo_erp = item['campo_erpnext'].strip()  # Eliminamos espacios en blanco
            campo_sap = item['campo_sap'].strip()
            
            if campo_erp not in mapeo["sap_fields"]:
                mapeo["sap_fields"][campo_erp] = campo_sap
    
    if not mapeo["sap_fields"]:
        frappe.throw("El mapeo obtenido no contiene campos válidos")
    
    return mapeo

def get_mapeo_almacenes():
    """Función adaptada para procesar la estructura actual del mapeo"""
    resultado = obtener_mapeo(
        doctype_padre="Mapeo Almacenes SAP",
        doctype_hijo="Mapeo Campos SAP",
        campos_mapeo={
            "campo_erp": "campo_erpnext",
            "campo_externo": "campo_sap"
        }
    )
    
    if not resultado or not resultado.get('success') or not resultado.get('data'):
        frappe.throw("No se pudo obtener el mapeo de campos para clientes o la estructura es inválida")
    
    # Procesar la estructura de datos recibida
    mapeo = {
        "key_field": "WarehouseCode",  # Campo clave en SAP
        "erp_key_field": "custom_warehousecode",  # Campo clave en ERPNext
        "sap_fields": {},  # Diccionario para mapeos campo_erp: campo_sap
        "defaults": {}  # Valores por defecto si es necesario
    }
    
    for item in resultado['data']:
        # Verificamos que tenga los campos necesarios y no esté duplicado
        if all(key in item for key in ['campo_erpnext', 'campo_sap']):
            campo_erp = item['campo_erpnext'].strip()  # Eliminamos espacios en blanco
            campo_sap = item['campo_sap'].strip()
            
            if campo_erp not in mapeo["sap_fields"]:
                mapeo["sap_fields"][campo_erp] = campo_sap
    
    if not mapeo["sap_fields"]:
        frappe.throw("El mapeo obtenido no contiene campos válidos")
    
    return mapeo

def mapping_blueprint(doctype, key_field_sap, key_field_erpnext):
    """Función adaptada para procesar la estructura actual del mapeo"""
    resultado = obtener_mapeo(
        doctype_padre=doctype,
        doctype_hijo="Mapeo Campos SAP",
        campos_mapeo={
            "campo_erp": "campo_erpnext",
            "campo_externo": "campo_sap"
        }
    )
    
    if not resultado or not resultado.get('success') or not resultado.get('data'):
        frappe.throw("No se pudo obtener el mapeo de campos para clientes o la estructura es inválida")
    
    # Procesar la estructura de datos recibida
    mapeo = {
        "key_field": key_field_sap,  # Campo clave en SAP
        "erp_key_field": key_field_erpnext,  # Campo clave en ERPNext
        "sap_fields": {},  # Diccionario para mapeos campo_erp: campo_sap
        "defaults": {}  # Valores por defecto si es necesario
    }
    
    for item in resultado['data']:
        # Verificamos que tenga los campos necesarios y no esté duplicado
        if all(key in item for key in ['campo_erpnext', 'campo_sap']):
            campo_erp = item['campo_erpnext'].strip()  # Eliminamos espacios en blanco
            campo_sap = item['campo_sap'].strip()
            
            if campo_erp not in mapeo["sap_fields"]:
                mapeo["sap_fields"][campo_erp] = campo_sap
    
    if not mapeo["sap_fields"]:
        frappe.throw("El mapeo obtenido no contiene campos válidos")
    
    return mapeo