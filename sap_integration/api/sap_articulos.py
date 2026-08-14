import frappe
from frappe import _
import json
import traceback  # Importación añadida
from datetime import datetime
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual
from sap_integration.api.sap_lista_precio import sincronizar_lista_precio
# from sap_integration.api.last_update import sync_tracker, sync_tracker_update


@frappe.whitelist()

def sincronizar_lista_articulos(docname=None):
    doctype_logs = "Sincronizacion Articulos SAP"
    doctype_target =  "Item"
    doctype_mapeo = "Mapeo Articulo SAP"
    key_erpnext = "custom_itemcode"
    key_sap = "ItemCode"
    campos_delta = {
        "create_date": "CreateDate", # Nombre del campo en SAP para fecha de creación
        "create_time": "CreateTime",      # Nombre del campo en SAP para hora de creación
        "update_date": "UpdateDate",   # Nombre del campo en SAP para fecha de actualización
        "update_time": "UpdateTime"    # Nombre del campo en SAP para hora de actualización
    }

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
                                                key_erpnext,
                                                campos_delta = campos_delta
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
            doctype_synctracker = "SAP Sync Tracker Items"
            doctype_syncrecord = "SAP Sync Record Items"
            
            # Obtener campos de fecha y hora de actualización o creación
            update_date = lista_mapeo.get("UpdateDate").split("T")[0]
            update_time = lista_mapeo.get("UpdateTime")
            # # Si no hay fecha/hora de actualización, usar fecha/hora de creación
            if not update_date or not update_time:
                update_date = lista_mapeo.get("CreateDate").split("T")[0]
                update_time = lista_mapeo.get("CreateTime")
            
            # # Convertir a datetime
            update_str = f"{update_date} {update_time}"
            try:
                update_datetime = datetime.strptime(update_str, "%Y-%m-%d %H:%M:%S")
            except Exception as e:
                frappe.log_error("Error al convertir datetime", f"{update_str}\n{traceback.format_exc()}")
                return None, "Error al convertir la fecha de actualización"
            print(f"valor erp_key_field: {erp_key_field}")
            dato_existente = frappe.db.sql("""
                SELECT T0.name
                FROM `tabItem` T0
                INNER JOIN `tabItem Default` T1
                    ON T0.name = T1.parent
                WHERE T0.{erp_key_field} = %s
                AND T1.company = %s
                LIMIT 1
            """.format(erp_key_field=erp_key_field), (sap_id, company), as_dict=True)
            
            codigo_grupo_articulo = lista_mapeo.get("ItemsGroupCode")
            grupo_articulo = frappe.db.sql("""
                SELECT ig.item_group_name
                FROM `tabItem Group` ig
                INNER JOIN `tabItem Default` igd
                    ON ig.name = igd.parent
                WHERE ig.custom_number = %s
                AND igd.company = %s
                LIMIT 1
            """, (codigo_grupo_articulo, company), as_list=True)
            grupo_articulo = grupo_articulo[0][0] if grupo_articulo else None
            
            InventoryUoMEntry = lista_mapeo.get("InventoryUoMEntry")
            InventoryUoMEntry_uom = frappe.get_value(
                "UOM",
                filters={"custom_absentry": InventoryUoMEntry, "custom_company": company},
                fieldname="name"
            )

            DefaultPurchasingUoMEntry = lista_mapeo.get("DefaultPurchasingUoMEntry")
            DefaultPurchasingUoMEntry_uom = frappe.get_value(
                "UOM",
                filters={"custom_absentry": DefaultPurchasingUoMEntry, "custom_company": company},
                fieldname="name"
            )

            DefaultSalesUoMEntry = lista_mapeo.get("DefaultSalesUoMEntry")
            DefaultSalesUoMEntry_uom = frappe.get_value(
                "UOM",
                filters={"custom_absentry": DefaultSalesUoMEntry, "custom_company": company},
                fieldname="name"
            )

            # 1. Obtener datos básicos
            campos = mapeo_lista.get("sap_fields", {}).get("head", {})
            company_abbr = frappe.get_value("Company", company, "abbr")

            dato_lista = {}
            nuevo_nombre = None

            # 2. Mapear campos y preparar el nombre
            for erp_field, sap_field in campos.items():
                valor = lista_mapeo.get(sap_field)

                if erp_field == "disabled":
                    if valor == "tYES":
                        valor = 0
                    elif valor == "tNO":
                        valor = 1
                elif erp_field == "has_batch_no":
                    if valor == "tYES":
                        valor = 1
                    else:
                        valor = 0
                elif erp_field == "item_group":
                    valor = grupo_articulo

                elif erp_field == "stock_uom":
                    valor = InventoryUoMEntry_uom
                elif erp_field == "weight_uom":
                    valor = InventoryUoMEntry_uom
                elif erp_field == "purchase_uom":
                    valor = DefaultPurchasingUoMEntry_uom
                elif erp_field == "sales_uom":
                    valor = DefaultSalesUoMEntry_uom

                elif erp_field == "item_code":
                    valor = f"{company_abbr} - {valor}"

                elif erp_field == "name":
                    nuevo_nombre = f"{company_abbr} - {valor}"
                    continue

                dato_lista[erp_field] = valor
            warehouse = frappe.get_value(
                "Warehouse",
                {"company": company, "is_group": 0},
                "name"
            )
            print(f"El Valor encontrado es: {dato_existente}")
            if dato_existente:
                # itemcode_erpnext = dato_existente[0]["name"]            
                # data_synctracker = sync_tracker(doctype_synctracker,doctype_syncrecord,itemcode_erpnext, company)
                # success = data_synctracker.get("success", False)
                # if not success:
                #     print(f"no existe en la tabla, se actualiza los valores")
                # else:
                #     data = data_synctracker.get("data") or {}
                #     code = data.get("code")
                #     last_sync = data.get("last_sync")

                #     if last_sync:
                #         last_sync = datetime.strptime(last_sync, "%Y-%m-%d %H:%M:%S")

                #         if update_datetime <= last_sync:
                #             print(f"Code: {code} ---- last_sync: {last_sync} Sin Cambios")
                #             continue                       

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
                # sync_tracker_update(doctype_synctracker, nuevo_nombre, company,update_datetime)
                sincronizar_uoms(doc, lista_mapeo, company)
                sincronizar_articulo_precio(nuevo_nombre, lista_mapeo, company)
            else:
                # Crear nuevo documento
                doc_data = {
                    "doctype": doctype,
                    **dato_lista,
                    "item_defaults": []
                }
                if nuevo_nombre:
                    doc_data["item_code"] = nuevo_nombre

                if warehouse:
                    doc_data["item_defaults"].append({
                        "company": company,
                        "default_warehouse": warehouse
                    })

                print(f"Insert -->{nuevo_nombre}")
                doc = frappe.get_doc(doc_data)
                doc.flags.ignore_permissions = True 
                doc.insert()
                frappe.db.commit()
                # sync_tracker_update(doctype_synctracker, nuevo_nombre, company,update_datetime)        
        except Exception as e:
            frappe.log_error(
                title=f"Error al procesar dato {sap_id}: {str(e)}" 
            )
            debug_messages.append(f"Error en {sap_id}: {str(e)}")
            continue
    return None, None

def sincronizar_uoms(item_doc, lista_mapeo, company):
    try:
        # 1. Extraer todos los UoMPrices de forma plana y eficiente
        uom_prices_raw = [
            uom for price in lista_mapeo.get("ItemPrices", []) 
            for uom in price.get("UoMPrices", []) 
            if uom.get("UoMEntry")
        ]

        if not uom_prices_raw:
            return

        # 2. OPTIMIZACIÓN SQL: Buscar todos los UOMs de una sola vez
        uom_ids = [u.get("UoMEntry") for u in uom_prices_raw]
        
        uoms_erp_data = frappe.get_all("UOM", 
            filters={
                "custom_absentry": ["in", uom_ids],
                "custom_company": company
            }, 
            fields=["name", "custom_absentry"]
        )
        
        # Crear mapa de búsqueda rápida {absentry: name_erp}
        uom_map = {d.custom_absentry: d.name for d in uoms_erp_data}

        # 3. Preparar set de UOMs ya existentes en el ítem para evitar duplicados
        uoms_actuales = {row.uom for row in item_doc.uoms}
        hay_cambios = False

        for uom_price in uom_prices_raw:
            abs_entry = uom_price.get("UoMEntry")
            uom_name_erp = uom_map.get(abs_entry)

            if uom_name_erp and uom_name_erp not in uoms_actuales:
                item_doc.append("uoms", {
                    "uom": uom_name_erp,
                    "conversion_factor": float(uom_price.get("Factor", 1.0)) or 1.0
                })
                uoms_actuales.add(uom_name_erp) # Evitar duplicados si SAP envía la misma UOM dos veces
                hay_cambios = True

        # Solo guardamos si realmente agregamos algo
        if hay_cambios:
            item_doc.flags.ignore_permissions = True 
            item_doc.save()
            frappe.db.commit()

    except Exception as e:
        frappe.log_error(f"Error sincronizando UOMs para {item_doc.name}: {str(e)}")


def sincronizar_articulo_precio(item_code, lista_mapeo, company):

    try:
        if not item_code:
            frappe.log_error("Item code vacío al sincronizar precios")
            return

        # Validar que el item exista
        if not frappe.db.exists("Item", item_code):
            frappe.log_error(f"Item no existe en ERPNext: {item_code}")
            return

        item_prices = lista_mapeo.get("ItemPrices", [])
        inv_uom_entry = lista_mapeo.get("InventoryUoMEntry")

        uom_por_defecto = frappe.get_value(
            "UOM",
            filters={"custom_absentry": inv_uom_entry, "custom_company": company},
            fieldname="name"
        )

        for precio in item_prices:
            try:
                price_list_id = precio.get("PriceList")

                if price_list_id == -1:
                    continue

                price_list_name = frappe.get_value(
                    "Price List",
                    filters={
                        "custom_pricelistno": price_list_id,
                        "custom_company": company
                    },
                    fieldname="name"
                )

                if not price_list_name:
                    sincronizar_lista_precio()

                    price_list = frappe.get_all(
                        "Price List",
                        filters={"custom_sap_pricelist": price_list_id},
                        fields=["name"],
                        limit=1
                    )

                    if not price_list:
                        frappe.log_error(
                            f"Lista de precios SAP {price_list_id} no encontrada"
                        )
                        continue

                    price_list_name = price_list[0].name

                moneda = precio.get("Currency", "QTZ")
                precio_base = precio.get("Price")
                uom_prices = precio.get("UoMPrices", [])

                if moneda == "QTZ":
                    moneda = "GTQ"

                # Precio base
                if precio_base is not None and uom_por_defecto:
                    insertar_o_actualizar_item_price({
                        "item_code": item_code,
                        "price_list": price_list_name,
                        "price_list_rate": precio_base,
                        "uom": uom_por_defecto,
                        "currency": moneda
                    })

                # Precios por UOM
                for uom in uom_prices:
                    uom_entry = uom.get("UoMEntry")
                    precio_uom = uom.get("Price")
                    moneda_uom = uom.get("Currency", "QTZ")

                    if moneda_uom == "QTZ":
                        moneda_uom = "GTQ"

                    if uom_entry and precio_uom:
                        uom_doc = frappe.get_all(
                            "UOM",
                            filters={
                                "custom_absentry": uom_entry,
                                "custom_company": company
                            },
                            fields=["name"],
                            limit=1
                        )

                        if uom_doc:
                            insertar_o_actualizar_item_price({
                                "item_code": item_code,
                                "price_list": price_list_name,
                                "price_list_rate": precio_uom,
                                "uom": uom_doc[0].name,
                                "currency": moneda_uom
                            })

            except Exception as e:
                frappe.log_error(
                    f"Error procesando precio {precio.get('PriceList')} para item {item_code}: {str(e)}"
                )
                continue

    except Exception as e:
        frappe.log_error(
            f"Error general sincronizando precios para item {item_code}: {str(e)}"
        )
        

def insertar_o_actualizar_item_price(data):
    """Crea o actualiza un registro en Item Price con base en el código de artículo, lista de precios y UOM."""
    
    try:
        # 🔹 Validaciones básicas
        if not data.get("item_code") or not data.get("price_list"):
            frappe.log_error(f"Datos incompletos para Item Price: {data}")
            return

        # Validar que el item exista
        if not frappe.db.exists("Item", data["item_code"]):
            frappe.log_error(f"Item no existe al insertar precio: {data['item_code']}")
            return

        filtros = {
            "item_code": data["item_code"],
            "price_list": data["price_list"],
            "uom": data.get("uom")
        }

        item_price = frappe.get_all(
            "Item Price",
            filters=filtros,
            fields=["name"],
            limit=1
        )

        # 🔹 UPDATE
        if item_price:
            try:
                doc = frappe.get_doc("Item Price", item_price[0].name)
                doc.price_list_rate = data.get("price_list_rate")
                doc.currency = data.get("currency")

                doc.flags.ignore_permissions = True
                doc.save()
                frappe.db.commit()

            except Exception as e:
                frappe.log_error(
                    f"Error actualizando Item Price {item_price[0].name}: {str(e)}\nData: {data}"
                )

        # 🔹 INSERT
        else:
            try:
                doc = frappe.new_doc("Item Price")
                doc.flags.ignore_permissions = True
                doc.update(data)
                doc.insert()
                frappe.db.commit()

            except Exception as e:
                frappe.log_error(
                    f"Error insertando Item Price: {str(e)}\nData: {data}"
                )

    except Exception as e:
        frappe.log_error(
            f"Error general en insertar_o_actualizar_item_price: {str(e)}\nData: {data}"
        )     
