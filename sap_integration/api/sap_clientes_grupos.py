import frappe
from frappe import _
# import requests
import json
import traceback  # Importación añadida
# from .logs import log_sincronizacion
# from .blueprint import mapping_blueprint1, construir_url_sap
# from .sap_auth import login_sap
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual

@frappe.whitelist()

def sincronizar_lista_clientes_grupos(docname=None):
    doctype_logs = "Sincronizacion Clientes Grupos SAP"
    doctype_target = "Customer Group"
    doctype_mapeo = "Mapeo Clientes Grupo SAP"
    key_erpnext = "Code"
    key_sap = "custom_code"

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
                                                key_erpnext,
                                                key_sap)

        resultados.append({
            "company": empresa.company,
            "endpoint": empresa.endpoint,
            "resultado": resultado
        })

    return resultados

def procesar_datos(lista_mapeo, mapeo_lista, doctype, company,debug_messages):

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
            SELECT cg.name
            FROM `tabCustomer Group` cg
            INNER JOIN `tabParty Account` pa
                ON cg.name = pa.parent
            WHERE cg.{erp_key_field} = %s
            AND pa.company = %s
            LIMIT 1
        """.format(erp_key_field=erp_key_field), (sap_id, company), as_dict=True)

        # ✅ Ahora se utiliza el head 
        campos = mapeo_lista.get("sap_fields", {}).get("head", {})
        # Mapear datos SAP -> ERPNext
        dato_lista = {}
        company_abbr = frappe.get_value("Company", company, "abbr")

        for erp_field, sap_field in campos.items():
            valor = lista_mapeo.get(sap_field)

            if erp_field == "customer_group_name":
                valor = f"{company_abbr} - {valor}"

            dato_lista[erp_field] = valor

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
            doc.append("accounts", {
                "company": company
            })
            # 👇 Esto ignora los permisos del usuario actual
            doc.flags.ignore_permissions = True 
            doc.insert()
            frappe.db.commit()  # ✅ commit después de insertar
            return f"{sap_id} (creado)", dato_lista

    except Exception as e:
        frappe.log_error(f"Error al procesar datos {sap_id}: {str(e)}\n{traceback.format_exc()}")
        return None, None