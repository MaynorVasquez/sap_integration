import frappe
from frappe import _
import json
import traceback  # Importación añadida
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual

@frappe.whitelist()

def sincronizar_lista_precio(docname=None):
    doctype_logs = "Sincronizacion Lista Precios SAP"
    doctype_target =  "Price List"
    doctype_mapeo = "Mapeo Lista De Precios SAP"
    key_sap = "PriceListNo"
    key_erpnext = "custom_pricelistno"

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
    sap_key_field = mapeo_lista["key_field"]          # Ej: "KeySAP"
    erp_key_field = mapeo_lista["erp_key_field"]      # Ej: "custom_ERPNEXT"
    for lista_mapeo in registros_sap:
        try:
            sap_id = lista_mapeo.get(sap_key_field)            

            if not sap_id:
                frappe.log_error("Dato sin código", json.dumps(lista_mapeo, indent=2))
                return None, None  # No se puede continuar sin ID

            # Buscar datos ERPNEXT
            dato_existente = frappe.get_all(
                doctype,
                filters={
                    erp_key_field: sap_id,
                    "custom_company": company
                },
                limit=1
            )
            print(f"El Valor encontrado es: {dato_existente}")

            # ✅ Ahora se utiliza el head 
            campos = mapeo_lista.get("sap_fields", {}).get("head", {})

            # Mapear datos SAP -> ERP
            dato_lista = {}
            nuevo_nombre = None
            company_abbr = frappe.get_value("Company", company, "abbr")
            for erp_field, sap_field in campos.items():
                valor = lista_mapeo.get(sap_field)

                # Corrección de moneda
                if erp_field == "currency" and valor == "QTZ":
                    valor = "GTQ"

                elif erp_field == "enabled":
                    valor = 1 if valor == "tYES" else 0
                
                elif erp_field == "price_list_name":
                    valor = f"{company_abbr} - {valor}"
                
                elif erp_field == "name":
                    nuevo_nombre = f"{company_abbr} - {valor}"
                    print(f"nombre compuesto a utilizar: {nuevo_nombre}")
                    continue

                dato_lista[erp_field] = valor
            
            
            # Asegurar que el campo clave esté presente
            dato_lista[erp_key_field] = sap_id
            dato_lista.setdefault("selling", 1)
            dato_lista.setdefault("buying", 1)
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
                        doc = frappe.get_doc(doctype, nuevo_nombre)
                
                doc.flags.ignore_permissions = True 
                doc.save()
                frappe.db.commit()
            else:
                doc_data = {
                    "doctype": doctype,
                    **dato_lista,
                    "item_group_defaults": []
                }
                if nuevo_nombre:
                    doc_data["price_list_name"] = nuevo_nombre
                
                print(f"Insert -->{nuevo_nombre}")
                doc = frappe.get_doc(doc_data)

                doc.flags.ignore_permissions = True 
                doc.insert()
                frappe.db.commit()
        except Exception as e:
            frappe.log_error(f"Error al procesar lista de precios {sap_id}: {str(e)}\n{traceback.format_exc()}")
            return None, None
    return None, None
    

def asignar_lista_precios_por_codigo_sap(datos_doc, listnum_sap, campo_destino="default_price_list", reintento=True):
    """
    Asigna el 'name' del Price List (buscado por custom_pricelistno=listnum_sap)
    al campo especificado en datos_doc (por defecto 'default_price_list').

    Si la lista no existe y reintento=True, intenta sincronizar desde SAP y reintenta la asignación.
    """
    if not listnum_sap or str(listnum_sap) == "-1":
        # Nada que asignar, o explícitamente no tiene lista de precios en SAP
        return False

    price_list_name = frappe.db.get_value("Price List", {"custom_pricelistno": listnum_sap}, "name")

    if price_list_name:
        datos_doc[campo_destino] = price_list_name
        return True
    elif reintento:
        # Intentar sincronizar listas de precios
        sincronizar_lista_precio()

        # Reintentar una vez sin permitir recursión infinita
        return asignar_lista_precios_por_codigo_sap(datos_doc, listnum_sap, campo_destino, reintento=False)
    else:
        frappe.logger().info(f"No se encontró Price List con custom_pricelistno = {listnum_sap} tras reintento")
        return False



