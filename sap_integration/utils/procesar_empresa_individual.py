import frappe
from frappe import _
import hashlib
import traceback  # Importación añadida
import json
from sap_integration.api.logs import log_sincronizacion
from sap_integration.api.blueprint import mapping_blueprint1, construir_url_sap
from sap_integration.api.sap_auth import login_sap
from sap_integration.utils.url_filtro_fecha_tiempo import construir_filtro_tiempo, inyectar_filtro_a_url
from frappe.utils import now_datetime, add_to_date


def procesar_empresa_individual(config, 
                                empresa,
                                docname,
                                procesar_datos,
                                doctype_logs,
                                doctype_target,
                                doctype_mapeo,                                
                                key_sap,
                                key_erpnext,
                                usa_paginacion=True,
                                almacen=None,
                                campos_delta=None):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    sync_failed = False
    try:

        # 1. Obtienes la hora actual (Ej: 2026-06-11 11:50:53)
        hora_inicio_job = now_datetime()
        # 2. "Limpiamos" los segundos llevándolos a cero (Ej: 2026-06-11 11:50:00)
        hora_exacta = hora_inicio_job.replace(second=0, microsecond=0)

        print(f"🚀 Procesando empresa: {empresa.company}")
        print(f"🚀 Procesando empresa Endpoint: {empresa.endpoint}")

        # 🔐 Login por empresa
        session = login_sap(empresa.company)

        if not session:
            raise Exception(f"No se pudo iniciar sesión para {empresa.company}")
        print("✔ Autenticación exitosa")

        #2. Obtener mapeo
        mapeo_lista = mapping_blueprint1(doctype_mapeo, key_sap, key_erpnext )
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos desde el blueprint")
        #print(f"✔ Mapeo de campos exitoso : {json.dumps(mapeo_lista, indent=2)}")

        datos_delta = frappe.db.get_value(
            "Campos Delta Load", # <-- Nombre del DocType de la tabla HIJA
            filters={
                "parent": "Delta Load Transaccionales", # El padre en un Single siempre se llama igual que el DocType
                "company": empresa.company,   # Tu variable de empresa
                "doc_type": doctype_target,   # Ej: "Sales Order"
                "enabled": 1                  # Solo si está marcado el check
            },
            fieldname=["name", "date_time"],  # Traemos la fecha y el ID único de la fila
            as_dict=True
        )
        ultima_sync = None
        fila_id = None # Guardamos el ID para actualizarla después

        if datos_delta:
            ultima_sync = datos_delta.date_time
            fila_id = datos_delta.name

        # 🔁 PAGINACIÓN (tu código actual)
        top = 20
        skip = 0
        page_count = 0
        seen_pages = set()
        max_pages = int(frappe.conf.get("sap_max_pages") or 10000)

        url_final = None

        filtro_tiempo = construir_filtro_tiempo(ultima_sync, campos_delta)
        print(f"Filtro de tiempo: {filtro_tiempo}")

        while True:
    
            url_base = construir_url_sap(mapeo_lista, empresa.company, empresa.endpoint, usa_paginacion, almacen, top=top, skip=skip)
            if filtro_tiempo:
                url_final = inyectar_filtro_a_url(url_base, filtro_tiempo)
            else:
                url_final = url_base
            
            print(f"✔ URL: {url_final}")
            timeout = float(frappe.conf.get("sap_request_timeout") or 60)
            response = session.get(url_final, timeout=(10, timeout))
            response.raise_for_status()
            #print(f"Respuesta servidor: {response}")

            data = response.json()
            lista_datos = data.get("value", [])
            page_count += 1

            if lista_datos and usa_paginacion:
                page_fingerprint = hashlib.sha256(
                    json.dumps(lista_datos, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
                if page_fingerprint in seen_pages:
                    raise RuntimeError(
                        f"SAP repitió una página para {empresa.company}; "
                        "se detuvo la sincronización sin avanzar el delta."
                    )
                seen_pages.add(page_fingerprint)

            if page_count > max_pages:
                raise RuntimeError(
                    f"La sincronización superó el límite de {max_pages} páginas; "
                    "se detuvo sin avanzar el delta."
                )
            #print(f"Datos: {json.dumps(data, indent=2)}")

            # Si SAP no devuelve datos, salir de la función inmediatamente
            # if not lista_datos:
            #     print("⚠ SAP no devolvió datos. No hay nada que procesar.")
            #     return
            
            detalles.extend(lista_datos)
            #print(f"Datos: {json.dumps( detalles, indent=2)}")

            if not lista_datos or usa_paginacion == False:
                break

            skip += top

        # 🏭 Procesar datos
        if detalles:
            resultados = procesar_datos(
                detalles,  # 👈 lista completa
                mapeo_lista,
                doctype_target,
                empresa.company,
                debug_messages
            )
            processing_complete = True
            processing_failures = 0
            if isinstance(resultados, dict) and "processed" in resultados:
                total_procesados = int(resultados.get("processed") or 0)
                processing_failures = int(resultados.get("failed") or 0)
                processing_complete = bool(resultados.get("complete", processing_failures == 0))
            else:
                # Contrato heredado: conservarlo hasta migrar cada procesador.
                total_procesados = len(resultados)

            if fila_id and processing_complete:
                frappe.db.set_value("Campos Delta Load", fila_id, "date_time", hora_exacta)
                frappe.db.commit()
                print(f"se actualizo la hora {hora_exacta}")
            elif not processing_complete:
                raise RuntimeError(
                    f"Procesamiento incompleto ({processing_failures} errores); "
                    "no se avanzó el delta."
                )
            elif not fila_id:
                debug_messages.append("⚠ No hay datos para procesar")

    except Exception as e:
        sync_failed = True
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
        if not sync_failed:
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
        "status": "error" if sync_failed else ("success" if total_procesados > 0 else "warning"),
        "debug": debug_messages
    }
