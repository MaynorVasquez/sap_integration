from frappe import _
import frappe
import requests
import json
import traceback  # Importación añadida
from .blueprint import mapping_blueprint1, construir_url_sap
from .sap_auth import login_sap 
from .logs import log_sincronizacion


@frappe.whitelist()
def sincronizar_lista_alamacenes(docname=None):
    config = frappe.get_doc("Mapeo Almacenes SAP", docname)

    resultados = []

    for empresa in config.company_detalle:
        resultado = procesar_empresa_individual(config, empresa,docname)

        resultados.append({
            "company": empresa.company,
            "endpoint": empresa.endpoint,
            "resultado": resultado
        })

    return resultados



def procesar_empresa_individual(config, empresa,docname):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    doctype_logs = "Sincronizacion Almacenes SAP"
    doctype_target = "Warehouse"

    try:
        debug_messages.append(f"🚀 Procesando empresa: {empresa.company}")

        # 🔐 Login por empresa
        session = login_sap(empresa.company)

        if not session:
            raise Exception(f"No se pudo iniciar sesión para {empresa.company}")
        debug_messages.append("✔ Autenticación exitosa")

        #2. Obtener mapeo
        mapeo_lista = mapping_blueprint1(
            "Mapeo Almacenes SAP",
            "WarehouseCode",
            "custom_warehousecode"
        )
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos desde el blueprint")
        debug_messages.append("✔ Mapeo de campos exitoso")        

        # 🔁 PAGINACIÓN (tu código actual)
        top = 20
        page, skip = 1, 0

        while True:
            url_final = construir_url_sap(mapeo_lista,empresa.company, empresa.endpoint,  top=top, skip=skip)
            debug_messages.append(f"✔ URL: {url_final}")
            response = session.get(url_final)
            response.raise_for_status()

            data = response.json()
            lista_datos = data.get("value", [])
            detalles.extend(lista_datos)

            if not lista_datos:
                break

            skip += top
            page += 1

        # 🏭 Procesar datos
        for detalle in detalles:
            procesado, _ = procesar_datos(
                detalle,
                mapeo_lista,
                doctype_target,
                empresa.company,
                debug_messages
            )

            if procesado:
                total_procesados += 1

    except Exception as e:
        frappe.log_error(
            title=f"Error empresa {empresa.company}",
            message=frappe.get_traceback()
        )
        error_msg = f"Error durante sincronización: {str(e)}\n{traceback.format_exc()}"
        log_sincronizacion(
            doctype=doctype_logs,
            docname=docname,
            company = empresa.company,
            status="Error",
            total=total_procesados,
            detalles={},
            errores=error_msg
        )

    finally:
        if session:
            session.close()
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                company = empresa.company,
                status="Exitoso" if total_procesados > 0 else "Sin cambios",
                total=total_procesados,
                detalles=detalles, #Json devuelto
                errores=""
            )


    return {
        "empresa": empresa.company,
        "total": total_procesados,
        "status": "success" if total_procesados > 0 else "warning",
        "debug": debug_messages
    }

def procesar_datos(lista_mapeo, mapeo_lista, doctype, company,debug_messages):
    try:
        sap_key_field = mapeo_lista["key_field"]
        erp_key_field = mapeo_lista["erp_key_field"]
        sap_id = lista_mapeo.get(sap_key_field)

        if not sap_id:
            frappe.log_error("Dato sin código", json.dumps(lista_mapeo, indent=2))
            return None, None

        dato_existente = frappe.get_all(
            doctype,
            filters={erp_key_field: sap_id, "company": company},
            limit=1
        )

        # ✅ Ahora se utiliza el head 
        campos = mapeo_lista.get("sap_fields", {}).get("head", {})

        dato_lista = {}

        for erp_field, sap_field in campos.items():
            valor = lista_mapeo.get(sap_field)

            if erp_field == "disabled":
                valor = 1 if valor == "tYES" else 0

            dato_lista[erp_field] = valor

        dato_lista[erp_key_field] = sap_id
        dato_lista["company"] = company
        debug_messages.append(f"Lista de campos: {dato_lista}")

        if dato_existente:
            doc = frappe.get_doc(doctype, dato_existente[0].name)

            for campo, valor in dato_lista.items():
                debug_messages.append(f"Update --> campo: {campo} --- valor: {valor}")
                setattr(doc, campo, valor)

            doc.flags.ignore_permissions = True  
            doc.save()
            frappe.db.commit()

            return f"{sap_id} (actualizado)", dato_lista

        else:
            doc = frappe.new_doc(doctype)

            for campo, valor in dato_lista.items():
                debug_messages.append(f"insert --> campo: {campo} --- valor: {valor}")
                setattr(doc, campo, valor)

            doc.flags.ignore_permissions = True 
            doc.insert()
            frappe.db.commit()  # ✅ commit después de insertar
            return f"{sap_id} (creado)", dato_lista

    except Exception as e:
        frappe.log_error(
            f"Error al procesar datos {sap_id}: {str(e)}\n{traceback.format_exc()}"
        )
        return None, None


# @frappe.whitelist()
# def sincronizar_lista_alamacenes(company):
#     debug_messages = []
#     total_procesados = 0
#     session = None
#     detalles = []
#     doctype_logs = "Sincronizacion Almacenes SAP"
#     doctype_target = "Warehouse"
#     frappe.logger().info("🚀 Scheduler ejecutó sincronizar_lista_alamacenes")
#     print("🚀 Print: sincronizar_lista_alamacenes corrió")

#     try:
#         # 1. Autenticación
#         debug_messages.append(f"Iniciando autenticación con SAP {company}")
#         session = login_sap(company)

#         if not session or not isinstance(session, requests.Session):
#             raise Exception("La sesión SAP no se creó correctamente")
#         debug_messages.append("✔ Autenticación exitosa")
#         print("Cookies obtenidas:", session.cookies.get_dict())

#         # 2. Obtener mapeo
#         mapeo_lista = mapping_blueprint("Mapeo Almacenes SAP", "WarehouseCode", "custom_warehousecode")
#         if not mapeo_lista or "sap_fields" not in mapeo_lista:
#             raise Exception("No se pudo obtener el mapeo de campos desde el blueprint")
#         debug_messages.append("✔ Mapeo de campos exitoso")
#         print("✔ Mapeo de campos exitoso")

#         # 3. Paginación
#         print("Inicio de paginación URL: ", mapeo_lista["url"])
#         top = 20
#         page, skip = 1, 0
#         lista_datos = []
#         while True:
#             url_final = construir_url_sap(mapeo_lista, top=top, skip=skip)
#             debug_messages.append(f"URL: {url_final}")

#             intentos = 0
#             max_reintentos = 3
#             while intentos <= max_reintentos:
#                 try:
#                     response = session.get(url_final)
#                     if response.status_code == 401:
#                         debug_messages.append("⚠ Sesión expirada, intentando nueva sesión")
#                         session = login_sap(company)
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
#                 procesado, resultado = procesar_datos(detalle, mapeo_lista, doctype_target, company)
#                 if procesado:
#                     total_procesados += 1
#                     debug_messages.append(f"✔ Procesado: {procesado}")
#                     # log_sincronizacion(doctype_logs, procesado, resultado)  # ← Descomenta si deseas guardar log por registro
#                 else:
#                     debug_messages.append(f"✗ Falló procesar: {detalle}")

#     except Exception as e:
#         error_msg = f"Error durante sincronización: {str(e)}\n{traceback.format_exc()}"
#         debug_messages.append(f"✗ {error_msg}")
#         frappe.log_error(title="Error sincronizando listas de precios desde SAP", message=error_msg)

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



# def procesar_datos(lista_mapeo, mapeo_lista, doctype, company):
#     """Crea o actualiza documentos en ERPNext de forma genérica"""
#     try:
#         # Obtener campos clave
#         sap_key_field = mapeo_lista["key_field"]          # Ej: "KeySAP"
#         erp_key_field = mapeo_lista["erp_key_field"]      # Ej: "custom_ERPNEXT"
#         sap_id = lista_mapeo.get(sap_key_field)

#         print("Código sap: ", sap_id)

#         if not sap_id:
#             frappe.log_error("Dato sin código", json.dumps(lista_mapeo, indent=2))
#             return None, None  # No se puede continuar sin ID

        

#         # Buscar documento existente en ERPNext
#         dato_existente = frappe.get_all(doctype, filters={erp_key_field: sap_id, "company": company}, limit=1)

#         # Mapear datos SAP -> ERPNext
#         campos = mapeo_lista.get("sap_fields", {}).get("head", {})
#         dato_lista = {}
#         for erp_field, sap_field in campos.items():
#             valor = lista_mapeo.get(sap_field)

#             if erp_field == "disabled":
#                 valor = 1 if valor == "tYES" else 0

#             dato_lista[erp_field] = valor

#         print(dato_lista)
#         # Asegurar que el campo clave esté presente
#         dato_lista[erp_key_field] = sap_id
#         dato_lista["company"] = company

#         if dato_existente:
#             # Actualizar documento existente
#             doc = frappe.get_doc(doctype, dato_existente[0].name)
#             for campo, valor in dato_lista.items():
#                 setattr(doc, campo, valor)
           
#             try:
#                 # Esto ignora los permisos del usuario actual
#                 doc.flags.ignore_permissions = True  
#                 doc.save()
#                 frappe.db.commit()  # ✅ commit después de guardar
#             except frappe.exceptions.DocumentHasBeenModifiedError:
#                 frappe.db.rollback()
#             return f"{sap_id} (actualizado)", dato_lista
#         else:
#             # Crear nuevo documento
#             doc = frappe.new_doc(doctype)
#             for campo, valor in dato_lista.items():
#                 setattr(doc, campo, valor)
            
#             # Esto ignora los permisos del usuario actual
#             doc.flags.ignore_permissions = True 
#             doc.insert()
#             frappe.db.commit()  # ✅ commit después de insertar
#             return f"{sap_id} (creado)", dato_lista

#     except Exception as e:
#         frappe.log_error(f"Error al procesar datos {sap_id}: {str(e)}\n{traceback.format_exc()}")
#         return None, None

    
