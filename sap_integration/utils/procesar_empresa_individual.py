import frappe
from frappe import _
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
        page, skip = 1, 0

        filtro_tiempo = construir_filtro_tiempo(ultima_sync, campos_delta)

        while True:
            url_base = construir_url_sap(mapeo_lista, empresa.company, empresa.endpoint, usa_paginacion, almacen, top=top, skip=skip)
            url_final = inyectar_filtro_a_url(url_base, filtro_tiempo)
            #url_final = construir_url_sap(mapeo_lista, empresa.company, empresa.endpoint, usa_paginacion, almacen, top=top, skip=skip)
            
            print(f"✔ URL: {url_final}")
            response = session.get(url_final)
            response.raise_for_status()
            #print(f"Respuesta servidor: {response}")

            data = response.json()
            lista_datos = data.get("value", [])
            #print(f"Datos: {json.dumps(data, indent=2)}")

            detalles.extend(lista_datos)
            #print(f"Datos: {json.dumps( detalles, indent=2)}")           

            if not lista_datos or usa_paginacion == False:
                break

            skip += top
            page += 1


        # 🏭 Procesar datos
        if detalles:
            resultados = procesar_datos(
                detalles,  # 👈 lista completa
                mapeo_lista,
                doctype_target,
                empresa.company,
                debug_messages
            )
            total_procesados = len(resultados)
        if fila_id:
            frappe.db.set_value("Campos Delta Load", fila_id, "date_time", hora_exacta)
            frappe.db.commit()
            print(f"se actualizo la hora {hora_exacta}")
        else:
            debug_messages.append("⚠ No hay datos para procesar")

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