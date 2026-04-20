import frappe
from frappe import _
import json
import traceback  # Importación añadida
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual


@frappe.whitelist()

def sincronizar_lista_vendedores(docname=None):
    doctype_logs = "Sincronizacion person sales SAP"
    doctype_target =  "Sales Person"
    doctype_mapeo = "Mapeo Vendedores SAP"
    key_erpnext = "custom_salesemployeecode"
    key_sap = "SalesEmployeeCode"

    config = frappe.get_doc(doctype_mapeo, docname)

    resultados = []

    for empresa in config.company_detalle:
        resultado = procesar_empresa_individual(config, 
                                                empresa,
                                                docname,
                                                procesar_datos,
                                                doctype_logs,
                                                doctype_target,
                                                doctype_mapeo,
                                                key_sap,
                                                key_erpnext
                                                )

        resultados.append({
            "company": empresa.company,
            "endpoint": empresa.endpoint,
            "resultado": resultado
        })

    return resultados

def procesar_datos(lista_mapeo, mapeo_lista, doctype, company,debug_messages):
    """"Crea o actualiza lista de precios en ERPNEXT"""
    try:
        # Obtener campos clave
        sap_key_field = mapeo_lista["key_field"]          # Ej: "SalesEmployeeCode"
        erp_key_field = mapeo_lista["erp_key_field"]      # Ej: "custom_salesemployeecode"
        sap_id = lista_mapeo.get(sap_key_field)

        if not sap_id:
            frappe.log_error("Vendedor sin código", json.dumps(lista_mapeo, indent=2))
            return None  # No se puede continuar sin ID
        debug_messages.append(f"SAP ID : {sap_id}")

        #vendedor_existente = frappe.get_all(doctype, filters={erp_key_field: sap_id}, limit=1)
        # Buscar datos ERPNEXT
        dato_existente = frappe.get_all(
            doctype,
            filters={
                erp_key_field: sap_id,
                "custom_company": company
            },
            limit=1
        )
        debug_messages.append(f"Vendedor encontrado : {dato_existente}")

        # ✅ Ahora se utiliza el head 
        campos = mapeo_lista.get("sap_fields", {}).get("head", {})

        # Mapear datos SAP -> ERP
        dato_lista = {}
        nuevo_nombre = None
        company_abbr = frappe.get_value("Company", company, "abbr")

        for erp_field, sap_field in campos.items():
            valor = lista_mapeo.get(sap_field)
            if erp_field == "enabled":
                valor = 1 if valor == "tYES" else 0
            
            if erp_field == "sales_person_name":
                valor = f"{company_abbr} - {valor}"

            if erp_field == "name":
                nuevo_nombre = f"{company_abbr} - {valor}"
                continue

            dato_lista[erp_field] = valor

        
        # Asegurar que el campo clave esté presente
        dato_lista[erp_key_field] = sap_id
        dato_lista["custom_company"] = company
   
        if dato_existente:
            doc = frappe.get_doc(doctype, dato_existente[0].name)
            for campo, valor in dato_lista.items():
                if campo != "name":
                    setattr(doc, campo, valor)

                debug_messages.append(f"Update --> campo: {campo} --- valor: {valor}")
                setattr(doc, campo, valor)
            
                doc.flags.ignore_permissions = True 
                doc.save()
                frappe.db.commit()

            if nuevo_nombre and doc.name != nuevo_nombre:
                if not frappe.db.exists(doctype, nuevo_nombre):
                    frappe.rename_doc(doctype, doc.name, nuevo_nombre, force=True)

            return f"{sap_id} (actualizado)", dato_lista
        else:
            # Crea Vendedor Nuevo
            doc = frappe.new_doc(doctype)
            for campo, valor in dato_lista.items():
                debug_messages.append(f"insert --> campo: {campo} --- valor: {valor}")
                setattr(doc, campo, valor)
            doc.flags.ignore_permissions = True 
            doc.insert()
            frappe.db.commit()  # ✅ commit después de insertar
            return f"{sap_id} (creado)", dato_lista

    except Exception as e:
        frappe.log_error(f"Error al procesar lista vendedor {sap_id}: {str(e)}\n{traceback.format_exc()}")
        return None

@frappe.whitelist()
def asignar_vendedor_por_codigo_sap(datos_doc, sales_employee_code, campo_destino="sales_person", reintento=True):
    """
    Asigna el 'name' del Sales Person (buscado por custom_salesemployeecode=sales_employee_code)
    al campo especificado en datos_doc (por defecto 'sales_person').

    Si el vendedor no existe y reintento=True, intenta sincronizar desde SAP y reintenta la asignación.
    """
    if not sales_employee_code or str(sales_employee_code) == "-1":
        return False  # Nada que asignar

    vendedor_name = frappe.db.get_value("Sales Person", {"custom_salesemployeecode": sales_employee_code}, "name")

    if vendedor_name:
        datos_doc[campo_destino] = vendedor_name
        return True
    elif reintento:
        sincronizar_lista_vendedores()  # Asegúrate de que esta función está disponible
        return asignar_vendedor_por_codigo_sap(datos_doc, sales_employee_code, campo_destino, reintento=False)
    else:
        frappe.logger().info(f"No se encontró Sales Person con custom_salesemployeecode = {sales_employee_code} tras reintento")
        return False


# @frappe.whitelist()
# def sincronizar_lista_vendedores(docname=None):
#     debug_messages = []
#     total_procesados = 0
#     session = None
#     detalles = []
#     doctype_logs = "Sincronizacion person sales SAP"
#     doctype_target = "Sales Person"
#     detalle = []

#     try:
#         # 1. Autenticación
#         debug_messages.append("Iniciando autenticación con SAP...")
#         session = login_sap()

#         if not session or not isinstance(session, requests.Session):
#             raise Exception("La sesión SAP no se creó correctamente")
#         debug_messages.append("✔ Autenticación exitosa")

#         # 2. Obtener vendedores
#         mapeo_lista = mapping_blueprint("Mapeo Vendedores SAP", "SalesEmployeeCode", "custom_salesemployeecode")
#         if not mapeo_lista or "sap_fields" not in mapeo_lista:
#             raise Exception("No se pudo obtener el mapeo de campos desde el blueprint")
#         debug_messages.append("✔ Mapeo de campos exitoso")
#         print("✔ Mapeo de campos exitoso")

#         top = 20
#         skip = 0
#         page = 0
#         print("Inicio de paginación URL: ", mapeo_lista["url"])

#         while True:
#             url_final = construir_url_sap(mapeo_lista, top=top, skip=skip)
#             debug_messages.append(f"URL: {url_final}")

#             intentos = 0
#             max_reintentos = 3
#             while intentos <= max_reintentos:
#                 try:
#                     response = session.get(url_final, timeout=30)
#                     if response.status_code == 401:
#                         debug_messages.append("⚠ Sesión expirada, intentando nueva sesión")
#                         session = login_sap()
#                         intentos += 1
#                         continue
#                     response.raise_for_status()
#                     data = response.json()
#                     lista_datos = data.get("value", [])
#                     detalles.extend(lista_datos)
#                     break
#                 except Exception as e:
#                     debug_messages.append(f"✗ Error al obtener datos desde SAP: {e}")
#                     if intentos >= max_reintentos:
#                         return {"status": "error", "message": "Error al obtener datos de SAP", "debug": debug_messages}
#                     intentos += 1

#             debug_messages.append(f"📄 Página {page} → Registros recibidos: {len(lista_datos)}")

#             if not lista_datos:
#                 print("Fin de la paginación...")
#                 break

#             skip += top
#             page += 1

#         debug_messages.append(f"✅ Total registros acumulados: {len(detalles)}")

#         # Procesar todos los registros individualmente
#         if detalles:
#             for detalle in detalles:
#                 procesado = procesar_datos(detalle, mapeo_lista, doctype = doctype_target)
#                 if procesado:
#                     total_procesados += 1
#                     debug_messages.append(f"✔ Procesado: {procesado}")
#                 else:
#                     debug_messages.append(f"✗ Falló procesar: {detalle}")        

#     except Exception as e:
#         error_msg = f"Error durante sincronización: {str(e)}"
#         debug_messages.append(f"✗ {error_msg}")
#         frappe.log_error(title="Vendedores:", message= f"{detalle} --- {error_msg}")

#         if docname:
#             log_sincronizacion(
#                 doctype=doctype_logs,
#                 docname=docname,
#                 status="Error",
#                 total=total_procesados,
#                 detalles={},
#                 errores=error_msg
#             )

#         return {
#             "status": "error",
#             "message": "Ocurrió un error durante la sincronización",
#             "debug": debug_messages,
#             "total": total_procesados
#         }
    
#     finally:        
#         if session and isinstance(session, requests.Session):
#             session.close()
#             debug_messages.append("✓ Sesión SAP cerrada correctamente")

#         if docname:
#             log_sincronizacion(
#                 doctype=doctype_logs,
#                 docname=docname,
#                 status="Exitoso" if total_procesados > 0 else "Sin cambios",
#                 total=total_procesados,
#                 detalles=detalles, #Json devuelto
#                 errores=""
#             )
#     return {
#         "status": "success" if total_procesados > 0 else "warning",
#         "total": total_procesados,
#         "debug": debug_messages
#     }

