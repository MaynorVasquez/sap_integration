import frappe
from frappe import _
import json
import traceback  # Importación añadida
from datetime import datetime
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual
from sap_integration.api.sap_lista_precio import sincronizar_lista_precio


@frappe.whitelist()

def sincronizar_lista_articulos(docname=None):
    doctype_logs = "Sincronizacion Articulos SAP"
    doctype_target =  "Item"
    doctype_mapeo = "Mapeo Articulo SAP"
    key_erpnext = "custom_itemcode"
    key_sap = "ItemCode"

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
        
        # #Busca en la tabla de Syncs Traker a los articulos
        # syncs = obtener_filtro_ultima_sync("Sync Tracker", "Sync Record", "Articulos")
        # sync_records = syncs["data"] if syncs["success"] else {}
        
        # last_sync = sync_records.get(sap_id)
        # if last_sync:
        #     last_sync_dt = datetime.strptime(last_sync, "%Y-%m-%d %H:%M:%S")
        #     if update_datetime <= last_sync_dt:
        #         return None, "Articulo sin cambios"

        dato_existente = frappe.db.sql("""
            SELECT T0.name
            FROM `tabItem` T0
            INNER JOIN `tabItem Default` T1
                ON T0.name = T1.parent
            WHERE T0.{erp_key_field} = %s
            AND T1.company = %s
            LIMIT 1
        """.format(erp_key_field=erp_key_field), (sap_id, company), as_dict=True)
        
        codigo_grupo_articulo = registro_sap.get("ItemsGroupCode")
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
        
        InventoryUoMEntry = registro_sap.get("InventoryUoMEntry")
        InventoryUoMEntry_uom = frappe.get_value(
            "UOM",
            filters={"custom_absentry": InventoryUoMEntry, "custom_company": company},
            fieldname="name"
        )

        DefaultPurchasingUoMEntry = registro_sap.get("DefaultPurchasingUoMEntry")
        DefaultPurchasingUoMEntry_uom = frappe.get_value(
            "UOM",
            filters={"custom_absentry": DefaultPurchasingUoMEntry, "custom_company": company},
            fieldname="name"
        )

        DefaultSalesUoMEntry = registro_sap.get("DefaultSalesUoMEntry")
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
            valor = registro_sap.get(sap_field)

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
        #(f"Datos: {json.dumps( dato_lista, indent=2)}")

        item_prices = registro_sap.get("ItemPrices", [])
        

        if dato_existente:
            doc = frappe.get_doc(doctype, dato_existente[0].name)
            for campo, valor in dato_lista.items():
                if campo != "name":
                    doc.set(campo, valor)
            print(f"Update --> {nuevo_nombre}")

            sincronizar_uoms(doc, registro_sap, company)

            if nuevo_nombre and doc.name != nuevo_nombre:
                if not frappe.db.exists(doctype, nuevo_nombre):
                    frappe.rename_doc(doctype, doc.name, nuevo_nombre, force=True)

            doc.flags.ignore_permissions = True 
            doc.save()
            frappe.db.commit()

            sincronizar_articulo_precio(nuevo_nombre, registro_sap, company)
            return f"{sap_id} (actualizado)", dato_lista

        else:
            print("insert aun en dev *******")
    
    except Exception as e:
        frappe.log_error(f"Error al procesar lista vendedor {sap_id}: {str(e)}\n{traceback.format_exc()}")
        return None

def sincronizar_uoms(item_doc, registro_sap, company):
    try:
        # 1. Extraer todos los UoMPrices de forma plana y eficiente
        uom_prices_raw = [
            uom for price in registro_sap.get("ItemPrices", []) 
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

    except Exception as e:
        frappe.log_error(f"Error sincronizando UOMs para {item_doc.name}: {str(e)}")


def sincronizar_articulo_precio(item_code, registro_sap, company):

    item_prices = registro_sap.get("ItemPrices", [])
    # Obtener la unidad de medida por defecto desde InventoryUoMEntry
    inv_uom_entry = registro_sap.get("InventoryUoMEntry")

    uom_por_defecto = frappe.get_value(
                    "UOM", 
                    filters={"custom_absentry": inv_uom_entry,
                                "custom_company": company}, 
                    fieldname="name")

    for precio in item_prices:
        price_list_id = precio.get("PriceList")
        
        if price_list_id == -1:
            continue

        # Validar existencia de la lista de precios
        price_list_name = frappe.get_value(
                            "Price List", 
                            filters={"custom_pricelistno": price_list_id,
                                     "custom_company": company}, 
                            fieldname="name")
        
        if not price_list_name:
            # Si no existe, intenta sincronizar la lista de precios desde SAP
            sincronizar_lista_precio()  # función ya existente que creará las listas
            # Vuelve a verificar si ya existe
            price_list_name = frappe.get_all("Price List", filters={"custom_sap_pricelist": price_list_id}, fields=["name"], limit=1)
            if not price_list_name:
                frappe.log_error(f"Lista de precios SAP {price_list_id} no encontrada incluso después de sincronización.")
                continue  # Salta si aún no existe
        
        moneda = precio.get("Currency", "QTZ")
        precio_base = precio.get("Price")
        uom_prices = precio.get("UoMPrices", [])

        if moneda == "QTZ":
            moneda = "GTQ"
 
        # Precio base (UOM por defecto)
        if precio_base is not None and uom_por_defecto:
            insertar_o_actualizar_item_price({
                "item_code": item_code,
                "price_list": price_list_name,
                "price_list_rate": precio_base,
                "uom": uom_por_defecto,
                "currency": moneda
            })
        
        # Precios por UOM adicional
        for uom in uom_prices:
            uom_entry = uom.get("UoMEntry")
            precio_uom = uom.get("Price")
            moneda_uom = uom.get("Currency", "QTZ")

            if moneda_uom == "QTZ":
                moneda_uom = "GTQ"

            if uom_entry and precio_uom:
                uom_doc = frappe.get_all(
                            "UOM", filters={"custom_absentry": uom_entry,
                                            "custom_company": company}, 
                            fields=["name"], limit=1)
                if uom_doc:
                    insertar_o_actualizar_item_price({
                        "item_code": item_code,
                        "price_list": price_list_name,
                        "price_list_rate": precio_uom,
                        "uom": uom_doc[0].name,
                        "currency": moneda_uom
                    })
        
        

def insertar_o_actualizar_item_price(data):
    """Crea o actualiza un registro en Item Price con base en el código de artículo, lista de precios y UOM."""
    filtros = {
        "item_code": data["item_code"],
        "price_list": data["price_list"],
        "uom": data.get("uom")
    }

    item_price = frappe.get_all("Item Price", filters=filtros, fields=["name"], limit=1)
    #print(f"✅ ID Precio lista {data} ")
    if item_price:
        doc = frappe.get_doc("Item Price", item_price[0].name)
        doc.price_list_rate = data["price_list_rate"]
        doc.currency = data["currency"]
        # 👇 Esto ignora los permisos del usuario actual
        doc.flags.ignore_permissions = True 
        doc.save()
        frappe.db.commit()
    else:
        doc = frappe.new_doc("Item Price")
        # 👇 Esto ignora los permisos del usuario actual
        doc.flags.ignore_permissions = True 
        doc.update(data)
        doc.insert()
        frappe.db.commit()