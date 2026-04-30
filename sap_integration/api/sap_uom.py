import frappe
from frappe import _
import json
import traceback  # Importación añadida
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual

@frappe.whitelist()

def sincronizar_uom(docname=None):
    doctype_logs = "Sincronizacion UOM"
    doctype_target =  "UOM"
    doctype_mapeo = "Mapeo UOM"
    key_sap = "AbsEntry"
    key_erpnext = "custom_absentry"

    config = frappe.get_doc(doctype_mapeo, docname)

    resultados = []

    for empresa in config.company_detalle:
        print(f"empresa: {empresa.company}")
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

def procesar_datos(registros_sap, mapeo_lista, doctype, company, debug_messages):
    sap_key_field = mapeo_lista["key_field"]
    erp_key_field = mapeo_lista["erp_key_field"]
    for lista_mapeo in registros_sap:
        try:
            sap_key_field = mapeo_lista["key_field"]
            erp_key_field = mapeo_lista["erp_key_field"]
            sap_id = lista_mapeo.get(sap_key_field)

            if not sap_id:
                frappe.log_error("Dato sin código", json.dumps(lista_mapeo, indent=2))
                return None, None

            # 1. Obtener datos básicos
            campos = mapeo_lista.get("sap_fields", {}).get("head", {})
            company_abbr = frappe.get_value("Company", company, "abbr")
            
            dato_lista = {}
            nuevo_nombre = None
            
            # 2. Mapear campos y preparar el nombre
            for erp_field, sap_field in campos.items():
                valor = lista_mapeo.get(sap_field)
                if erp_field == "name":
                    nuevo_nombre = f"{company_abbr} - {valor}"
                else:
                    dato_lista[erp_field] = valor

            # Asegurar campos obligatorios
            dato_lista[erp_key_field] = sap_id
            dato_lista["custom_company"] = company

            # 3. Buscar si ya existe
            dato_existente = frappe.get_all(
                doctype,
                filters={erp_key_field: sap_id, "custom_company": company},
                limit=1
            )

            if dato_existente:
                # --- ACTUALIZACIÓN ---
                nombre_actual = dato_existente[0].name
                doc = frappe.get_doc(doctype, nombre_actual)
                
                for campo, valor in dato_lista.items():
                    doc.set(campo, valor)

                print(f"Update --> {nuevo_nombre}")
                
                doc.flags.ignore_permissions = True
                doc.save()

                # Cambiar nombre si es necesario
                if nuevo_nombre and nombre_actual != nuevo_nombre:
                    if not frappe.db.exists(doctype, nuevo_nombre):
                        frappe.rename_doc(doctype, nombre_actual, nuevo_nombre, force=True)
                
                frappe.db.commit()
            else:
                doc_data = {
                    "doctype": doctype,
                    **dato_lista
                }
                
                if nuevo_nombre:
                    doc_data["uom_name"] = nuevo_nombre
                
                print(f"Insert -->{nuevo_nombre}")
                doc = frappe.get_doc(doc_data)
                
                doc.flags.ignore_permissions = True
                doc.insert()            
                frappe.db.commit()
        except Exception as e:
            frappe.log_error(f"Error al procesar datos {sap_id}: {str(e)}\n{traceback.format_exc()}")
            return None, None
    return None, None
