# import frappe
# import requests
# from frappe import _
# from .sap_auth import login_sap

# SAP_URL = "https://apisap.yaesta.com.gt/b1s/v1"
# PAGE_SIZE = 20  # Tamaño de página para la paginación

# def obtener_clientes_sap_paginados(page=0):
#     """
#     Obtiene clientes de SAP con paginación
#     Args:
#         page (int): Número de página (0-based)
#     Returns:
#         list: Lista de clientes de la página solicitada
#     """
#     sesion = login_sap()
    
#     headers = {
#         "Prefer": f"odata.maxpagesize={PAGE_SIZE}",
#         "Content-Type": "application/json",
#         "Cookie": f"B1SESSION={sesion['session_id']}; ROUTEID={sesion['route_id']}"
#     }

#     # URL con filtros y paginación
#     skip = page * PAGE_SIZE
#     url = (f"{SAP_URL}/BusinessPartners?"
#            f"$filter=CardType eq 'C' and U_smart_cli eq '1'&"
#            f"$skip={skip}&$top={PAGE_SIZE}")
    
#     try:
#         response = requests.get(url, headers=headers, cookies=sesion["cookies"], verify=False)
#         response.raise_for_status()
#         return response.json().get("value", [])
#     except requests.exceptions.RequestException as e:
#         frappe.log_error(f"Error al obtener clientes de SAP: {str(e)}", "SAP Client Sync")
#         frappe.throw(_("Error al conectar con SAP. Por favor revisa los logs."))

# @frappe.whitelist()
# def mapear_cliente_sap_a_erpnext(cliente_sap):
#     """
#     Mapea los datos del cliente de SAP al formato de ERPNext
#     Args:
#         cliente_sap (dict): Datos del cliente desde SAP
#     Returns:
#         dict: Datos del cliente en formato ERPNext
#     """
#     return {
#         "customer_name": cliente_sap.get("CardName", ""),
#         "territory": "Guatemala",
#         "code_sap": cliente_sap.get("CardCode", "")
#         # Puedes agregar más mapeos según necesites
#     }
# @frappe.whitelist()
# def actualizar_o_crear_cliente(cliente_data):
#     """
#     Crea o actualiza un cliente en ERPNext
#     Args:
#         cliente_data (dict): Datos del cliente a crear/actualizar
#     Returns:
#         str: Nombre del cliente creado/actualizado
#     """
#     sap_code = cliente_data.get("code_sap")
    
#     # Buscar si el cliente ya existe por el código de SAP
#     cliente_existente = frappe.db.get_value("Customer", 
#                                           {"code_sap": sap_code}, 
#                                           "name")
    
#     if cliente_existente:
#         # Actualizar cliente existente
#         doc = frappe.get_doc("Customer", cliente_existente)
#         doc.update(cliente_data)
#         doc.save()
#         frappe.db.commit()
#         return doc.name
#     else:
#         # Crear nuevo cliente
#         doc = frappe.get_doc({
#             "doctype": "Customer",
#             **cliente_data
#         })
#         doc.insert()
#         frappe.db.commit()
#         return doc.name

# @frappe.whitelist()
# @frappe.whitelist()
# def sincronizar_clientes_desde_sap():
#     """
#     Función principal para sincronizar clientes desde SAP
#     Se ejecuta desde un botón en un Doctype
#     """
#     try:
#         page = 0
#         total_clientes = 0
#         sap_response_data = []  # Lista para almacenar datos de SAP
        
#         frappe.publish_realtime("sap_client_sync_progress", 
#                               {"progress": 0, "message": "Iniciando sincronización..."})
        
#         while True:
#             clientes_sap = obtener_clientes_sap_paginados(page)
            
#             if not clientes_sap:
#                 break  # No hay más páginas
                
#             # Almacenar datos crudos de SAP
#             sap_response_data.extend(clientes_sap)
                
#             for cliente_sap in clientes_sap:
#                 cliente_erp = mapear_cliente_sap_a_erpnext(cliente_sap)
#                 nombre_cliente = actualizar_o_crear_cliente(cliente_erp)
#                 total_clientes += 1
                
#                 frappe.publish_realtime("sap_client_sync_progress", {
#                     "progress": (page + 1) * 100 // (page + 2),
#                     "message": f"Procesando cliente {total_clientes}: {nombre_cliente}",
#                     "page": page + 1,
#                     "total": total_clientes
#                 })
            
#             page += 1
        
#         # Crear log con los datos completos de SAP
#         crear_log_sincronizacion(
#             status="Success",
#             total_records=total_clientes,
#             details={
#                 "sap_response": sap_response_data,
#                 "summary": {
#                     "total_pages": page,
#                     "total_clientes": total_clientes,
#                     "last_page": page - 1  # Porque page se incrementa después del último procesamiento
#                 }
#             }
#         )
        
#         frappe.publish_realtime("sap_client_sync_progress", {
#             "progress": 100,
#             "message": f"Sincronización completada. {total_clientes} clientes procesados.",
#             "refresh": True
#         })
        
#         return {
#             "success": True,
#             "message": f"Sincronización completada. {total_clientes} clientes procesados.",
#             "data_summary": {
#                 "total_pages": page,
#                 "total_clientes": total_clientes
#             }
#         }
        
#     except Exception as e:
#         # En caso de error, registrar tanto el error como los datos recolectados
#         crear_log_sincronizacion(
#             status="Failed",
#             total_records=total_clientes,
#             error_log=frappe.get_traceback(),
#             details={
#                 "sap_response": sap_response_data if 'sap_response_data' in locals() else None,
#                 "partial_progress": {
#                     "page": page,
#                     "processed": total_clientes
#                 }
#             }
#         )
#         frappe.throw(f"Error: {str(e)}")


# def crear_log_sincronizacion(status, total_records, error_log=None, details=None):
#     # Limitar a 60KB para evitar problemas
#     json_str = frappe.as_json(details)
#     if len(json_str) > 60000:
#         details = {
#             "_warning": "Datos truncados por tamaño",
#             "data_sample": details.get("sap_response")[:5] if details.get("sap_response") else None,
#             "total_records": len(details.get("sap_response")) if details.get("sap_response") else 0
#         }
    
#     log = frappe.get_doc({
#         "doctype": "Sincronizacion clientes SAP",
#         "sync_date": frappe.utils.now(),
#         "status": status,
#         "total_records": total_records,
#         "error_log": str(error_log)[:10000] if error_log else "",  # Limitar error
#         "sap_response": frappe.as_json(details, indent=2)[:65535]  # Asegurar límite
#     })
#     log.insert(ignore_permissions=True)
