import frappe
from frappe import _
import json
import traceback  # Importación añadida
from datetime import datetime
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual

@frappe.whitelist()

def sincronizar_clientes_desde_sap(docname=None):
    doctype_logs = "Sincronizacion clientes SAP"
    doctype_target =  "Customer"
    doctype_mapeo = "Mapeo Cliente"
    key_erpnext = "custom_cardcode"
    key_sap = "CardCode"

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

def procesar_datos(registro_sap, mapeo_lista, doctype, company,debug_messages):
    try:
        sap_key_field = mapeo_lista["key_field"]  
        erp_key_field = mapeo_lista["erp_key_field"]     
        sap_id = registro_sap.get(sap_key_field)
        SalesPersonCode = registro_sap.get("SalesPersonCode")
        codigo_grupo_cliente = registro_sap.get("GroupCode")
        PriceListNum = registro_sap.get("PriceListNum")
        CardType = registro_sap.get("CardType")
        doctype_synctracker = "SAP Sync Tracker Customer"
        doctype_syncrecord = "SAP Sync Record Customer"

        print(f"valor del cardtype: {CardType}")
        if CardType == "cSupplier":
            doctype = "Supplier"
        
        print(f"Ahora el doctype es: {doctype}")

        # Obtener campos de fecha y hora de actualización o creación
        update_date = registro_sap.get("UpdateDate").split("T")[0]
        update_time = registro_sap.get("UpdateTime")
        # # Si no hay fecha/hora de actualización, usar fecha/hora de creación
        if not update_date or not update_time:
            update_date = registro_sap.get("CreateDate").split("T")[0]
            update_time = registro_sap.get("CreateTime")
        
        # # Convertir a datetime
        update_str = f"{update_date} {update_time}"
        try:
            update_datetime = datetime.strptime(update_str, "%Y-%m-%d %H:%M:%S")
        except Exception as e:
            frappe.log_error("Error al convertir datetime", f"{update_str}\n{traceback.format_exc()}")
            return None, "Error al convertir la fecha de actualización"
        print(f"valor erp_key_field: {erp_key_field}")

        dato_existente = frappe.get_all(
            doctype,
            filters={
                erp_key_field: sap_id,
                "custom_company": company
            },
            limit=1
        )

        print(f"Cliente encontrado: {dato_existente}")

        #buscar vendedor asignado
        dato_vendedor = frappe.get_value(
            "Sales Person",
            filters={
                "custom_salesemployeecode": SalesPersonCode,
                "custom_company": company
            },
            fieldname="name"
        )
        print(f"Vendedor encontrado {dato_vendedor}")

        #buscar lista de precio
        dato_lista_precio = frappe.get_value(
            "Price List",
            filters={
                "custom_pricelistno": PriceListNum,
                "custom_company": company
            },
            fieldname="name"
        )
        print(f"Lista de precios: {dato_lista_precio}")

        #buscar grupo cliente
        dato_grupo_cliente = frappe.db.sql("""
            SELECT cg.name
            FROM `tabCustomer Group` cg
            INNER JOIN `tabParty Account` pa
                ON cg.name = pa.parent
            WHERE cg.custom_code = %s
            AND pa.company = %s
            LIMIT 1
        """, (codigo_grupo_cliente, company), as_list=True)
        grupo_cliente = dato_grupo_cliente[0][0] if dato_grupo_cliente else None
        print(f"Grupo de cliente: {grupo_cliente}")
        # 1. Obtener datos básicos
        campos = mapeo_lista.get("sap_fields", {}).get("head", {})
        dato_lista = {}

        # 2. Mapear campos y preparar el nombre
        for erp_field, sap_field in campos.items():
            valor = registro_sap.get(sap_field)

            if erp_field == "disabled":
                valor = 0 if valor == "tYES" else 1
            if erp_field == "customer_group":
                valor = grupo_cliente
            if erp_field == "default_price_list":
                valor = dato_lista_precio
            
            dato_lista[erp_field] = valor

        dato_lista["custom_company"] = company
        
        #print(f"✔ Mapeo de campos exitoso : {json.dumps(dato_lista, indent=2)}")

        if dato_existente:
            doc = frappe.get_doc(doctype, dato_existente[0].name)
            for campo, valor in dato_lista.items():
                    doc.set(campo, valor)
            
            if dato_vendedor:
                existe = False

                for row in doc.sales_team:
                    if row.sales_person == dato_vendedor:
                        existe = True
                        break

                if not existe:
                    total_actual = sum([row.allocated_percentage for row in doc.sales_team])

                    restante = 100 - total_actual

                    # Evita negativos por seguridad
                    if restante < 0:
                        restante = 0

                    doc.append("sales_team", {
                        "sales_person": dato_vendedor,
                        "allocated_percentage": restante
                    })

            doc.flags.ignore_permissions = True 
            doc.save()
            frappe.db.commit()
            procesar_direcciones(registro_sap,mapeo_lista, doctype, company,debug_messages)
            return f"{sap_id} (actualizado)", dato_lista
        else:
            doc_data = {
                "doctype": doctype,
                **dato_lista,
                "sales_team": []
            }

            if dato_vendedor:
                doc_data["sales_team"].append({
                    "sales_person": dato_vendedor,
                    "allocated_percentage": 100
                })
            #print(f"✔ Mapeo de campos a insertar : {json.dumps(doc_data, indent=2)}")
            doc = frappe.get_doc(doc_data)
            doc.flags.ignore_permissions = True 
            doc.insert()
            frappe.db.commit()
            procesar_direcciones(registro_sap,mapeo_lista,doctype,company, debug_messages)
            return f"{sap_id} (actualizado)", dato_lista
    except Exception as e:
        frappe.log_error(
            title=f"Error al procesar dato {sap_id}: {str(e)}" 
        )
        return None, None

def procesar_direcciones(registro_sap, mapeo_lista, doctype,company, debug_messages):

    billto_default = registro_sap.get("BilltoDefault")
    shipto_default = registro_sap.get("ShipToDefault")
    bp_addresses = registro_sap.get("BPAddresses")
    cardcode = registro_sap.get("CardCode")

    print(f"Direción de facturación: {billto_default}")
    print(f"Dirección de entrega: {shipto_default}")

    if not bp_addresses:
        print("Cliente sin direcciones en SAP.")
        return []
    
    card_code = frappe.get_value(
        doctype,
        filters={            
            "custom_cardcode": cardcode,
            "custom_company": company
        },
        fieldname="name"
    )
    print(f"se busca el name del cliente: {card_code}")

    campos = mapeo_lista.get("sap_fields", {}).get("DocumentLines", {})

    country_map = {
        "NI": "Nicaragua",
        "GT": "Guatemala"
    }

    direcciones_procesadas = []

    for direccion in bp_addresses:
        try:
            dato_lista = {}

            for erp_field, sap_field in campos.items():
                valor = direccion.get(sap_field)  # ✅ ahora sí correcto

                # ejemplo de transformación
                if sap_field == "Country":
                    valor = country_map.get(valor, valor)

                dato_lista[erp_field] = valor

            dato_lista["is_primary_address"] = 0
            dato_lista["is_shipping_address"] = 0

            address_name = direccion.get("AddressName")
            address_type = direccion.get("AddressType")

            if address_name == billto_default:
                dato_lista["is_primary_address"] = 1

            if address_name == shipto_default:
                dato_lista["is_shipping_address"] = 1
            
            if address_type == "bo_ShipTo":
                dato_lista["address_type"] = "Shipping"
            else: 
                dato_lista["address_type"] = "Billing"
            
            dato_lista["links"] = [
                {
                    "link_doctype": doctype,
                    "link_name": card_code # o el name real en ERPNext
                }
            ]            
            dato_existente = frappe.get_all(
                "Address",
                filters={
                    "address_title": address_name,
                    "address_type":  dato_lista["address_type"],
                    "custom_cardcode": cardcode
                },
                limit=1
            )
            if not dato_existente:
                dato_existente = frappe.get_all(
                    "Address",
                    filters={
                        "custom_rownum": dato_lista["custom_rownum"],
                        "address_type": dato_lista["address_type"],
                        "custom_cardcode": cardcode
                    },
                    limit=1
                )

            print(f"Datos encontrados: {dato_existente}")
            #print(f"✔ Mapeo de campos : {json.dumps(dato_lista, indent=2)}")
            if dato_existente:
                doc = frappe.get_doc("Address", dato_existente[0].name)
                print(f"actualizar {cardcode} --- {address_name}")
                for campo, valor in dato_lista.items():
                    if campo != "links": 
                        doc.set(campo, valor)
                doc.flags.ignore_permissions = True
                doc.save()
                frappe.db.commit()
            else:
                doc_data = {
                    "doctype": "Address",
                    **dato_lista
                }
                print(f"Insert:  {cardcode} --- {address_name}")
                doc = frappe.get_doc(doc_data)
                doc.flags.ignore_permissions = True 
                doc.insert()
                frappe.db.commit()

            direcciones_procesadas.append(dato_lista)
        except Exception as e:
            error_msg = f"Error en dirección {direccion.get('AddressName')} ({cardcode}): {str(e)}"
            frappe.log_error(
                message=error_msg,
                title="Error Sync Direcciones"
            )
            debug_messages.append(error_msg)
            continue
    return direcciones_procesadas