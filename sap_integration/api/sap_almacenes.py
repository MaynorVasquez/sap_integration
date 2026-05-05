import frappe
from frappe import _
import json
import traceback  # Importación añadida
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual


@frappe.whitelist()
def sincronizar_lista_alamacenes(docname=None):
    doctype_logs = "Sincronizacion Almacenes SAP"
    doctype_target =  "Warehouse"
    doctype_mapeo = "Mapeo Almacenes SAP"
    key_sap = "WarehouseCode"
    key_erpnext = "custom_warehousecode"
    

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

    sap_key_field = mapeo_lista["key_field"]
    erp_key_field = mapeo_lista["erp_key_field"]
    for lista_mapeo in registros_sap:
        try:            
            sap_id = lista_mapeo.get(sap_key_field)

            if not sap_id:
                frappe.log_error("Dato sin código", json.dumps(lista_mapeo, indent=2))
                return None, None

            dato_existente = frappe.get_all(
                doctype,
                filters={erp_key_field: sap_id, "company": company},
                limit=1
            )
            debug_messages.append(f"Dato encontrado : {dato_existente}")

            # ✅ Ahora se utiliza el head 
            campos = mapeo_lista.get("sap_fields", {}).get("head", {})

            dato_lista = {}
            nuevo_nombre = None
            company_abbr = frappe.get_value("Company", company, "abbr")

            for erp_field, sap_field in campos.items():
                valor = lista_mapeo.get(sap_field)

                if erp_field == "disabled":
                    valor = 1 if valor == "tYES" else 0
                
                elif erp_field == "name":
                    nuevo_nombre = f"{valor} - {company_abbr} "
                    continue

                dato_lista[erp_field] = valor

            dato_lista[erp_key_field] = sap_id
            dato_lista["company"] = company
            debug_messages.append(f"Lista de campos: {dato_lista}")

            if dato_existente:
                nombre_actual = dato_existente[0].name
                doc = frappe.get_doc(doctype, nombre_actual)
                
                for campo, valor in dato_lista.items():
                    doc.set(campo, valor)

                print(f"Update --> {nuevo_nombre}")
                
                doc.flags.ignore_permissions = True
                doc.save()
                if nuevo_nombre and doc.name != nuevo_nombre:
                    if not frappe.db.exists(doctype, nuevo_nombre):
                        frappe.rename_doc(doctype, doc.name, nuevo_nombre, force=True)

                frappe.db.commit()
                #return f"{sap_id} (actualizado)", dato_lista

            else:

                doc_data = {
                    "doctype": doctype,
                    **dato_lista
                }
                
                print(f"Insert -->{nuevo_nombre}")
                doc = frappe.get_doc(doc_data)

                doc.flags.ignore_permissions = True 
                doc.insert()
                frappe.db.commit()  # ✅ commit después de insertar
                #return f"{sap_id} (creado)", dato_lista

        except Exception as e:
            frappe.log_error(
                f"Error al procesar datos {sap_id}: {str(e)}\n{traceback.format_exc()}"
            )
            return None, None
    return None, None