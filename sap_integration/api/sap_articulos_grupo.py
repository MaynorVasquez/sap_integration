import frappe
from frappe import _
import json
import traceback  # Importación añadida
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual


@frappe.whitelist()
def sincronizar_articulos_grupo(docname=None):
    doctype_logs = "Sincronizacion Articulos Grupo SAP"
    doctype_target =  "Item Group"
    doctype_mapeo = "Mapeo Articulos Grupo SAP"
    key_sap = "Number"
    key_erpnext = "custom_number"

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
                                                key_sap,
                                                key_erpnext
                                                )

        resultados.append({
            "company": empresa.company,
            "endpoint": empresa.endpoint,
            "resultado": resultado
        })

    return resultados

def procesar_datos(registros_sap, mapeo_lista, doctype, company,debug_messages):
    """Crea o actualiza documentos en ERPNext de forma genérica"""
    sap_key_field = mapeo_lista["key_field"]
    erp_key_field = mapeo_lista["erp_key_field"]
    for lista_mapeo in registros_sap:
        try:
            sap_id = lista_mapeo.get(sap_key_field)
            if not sap_id:
                frappe.log_error("Dato sin código", json.dumps(lista_mapeo, indent=2))
                return None, None  # No se puede continuar sin ID           

            #Buscar documento existente en ERPNext
            dato_existente = frappe.db.sql("""
                SELECT ig.name
                FROM `tabItem Group` ig
                INNER JOIN `tabItem Default` igd
                    ON ig.name = igd.parent
                WHERE ig.{erp_key_field} = %s
                AND igd.company = %s
                LIMIT 1
            """.format(erp_key_field=erp_key_field), (sap_id, company), as_dict=True)
            #✅ Ahora se utiliza el head 

            print(f"Dato encontrado: {dato_existente}") 
            campos = mapeo_lista.get("sap_fields", {}).get("head", {})

            # Mapear datos SAP -> ERPNext
            dato_lista = {}
            nuevo_nombre = None
            company_abbr = frappe.get_value("Company", company, "abbr")

            for erp_field, sap_field in campos.items():
                valor = lista_mapeo.get(sap_field)

                if erp_field == "Inactive":
                    valor = 1 if valor == "tYES" else 0
                
                if erp_field == "item_group_name":
                    valor = f"{company_abbr} - {valor}"
                
                if erp_field == "name":
                    nuevo_nombre = f"{company_abbr} - {valor}"
                    continue

                dato_lista[erp_field] = valor

            # Asegurar que el campo clave esté presente
            dato_lista[erp_key_field] = sap_id

            warehouse = frappe.get_value(
                "Warehouse",
                {"company": company, "is_group": 0},
                "name"
            )

            if dato_existente:
                doc = frappe.get_doc(doctype, dato_existente[0].name)
        
                for campo, valor in dato_lista.items():
                    if campo != "name":
                        doc.set(campo, valor)

                print(f"Update --> {nuevo_nombre}")

                if nuevo_nombre and doc.name != nuevo_nombre:
                    if not frappe.db.exists(doctype, nuevo_nombre):
                        frappe.rename_doc(doctype, doc.name, nuevo_nombre, force=True)

                doc.flags.ignore_permissions = True  
                doc.save()
                frappe.db.commit()
            else:
                # Crear nuevo documento
                doc_data = {
                    "doctype": doctype,
                    **dato_lista,
                    "item_group_defaults": []
                }

                if nuevo_nombre:
                    doc_data["item_group_name"] = nuevo_nombre

                if warehouse:
                    doc_data["item_group_defaults"].append({
                        "company": company,
                        "default_warehouse": warehouse
                    })

                print(f"Insert -->{nuevo_nombre}")
                doc = frappe.get_doc(doc_data)

                doc.flags.ignore_permissions = True 
                doc.insert()
                frappe.db.commit()
        except Exception as e:
            frappe.log_error(f"Error al procesar datos {sap_id}: ")
            return None, None
    return None, None