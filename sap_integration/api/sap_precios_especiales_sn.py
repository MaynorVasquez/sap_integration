import frappe
from frappe import _
import json
import traceback  # Importación añadida
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual
from datetime import datetime, date
from pprint import pprint



@frappe.whitelist()
def sincronizar_precios_especiales_sn(docname=None):
    doctype_logs = "Sincronizacion Precios Especiales SN SAP"
    doctype_target =  "Pricing Rule"
    doctype_mapeo = "Mapeo Precios Especiales SN SAP"
    key_sap = "ItemCode"
    key_erpnext = "title"
    

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
            ItemCode_SAP = lista_mapeo.get("ItemCode")
            CardCode_SAP = lista_mapeo.get("CardCode")
            #campos = mapeo_lista.get("sap_fields", {}).get("head", {})
            titulo = f"{CardCode_SAP}-{ItemCode_SAP}"
            SpecialPriceDataAreas = lista_mapeo.get("SpecialPriceDataAreas", [])
            ItemCode_erpnext = frappe.db.sql("""
                SELECT T0.name
                FROM `tabItem` T0
                INNER JOIN `tabItem Default` T1
                    ON T0.name = T1.parent
                WHERE T0.custom_itemcode = %s
                AND T1.company = %s
                LIMIT 1
            """,(ItemCode_SAP, company), as_dict=True)
            #print(f"ItemCode_erpnext: {ItemCode_erpnext}--{ItemCode_SAP}")

            if not ItemCode_erpnext:
                #print(f"Código de articulo no encontrado: {ItemCode_SAP}--{company}")
                continue
            ItemCode_erpnext = ItemCode_erpnext[0]["name"]
            

            for SpecialPriceDataArea in SpecialPriceDataAreas:
                DateFrom = SpecialPriceDataArea.get("DateFrom")
                Dateto = SpecialPriceDataArea.get("Dateto")
                Discount = SpecialPriceDataArea.get("Discount")
                # Validar vigencia
                if not Dateto:
                    continue

                fecha_vencimiento = datetime.strptime(
                    Dateto,
                    "%Y-%m-%dT%H:%M:%SZ"
                ).date()
                

                if fecha_vencimiento < date.today():                    
                    continue

                print(f"Fecha de vencimiento: {fecha_vencimiento}")
                print(f"ItemCode_erpnext: {ItemCode_erpnext}")

                dato_existe = frappe.get_value(
                    doctype,
                    {
                        "title": titulo,
                        "company": company
                    },
                    "name"
                )
                cardcode_erpnext = frappe.get_value(
                    "Customer",
                    {
                        "custom_cardcode": CardCode_SAP,
                        "custom_company": company
                    },
                    "name"
                )
                if not cardcode_erpnext:
                    continue

                campos = mapeo_lista.get("sap_fields", {}).get("DocumentLines", {})
                dato_lista = {}
                for erp_field, sap_field in campos.items():
                    valor = SpecialPriceDataArea.get(sap_field)
                    if erp_field == "currency" and valor == "QTZ":
                        valor = "GTQ"
                    elif erp_field == "customer":
                        valor = cardcode_erpnext
                    elif erp_field == "item_code":
                        valor = ItemCode_erpnext
                    elif erp_field == "valid_upto":
                        valor = fecha_vencimiento
                    elif erp_field == "valid_from":
                        valor = datetime.strptime(
                            DateFrom,
                            "%Y-%m-%dT%H:%M:%SZ"
                        ).date()
                    dato_lista[erp_field] = valor
                
                dato_lista["company"] = company
                dato_lista["selling"] = 1
                dato_lista["title"] = titulo
                dato_lista["price_or_product_discount"] = "Price"
                dato_lista["apply_on"] =  "Item Code"
                dato_lista["applicable_for"] =  "Customer"
            
                if dato_existe:
                    # =====================
                    # ACTUALIZAR
                    # =====================
                    doc = frappe.get_doc(doctype, dato_existe)

                    for campo, valor in dato_lista.items():
                        doc.set(campo, valor)

                    # Validar la tabla hija Items
                    if len(doc.items) == 0:
                        doc.append("items", {
                            "item_code": ItemCode_erpnext
                        })
                    else:
                        doc.items[0].item_code = ItemCode_erpnext

                    doc.flags.ignore_permissions = True
                    doc.save()
                    frappe.db.commit()
                    print(f"Regla de precio especial actualizada: {titulo} para la empresa {company}")
                else: 
                    # =====================
                    # CREAR
                    # =====================
                    doc_data = {
                        "doctype": doctype,
                        **dato_lista,
                        "items": [
                            {
                                "item_code": ItemCode_erpnext
                            }
                        ]
                    }
                    doc = frappe.get_doc(doc_data)
                    doc.flags.ignore_permissions = True 
                    doc.insert()
                    frappe.db.commit()  # ✅ commit después de insertar
                    print(f"Regla de precio especial creada: {titulo} para la empresa {company}")

        except Exception as e:
            frappe.log_error(
                f"Error al procesar datos {ItemCode_SAP}: {str(e)}\n{traceback.format_exc()}"
            )
            return None, None
    return None, None 
