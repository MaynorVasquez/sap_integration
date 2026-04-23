import frappe
from frappe import _
import traceback  # Importación añadida
import json
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
                                key_sap,
                                key_erpnext,
                                usa_paginacion=True):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    try:
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
        print(f"✔ Mapeo de campos exitoso : {json.dumps(mapeo_lista, indent=2)}")

        # 🔁 PAGINACIÓN (tu código actual)
        top = 20
        page, skip = 1, 0

        while True:
            url_final = construir_url_sap(mapeo_lista, empresa.company, empresa.endpoint, usa_paginacion, top=top, skip=skip)
            
            print(f"✔ URL: {url_final}")
            response = session.get(url_final)
            response.raise_for_status()
            print(f"Respuesta servidor: {response}")

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