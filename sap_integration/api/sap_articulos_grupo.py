import frappe
from frappe import _
import requests
import json
import traceback  # Importación añadida
from .blueprint import mapping_blueprint, mapping_blueprint1,construir_url_sap
from .sap_auth import login_sap 
from .logs import log_sincronizacion

@frappe.whitelist()
def sincronizar_articulos_grupo(docname=None):
    config = frappe.get_doc("Mapeo Articulos Grupo SAP", docname)

    resultados = []

    for empresa in config.company_detalle:
        resultado = procesar_empresa_individual(config, empresa,docname)

        resultados.append({
            "company": empresa.company,
            "endpoint": empresa.endpoint,
            "resultado": resultado
        })

    return resultados


@frappe.whitelist()
def procesar_empresa_individual(config, empresa,docname):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    doctype_logs = "Sincronizacion Articulos Grupo SAP"
    doctype_target = "Item Group"

    try:
        debug_messages.append(f"🚀 Procesando empresa: {empresa.company}")

        # 🔐 Login por empresa
        session = login_sap(empresa.company)

        if not session:
            raise Exception(f"No se pudo iniciar sesión para {empresa.company}")
        debug_messages.append("✔ Autenticación exitosa")

        #2. Obtener mapeo
        mapeo_lista = mapping_blueprint1(
            "Mapeo Articulos Grupo SAP", 
            "Number", 
            "custom_number"
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
        dato_existente = frappe.db.sql("""
            SELECT ig.name
            FROM `tabItem Group` ig
            INNER JOIN `tabItem Default` igd
                ON ig.name = igd.parent
            WHERE ig.{erp_key_field} = %s
            AND igd.company = %s
            LIMIT 1
        """.format(erp_key_field=erp_key_field), (sap_id, company), as_dict=True)
        # ✅ Ahora se utiliza el head 
        campos = mapeo_lista.get("sap_fields", {}).get("head", {})

        # Mapear datos SAP -> ERPNext
        dato_lista = {}
        company_abbr = frappe.get_value("Company", company, "abbr")
        for erp_field, sap_field in campos.items():
            valor = lista_mapeo.get(sap_field)

            if erp_field == "Inactive":
                valor = 1 if valor == "tYES" else 0
            
            if erp_field == "item_group_name":
                valor = f"{company_abbr} - {valor}"

            dato_lista[erp_field] = valor

        # Asegurar que el campo clave esté presente
        dato_lista[erp_key_field] = sap_id

        if dato_existente:
            # Actualizar documento existente
            doc = frappe.get_doc(doctype, dato_existente[0].name)
            for campo, valor in dato_lista.items():
                debug_messages.append(f"Update --> campo: {campo} --- valor: {valor}")
                setattr(doc, campo, valor)
            doc.flags.ignore_permissions = True  
            doc.save()
            frappe.db.commit()
            return f"{sap_id} (actualizado)", dato_lista
        else:
            # Crear nuevo documento
            doc = frappe.new_doc(doctype)
            for campo, valor in dato_lista.items():
                debug_messages.append(f"insert --> campo: {campo} --- valor: {valor}")
                setattr(doc, campo, valor)
            
            # agregar empresa en child table
            warehouse = frappe.get_value(
                "Warehouse",
                {"company": company, "is_group": 0},
                "name"
            )

            if warehouse:
                doc.append("item_group_defaults", {
                    "company": company,
                    "default_warehouse": warehouse
                })
            doc.flags.ignore_permissions = True 
            doc.insert()
            frappe.db.commit()  # ✅ commit después de insertar
            return f"{sap_id} (creado)", dato_lista

    except Exception as e:
        frappe.log_error(f"Error al procesar datos {sap_id}: ")
        return None, None

