import frappe

def obtener_filtros_validacion_sap(cliente, doctype_actual, doc):
    """
    Busca reglas de validación SAP para un cliente/doctype.
    Retorna una tupla: (ejecutar_validacion: bool, filtros_dinamicos: list)
    """
    config_doctype_name = "Clientes validad SAP"
    
    # Si el Doctype de configuración no existe, salimos
    if not frappe.db.exists("DocType", config_doctype_name):
        return False, []

    config = frappe.get_doc(config_doctype_name)
    
    # ⚠ IMPORTANTE: Aquí debes poner el fieldname real de la tabla en base de datos.
    # Reemplaza "nombre_real_tabla_hija" por el tuyo.
    tabla_reglas = config.get("clientes_campos_validar") or []
    print(f"Contenido de la tabla {tabla_reglas}")

    # Filtramos por cliente y doctype
    reglas_cliente = [
        regla for regla in tabla_reglas
        if regla.get("customer") == cliente and regla.get("doc_type") == doctype_actual
    ]

    # Si no hay reglas configuradas para este cliente/doctype, salimos
    if not reglas_cliente:
        return False, []

    filtros_dinamicos = []
    
    # Recorremos las reglas y extraemos los valores del 'doc'
    for regla in reglas_cliente:
        campo_erp = regla.campo_erpnext  # Ej: 'po_no'
        campo_sap = regla.campo_sap      # Ej: 'U_OrdenDeCompra'
        
        # Obtenemos el valor que el vendedor escribió en ERPNext
        valor_erp = doc.get(campo_erp)

        if campo_erp and campo_sap and valor_erp:
            filtros_dinamicos.append(f"{campo_sap} eq '{valor_erp}'")

    # Si logramos construir filtros, retornamos True y la lista
    if filtros_dinamicos:
        return True, filtros_dinamicos
    
    return False, []