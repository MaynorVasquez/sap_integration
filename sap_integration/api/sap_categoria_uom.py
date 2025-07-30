import frappe
from frappe import _
import requests
import json
import traceback  # Importación añadida
from .blueprint import mapping_blueprint, construir_url_sap
from .sap_auth import login_sap 
from .logs import log_sincronizacion


@frappe.whitelist()
def sincronizar_lista_categoria_uom(docname=None):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    doctype_logs = "Sincronizacion UOM"
    doctype_target = "UOM Category"

    try:
        # 1. Autenticación
        debug_messages.append("Iniciando autenticación con SAP...")
        session = login_sap()

        if not session or not isinstance(session, requests.Session):
            raise Exception("La sesión SAP no se creó correctamente")
        debug_messages.append("✔ Autenticación exitosa")
        print("✔ Autenticación exitosa")

        # 2. Obtener mapeo
        mapeo_lista = mapping_blueprint("Mapeo Categoria UOM", "AbsEntry", "custom_absentry")
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos desde el blueprint")
        debug_messages.append("✔ Mapeo de campos exitoso")
        print("✔ Mapeo de campos exitoso")

        # 3. Obtener datos del endpoint
        url_final = construir_url_sap(mapeo_lista)
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
        error_msg = f"Error durante sincronización: {str(e)}\n{traceback.format_exc()}"
        debug_messages.append(f"✗ {error_msg}")
        frappe.log_error(title="Error al sincronizar desde SAP", message=error_msg)

        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Error",
                total=total_procesados,
                detalles={},
                errores=error_msg
            )

        return {
            "status": "error",
            "message": "Ocurrió un error durante la sincronización",
            "debug": debug_messages,
            "total": total_procesados
        }

    finally:
        if session and isinstance(session, requests.Session):
            session.close()
            debug_messages.append("✓ Sesión SAP cerrada correctamente")

        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Exitoso" if total_procesados > 0 else "Sin cambios",
                total=total_procesados,
                detalles=detalles,
                errores=""
            )

    return {
        "status": "success" if total_procesados > 0 else "warning",
        "total": total_procesados,
        "debug": debug_messages
    }


@frappe.whitelist()
def sincronizar_lista_uom(docname=None):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    doctype_logs = "Sincronizacion UOM"
    doctype_target = "UOM"

    try:
        # 1. Autenticación
        debug_messages.append("Iniciando autenticación con SAP...")
        session = login_sap()

        if not session or not isinstance(session, requests.Session):
            raise Exception("La sesión SAP no se creó correctamente")
        debug_messages.append("✔ Autenticación exitosa")

        # 2. Obtener mapeo
        mapeo_lista = mapping_blueprint("Mapeo UOM", "AbsEntry", "custom_absentry")
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos desde el blueprint")
        debug_messages.append("✔ Mapeo de campos exitoso")
        print("✔ Mapeo de campos exitoso")

        # 3. Obtener datos del endpoint
        url_final = construir_url_sap(mapeo_lista)
        debug_messages.append(f"URL: {url_final}")

        
        top = 20
        page, skip = 1, 0
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

        print(detalles)

        # Procesar todos los registros individualmente
        if detalles:
            for detalle in detalles:
                procesado = procesar_datos(detalle, mapeo_lista, doctype_target)
                if procesado:
                    total_procesados += 1
                    debug_messages.append(f"✔ Procesado: {procesado}")
                    # log_sincronizacion(doctype_logs, procesado, resultado)  # ← Descomenta si deseas guardar log por registro
                else:
                    debug_messages.append(f"✗ Falló procesar: {detalle}")

    except Exception as e:
        error_msg = f"Error durante sincronización: {str(e)}\n{traceback.format_exc()}"
        debug_messages.append(f"✗ {error_msg}")
        frappe.log_error(title="Error al sincronizar desde SAP", message=error_msg)

        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Error",
                total=total_procesados,
                detalles={},
                errores=error_msg
            )

        return {
            "status": "error",
            "message": "Ocurrió un error durante la sincronización",
            "debug": debug_messages,
            "total": total_procesados
        }

    finally:
        if session and isinstance(session, requests.Session):
            session.close()
            debug_messages.append("✓ Sesión SAP cerrada correctamente")

        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Exitoso" if total_procesados > 0 else "Sin cambios",
                total=total_procesados,
                detalles=detalles,
                errores=""
            )

    return {
        "status": "success" if total_procesados > 0 else "warning",
        "total": total_procesados,
        "debug": debug_messages
    }




def procesar_datos(lista_mapeo, mapeo_lista, doctype):
    """Crea o actualiza documentos en ERPNext de forma genérica"""
    try:
        # Obtener campos clave
        sap_key_field = mapeo_lista["key_field"]          # Ej: "KeySAP"
        erp_key_field = mapeo_lista["erp_key_field"]      # Ej: "custom_ERPNEXT"
        sap_id = lista_mapeo.get(sap_key_field)
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

        # Asegurar que el campo clave esté presente
        dato_lista[erp_key_field] = sap_id

        if dato_existente:
            # Actualizar documento existente
            doc = frappe.get_doc(doctype, dato_existente[0].name)
            for campo, valor in dato_lista.items():
                setattr(doc, campo, valor)
            try:
                doc.save()
            except frappe.exceptions.DocumentHasBeenModifiedError:
                frappe.db.rollback()
            return f"{sap_id} (actualizado)", dato_lista
        else:
            # Crear nuevo documento
            doc = frappe.new_doc(doctype)
            for campo, valor in dato_lista.items():
                setattr(doc, campo, valor)
            doc.insert()
            return f"{sap_id} (creado)", dato_lista

    except Exception as e:
        frappe.log_error(f"Error al procesar datos {sap_id}: {str(e)}\n{traceback.format_exc()}")
        return None, None


@frappe.whitelist()
def sincronizar_factores_conversion(docname=None):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    doctype_logs = "Sincronizacion UOM"

    try:
        debug_messages.append("Iniciando autenticación con SAP...")
        session = login_sap()

        if not session or not isinstance(session, requests.Session):
            raise Exception("La sesión SAP no se creó correctamente")
        debug_messages.append("✔ Autenticación exitosa")

        # 2. Obtener mapeo
        mapeo_lista = mapping_blueprint("Mapeo UOM factores conversion SAP", "AbsEntry", "custom_absentry")
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos desde el blueprint")
        debug_messages.append("✔ Mapeo de campos exitoso")
        print("✔ Mapeo de campos exitoso")

        # 3. Obtener datos del endpoint
        url_final = construir_url_sap(mapeo_lista)
        debug_messages.append(f"URL: {url_final}")

        response = session.get(url_final, timeout=30)
        response.raise_for_status()
        data = response.json()

        grupos = data.get('value', [])
        if not grupos:
            debug_messages.append("✗ No se recibieron grupos de UOM desde SAP.")
        else:
            debug_messages.append(f"✔ {len(grupos)} grupos de UOM obtenidos")

            for grupo in grupos:
                categoria_id = grupo.get("AbsEntry")
                categoria = frappe.get_value("UOM Category", {"custom_absentry": categoria_id}, "name")
                print(f"Categoria encontrado: {categoria}")
                if not categoria:
                    debug_messages.append(f"✗ Categoría ID {categoria_id} no encontrada en ERPNext")
                    continue

                base_uom_code = grupo.get("BaseUoM")
                print(f"Código base UOM encontrado: {base_uom_code}")
                if base_uom_code == -1:
                    continue

                base_uom = frappe.get_value("UOM", {"custom_absentry": base_uom_code}, "name")
                print(f"nombre base UOM: {base_uom}")
                if not base_uom:
                    debug_messages.append(f"✗ Base UOM ID {base_uom_code} no encontrado en ERPNext")
                    continue

                for definicion in grupo.get("UoMGroupDefinitionCollection", []):
                    if definicion.get("AlternateUoM") == -1 or definicion.get("Active") != "tYES":
                        continue

                    alt_uom_code = definicion.get("AlternateUoM")
                    alt_uom = frappe.get_value("UOM", {"custom_absentry": alt_uom_code}, "name")
                    if not alt_uom:
                        debug_messages.append(f"✗ UOM alternativo ID {alt_uom_code} no encontrado en ERPNext")
                        continue

                    factor = definicion.get("BaseQuantity", 1)
                    if factor == 0:
                        debug_messages.append(f"✗ Factor no válido (0) para {alt_uom} ➜ {base_uom}")
                        continue

                    try:
                        conversion = frappe.get_all("UOM Conversion Factor", filters={
                            "category": categoria,
                            "from_uom": alt_uom,
                            "to_uom": base_uom
                        })

                        if conversion:
                            doc = frappe.get_doc("UOM Conversion Factor", conversion[0].name)
                            doc.conversion_factor = factor
                            doc.value = factor
                            doc.save(ignore_permissions=True)
                            debug_messages.append(f"✓ Factor actualizado: {alt_uom} ➜ {base_uom} ({factor})")
                        else:
                            doc = frappe.get_doc({
                                "doctype": "UOM Conversion Factor",
                                "category": categoria,
                                "from_uom": alt_uom,
                                "to_uom": base_uom,
                                "conversion_factor": factor,
                                "value": factor
                            })
                            doc.insert(ignore_permissions=True)
                            debug_messages.append(f"✓ Factor creado: {alt_uom} ➜ {base_uom} ({factor})")

                        total_procesados += 1
                        detalles.append({
                            "from": alt_uom,
                            "to": base_uom,
                            "factor": factor
                        })

                    except Exception as ex:
                        frappe.log_error(f"Error al insertar factor:\n{frappe.as_json(doc)}", "Error en UOM Conversion Factor")
                        debug_messages.append(f"✗ Error al crear factor: {alt_uom} ➜ {base_uom}: {str(ex)}")

            frappe.db.commit()

    except Exception as e:
        error_msg = f"Error durante sincronización: {str(e)}\n{traceback.format_exc()}"
        debug_messages.append(f"✗ {error_msg}")
        frappe.log_error(title="Error al sincronizar factores UOM desde SAP", message=error_msg)

        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Error",
                total=total_procesados,
                detalles={},
                errores=error_msg
            )

        return {
            "status": "error",
            "message": "Ocurrió un error durante la sincronización",
            "debug": debug_messages,
            "total": total_procesados
        }

    finally:
        if session and isinstance(session, requests.Session):
            session.close()
            debug_messages.append("✓ Sesión SAP cerrada correctamente")

        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Exitoso" if total_procesados > 0 else "Sin cambios",
                total=total_procesados,
                detalles=detalles,
                errores=""
            )

    return {
        "status": "success" if total_procesados > 0 else "warning",
        "total": total_procesados,
        "debug": debug_messages
    }


