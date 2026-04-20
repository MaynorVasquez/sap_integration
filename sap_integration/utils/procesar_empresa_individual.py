import frappe
from frappe import _
import traceback  # Importación añadida
from sap_integration.api.logs import log_sincronizacion
from sap_integration.api.blueprint import mapping_blueprint1, construir_url_sap
from sap_integration.api.sap_auth import login_sap


def procesar_empresa_individual(config, 
                                empresa,
                                docname,
                                procesar_datos,
                                doctype_logs,
                                doctype_target,
                                doctype_mapeo,
                                key_erpnext,
                                key_sap):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    try:
        debug_messages.append(f"🚀 Procesando empresa: {empresa.company}")
        debug_messages.append(f"🚀 Procesando empresa Endpoint: {empresa.endpoint}")

        # 🔐 Login por empresa
        session = login_sap(empresa.company)

        if not session:
            raise Exception(f"No se pudo iniciar sesión para {empresa.company}")
        debug_messages.append("✔ Autenticación exitosa")

        #2. Obtener mapeo
        mapeo_lista = mapping_blueprint1(doctype_mapeo, key_erpnext, key_sap)
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos desde el blueprint")
        debug_messages.append(f"✔ Mapeo de campos exitoso : {mapeo_lista}")

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