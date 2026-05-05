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

def procesar_datos(registros_sap, mapeo_lista, doctype, company,debug_messages):
    sap_key_field = mapeo_lista["key_field"]
    erp_key_field = mapeo_lista["erp_key_field"]
    for lista_mapeo in registros_sap:
        try:
            sap_id = lista_mapeo.get(sap_key_field)

            if not sap_id:
                frappe.log_error("Dato sin código", json.dumps(lista_mapeo, indent=2))
                return None, None  # No se puede continuar sin ID
            
            # 1. Obtener datos básicos
            campos = mapeo_lista.get("sap_fields", {}).get("head", {})
            company_abbr = frappe.get_value("Company", company, "abbr")

            dato_lista = {}
            nuevo_nombre = None

            # 2. Mapear campos y preparar el nombre
            for erp_field, sap_field in campos.items():
                valor = lista_mapeo.get(sap_field)

                if erp_field == "customer_group_name":
                    valor = f"{company_abbr} - {valor}"
                
                elif erp_field == "name":
                    nuevo_nombre = f"{company_abbr} - {valor}"
                    continue

                dato_lista[erp_field] = valor

            # Asegurar que el campo clave esté presente
            dato_lista[erp_key_field] = sap_id

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
            print(f"Dato encontrado: {dato_existente}")

            if dato_existente:
                # Actualizar documento existente
                doc = frappe.get_doc(doctype, dato_existente[0].name)
                # Usamos doc.set para campos de la cabecera
                for campo, valor in dato_lista.items():
                    if campo != "name":
                        doc.set(campo, valor)

                print(f"Update --> {nuevo_nombre}")

                if nuevo_nombre and doc.name != nuevo_nombre:
                    if not frappe.db.exists(doctype, nuevo_nombre):
                        frappe.rename_doc(doctype, doc.name, nuevo_nombre, force=True)
                        doc = frappe.get_doc(doctype, nuevo_nombre)

                doc.flags.ignore_permissions = True 
                doc.save()
                frappe.db.commit()
            else:
                # Crear nuevo documento
                doc_data = {
                    "doctype": doctype,
                    **dato_lista,
                    "accounts": []
                }
                if nuevo_nombre:
                    doc_data["customer_group_name"] = nuevo_nombre

                doc_data["accounts"].append({
                    "company": company
                })

                print(f"Insert -->{nuevo_nombre}")
                doc = frappe.get_doc(doc_data)

                doc.flags.ignore_permissions = True 
                doc.insert()
                frappe.db.commit()

        except Exception as e:
            frappe.log_error(f"Error al procesar datos {sap_id}: {str(e)}\n{traceback.format_exc()}")
            return None, None
    return None, None