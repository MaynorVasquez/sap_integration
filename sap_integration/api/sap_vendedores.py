import frappe
from frappe import _
import json
import traceback  # Importación añadida
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual


@frappe.whitelist()

def sincronizar_lista_vendedores(docname=None):
    doctype_logs = "Sincronizacion person sales SAP"
    doctype_target =  "Sales Person"
    doctype_mapeo = "Mapeo Vendedores SAP"
    key_erpnext = "custom_salesemployeecode"
    key_sap = "SalesEmployeeCode"

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
                frappe.log_error("Vendedor sin código", json.dumps(lista_mapeo, indent=2))
                return None  # No se puede continuar sin ID
            debug_messages.append(f"SAP ID : {sap_id}")

            #vendedor_existente = frappe.get_all(doctype, filters={erp_key_field: sap_id}, limit=1)
            # Buscar datos ERPNEXT
            dato_existente = frappe.get_all(
                doctype,
                filters={
                    erp_key_field: sap_id,
                    "custom_company": company
                },
                limit=1
            )
            debug_messages.append(f"Vendedor encontrado : {dato_existente}")

            # ✅ Ahora se utiliza el head 
            campos = mapeo_lista.get("sap_fields", {}).get("head", {})

            # Mapear datos SAP -> ERP
            dato_lista = {}
            nuevo_nombre = None
            company_abbr = frappe.get_value("Company", company, "abbr")

            for erp_field, sap_field in campos.items():
                valor = lista_mapeo.get(sap_field)
                if erp_field == "enabled":
                    valor = 1 if valor == "tYES" else 0
                
                if erp_field == "sales_person_name":
                    valor = f"{company_abbr} - {valor}"

                if erp_field == "name":
                    nuevo_nombre = f"{company_abbr} - {valor}"
                    continue

                dato_lista[erp_field] = valor

            
            # Asegurar que el campo clave esté presente
            dato_lista[erp_key_field] = sap_id
            dato_lista["custom_company"] = company
    
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
                doc_data = {
                    "doctype": doctype,
                    **dato_lista
                }
                if nuevo_nombre:
                    doc_data["sales_person_name"] = nuevo_nombre

                print(f"Insert -->{nuevo_nombre}")
                
                doc = frappe.get_doc(doc_data)

                doc.flags.ignore_permissions = True 
                doc.insert()
                frappe.db.commit()
        except Exception as e:
            frappe.log_error(f"Error al procesar lista vendedor {sap_id}: {str(e)}\n{traceback.format_exc()}")
            return None
    return None, None

# @frappe.whitelist()
# def asignar_vendedor_por_codigo_sap(datos_doc, sales_employee_code, campo_destino="sales_person", reintento=True):
#     """
#     Asigna el 'name' del Sales Person (buscado por custom_salesemployeecode=sales_employee_code)
#     al campo especificado en datos_doc (por defecto 'sales_person').

#     Si el vendedor no existe y reintento=True, intenta sincronizar desde SAP y reintenta la asignación.
#     """
#     if not sales_employee_code or str(sales_employee_code) == "-1":
#         return False  # Nada que asignar

#     vendedor_name = frappe.db.get_value("Sales Person", {"custom_salesemployeecode": sales_employee_code}, "name")

#     if vendedor_name:
#         datos_doc[campo_destino] = vendedor_name
#         return True
#     elif reintento:
#         sincronizar_lista_vendedores()  # Asegúrate de que esta función está disponible
#         return asignar_vendedor_por_codigo_sap(datos_doc, sales_employee_code, campo_destino, reintento=False)
#     else:
#         frappe.logger().info(f"No se encontró Sales Person con custom_salesemployeecode = {sales_employee_code} tras reintento")
#         return False
