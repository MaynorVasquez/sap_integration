import frappe
from frappe import _
import requests
import json
import traceback  # Importación añadida
from .logs import log_sincronizacion
from .blueprint import mapping_blueprint, construir_url_sap
from .sap_auth import login_sap

@frappe.whitelist()
def sincronizar_lista_clientes_grupos(docname=None):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    doctype_logs = "Sincronizacion Clientes Grupos SAP"
    doctype_target = "Customer Group"

    try:
        session = login_sap()
        if not session or not isinstance(session, requests.Session):
            raise Exception("No se pudo establecer la sesión con SAP.")
        print("Conexión exitosa...")

        mapeo_lista = mapping_blueprint("Mapeo Clientes Grupo SAP", "Code", "custom_code")
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos desde el blueprint")
        debug_messages.append("✔ Mapeo de campos exitoso")
        print("✔ Mapeo de campos exitoso")

        top = 20
        skip = 0
        page = 0
        print("Inicio de paginación URL: ", mapeo_lista["url"])

        while True:
            url_final = construir_url_sap(mapeo_lista, top=top, skip=skip)
            debug_messages.append(f"URL: {url_final}")

            intentos = 0
            max_reintentos = 3
            while intentos <= max_reintentos:
                try:
                    response = session.get(url_final, timeout=30)
                    if response.status_code == 401:
                        debug_messages.append("⚠ Sesión expirada, intentando nueva sesión")
                        session = login_sap()
                        intentos += 1
                        continue
                    response.raise_for_status()
                    data = response.json()
                    lista_datos = data.get("value", [])
                    detalles.extend(lista_datos)
                    break
                except Exception as e:
                    debug_messages.append(f"✗ Error al obtener datos desde SAP: {e}")
                    if intentos >= max_reintentos:
                        return {"status": "error", "message": "Error al obtener datos de SAP", "debug": debug_messages}
                    intentos += 1

            debug_messages.append(f"📄 Página {page} → Registros recibidos: {len(lista_datos)}")

            if not lista_datos:
                print("Fin de la paginación...")
                break

            skip += top
            page += 1

        debug_messages.append(f"✅ Total registros acumulados: {len(detalles)}")

        # Procesar todos los registros individualmente
        if detalles:
            for detalle in detalles:
                procesado, resultado = procesar_datos(detalle, mapeo_lista, doctype_target)
                if procesado:
                    total_procesados += 1
                    debug_messages.append(f"✔ Procesado: {procesado}")
                    # log_sincronizacion(doctype_logs, procesado, resultado)  # ← Descomenta si deseas guardar log por registro
                else:
                    debug_messages.append(f"✗ Falló procesar: {detalle}")

    except Exception as e:
        error_msg = f"✗ Error general: {str(e)}\n{traceback.format_exc()}"
        frappe.log_error(error_msg, "Sincronización Clientes Grupo SAP")
        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Error",
                total=total_procesados,
                detalles={},
                errores=error_msg
            )
        return {"status": "error", "message": "Fallo en la sincronización", "debug": debug_messages}

    finally:
        if session:
            print("Cerrando Sesión")
            session.close()
            debug_messages.append("✓ Sesión SAP cerrada correctamente")
        
        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Exitoso" if total_procesados > 0 else "Sin cambios",
                total=total_procesados,
                detalles=detalles, #Json devuelto
                errores=""
            )

    return {"status": "success", "total": total_procesados, "debug": debug_messages}



def procesar_datos(lista_mapeo, mapeo_lista, doctype):
    """Crea o actualiza documentos en ERPNext de forma genérica"""
    try:
        # Obtener campos clave
        sap_key_field = mapeo_lista["key_field"]          # Ej: "KeySAP"
        erp_key_field = mapeo_lista["erp_key_field"]      # Ej: "custom_ERPNEXT"
        sap_id = lista_mapeo.get(sap_key_field)

        print("Código sap: ", sap_id)

        if not sap_id:
            frappe.log_error("Dato sin código", json.dumps(lista_mapeo, indent=2))
            return None, None  # No se puede continuar sin ID

        

        # Buscar documento existente en ERPNext
        dato_existente = frappe.get_all(doctype, filters={erp_key_field: sap_id}, limit=1)

        # Mapear datos SAP -> ERPNext
        dato_lista = {}
        for erp_field, sap_field in mapeo_lista["sap_fields"].items():
            valor = lista_mapeo.get(sap_field)
            dato_lista[erp_field] = valor

        print(dato_lista)
        # Asegurar que el campo clave esté presente
        dato_lista[erp_key_field] = sap_id

        if dato_existente:
            # Actualizar documento existente
            doc = frappe.get_doc(doctype, dato_existente[0].name)
            for campo, valor in dato_lista.items():
                setattr(doc, campo, valor)
            try:
                # 👇 Esto ignora los permisos del usuario actual
                doc.flags.ignore_permissions = True 
                doc.save()
                frappe.db.commit()  # ✅ commit después de guardar
            except frappe.exceptions.DocumentHasBeenModifiedError:
                frappe.db.rollback()
            return f"{sap_id} (actualizado)", dato_lista
        else:
            # Crear nuevo documento
            doc = frappe.new_doc(doctype)
            for campo, valor in dato_lista.items():
                setattr(doc, campo, valor)
            # 👇 Esto ignora los permisos del usuario actual
            doc.flags.ignore_permissions = True 
            doc.insert()
            frappe.db.commit()  # ✅ commit después de insertar
            return f"{sap_id} (creado)", dato_lista

    except Exception as e:
        frappe.log_error(f"Error al procesar datos {sap_id}: {str(e)}\n{traceback.format_exc()}")
        return None, None