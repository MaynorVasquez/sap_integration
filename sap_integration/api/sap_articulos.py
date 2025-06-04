import frappe
from frappe import _
import requests
import json
import traceback  # Importación añadida
from .mapeos import mapping_blueprint
from .sap_auth import login_sap 
from .logs import log_sincronizacion
from .lista_precio import sincronizar_lista_precio

@frappe.whitelist()
def sincronizar_lista_articulos(docname=None):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    doctype_logs = "Sincronizacion Articulos Grupo SAP"
    doctype_target = "Item"

    try:
        # 1. Autenticación
        debug_messages.append("Iniciando autenticación con SAP...")
        session = login_sap()

        if not session or not isinstance(session, requests.Session):
            raise Exception("La sesión SAP no se creó correctamente")
        debug_messages.append("✔ Autenticación exitosa")

        # 2. Obtener la estructura del mapeo de campos
        mapeo_lista = mapping_blueprint("Mapeo Articulo SAP", "ItemCode", "item_code")
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos")
        debug_messages.append("✔ Mapeo de campos obtenido")

        # 3. Configuración
        base_url = "https://apisap.yaesta.com.gt/b1s/v1/Items"
        select_fields = ",".join(mapeo_lista["sap_fields"].values())
        filter_condition = "U_smart_art eq '1'"

                # 4. Paginación
        page, skip = 1, 0
        while True:
            current_url = f"{base_url}?$select={select_fields}&$filter={filter_condition}&$top=20&$skip={skip}"
            debug_messages.append(f"\nPágina {page} - URL: {current_url}")

            response = session.get(current_url, timeout=30)
            response.raise_for_status()
            data = response.json()

            lista_datos = data.get('value', [])
            if not lista_datos:
                debug_messages.append("✓ Fin de paginación alcanzado")
                break

            for registro_sap in lista_datos:
                result, datos_mapeados = procesar_dato(registro_sap, mapeo_lista, doctype_target)
                if result:
                    total_procesados += 1
                    debug_messages.append(f"✓ Dato: {result} procesado")
                    detalles.append(datos_mapeados)  # aquí guardas el JSON final procesado
                    print("🔍 JSON detalles que se enviará al log:")
                    print(json.dumps(detalles, indent=2, ensure_ascii=False))

            frappe.db.commit()
            skip += 20
            page += 1

    except Exception as e:
        error_msg = f"Error durante sincronización: {str(e)}\n{traceback.format_exc()}"
        debug_messages.append(f"✗ {error_msg}")
        frappe.log_error(title="Error sincronizando listas de precios desde SAP", message=error_msg)

        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Error",
                total=total_procesados,
                detalles={},
                errores=error_msg
            )

        return {
            "status": "error",
            "message": "Ocurrió un error durante la sincronización",
            "debug": debug_messages,
            "total": total_procesados
        }
    
    finally:        
        if session and isinstance(session, requests.Session):
            session.close()
            debug_messages.append("✓ Sesión SAP cerrada correctamente")

        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Exitoso" if total_procesados > 0 else "Sin cambios",
                total=total_procesados,
                detalles=detalles, #Json devuelto
                errores=""
            )
    return {
        "status": "success" if total_procesados > 0 else "warning",
        "total": total_procesados,
        "debug": debug_messages
    }

#Funcion para procesar datos paginadas
def procesar_dato(registro_sap, mapeo_lista, doctype_target):
    """Crea o actualiza un documento en ERPNext a partir de un registro obtenido de SAP."""
    try:
        # Obtener campos clave
        sap_key_field = mapeo_lista["key_field"]          # Ej: "ItemCode"
        erp_key_field = mapeo_lista["erp_key_field"]      # Ej: "custom_itemcode"
        sap_id = registro_sap.get(sap_key_field)

        if not sap_id:
            frappe.log_error("Registro SAP sin campo clave", json.dumps(registro_sap, indent=2))
            return None, None

        # Buscar si ya existe en ERPNext
        doc_existente = frappe.get_all(doctype_target, filters={erp_key_field: sap_id}, limit=1)

        # Mapeo SAP -> ERP
        datos_mapeados = {}
        for erp_field, sap_field in mapeo_lista["sap_fields"].items():
            datos_mapeados[erp_field] = registro_sap.get(sap_field)

        # Asegurar que el campo clave esté mapeado
        datos_mapeados[erp_key_field] = sap_id
        print("Procesando registro SAP:", sap_id)

        if doc_existente:
            # Actualización
            doc = frappe.get_doc(doctype_target, doc_existente[0].name)
            for campo, valor in datos_mapeados.items():
                setattr(doc, campo, valor)

            asignar_grupo_articulo(doc, registro_sap)

            try:
                doc.save()
                frappe.db.commit()

                # 🔁 Sincronizar UOMs después de guardar
                sincronizar_uoms(sap_id, registro_sap)
                
            except frappe.DocumentModifiedError:
                frappe.db.rollback()
                frappe.log_error(f"Conflicto de modificación al actualizar {sap_id}")
                return None, None
            
            # 👉 Sincronizar lista de precios después de actualizar
            try:
                item_prices = registro_sap.get("ItemPrices")
                if not isinstance(item_prices, list):
                    item_prices = []
                if item_prices:
                    sincronizar_articulo_precio(sap_id, item_prices, registro_sap)
            except Exception as e:
                frappe.log_error(f"Error sincronizando lista de precios para {sap_id}: {e}")

            return f"{sap_id} (actualizado)", datos_mapeados

        else:
            # Creación
            doc = frappe.new_doc(doctype_target)
            for campo, valor in datos_mapeados.items():
                setattr(doc, campo, valor)

            asignar_grupo_articulo(doc, registro_sap)

            try:
                doc.insert()
                frappe.db.commit()
                # 🔁 Sincronizar UOMs después de guardar
                sincronizar_uoms(sap_id, registro_sap)
            except Exception as e:
                frappe.db.rollback()
                frappe.log_error(f"Error al crear {sap_id}: {str(e)}\n{traceback.format_exc()}")
                return None, None
            
            # 👉 Sincronizar lista de precios después de creación
            try:
                item_prices = registro_sap.get("ItemPrices", [])
                if item_prices:
                    sincronizar_articulo_precio(sap_id, item_prices, registro_sap)
            except Exception as e:
                frappe.log_error(f"Error sincronizando lista de precios para {sap_id}: {e}")


            return f"{sap_id} (creado)", datos_mapeados

    except Exception as e:
        frappe.log_error(f"Error al procesar dato {registro_sap.get(sap_key_field)}: {str(e)}\n{traceback.format_exc()}")
        frappe.db.rollback()
        return None, None


def asignar_grupo_articulo(item_doc, item_sap):
    """
    Asigna el grupo de artículo (item_group) al artículo de ERPNext.
    Busca el grupo por el código SAP (ItemGroupCode) comparándolo con el campo custom_number.
    Si el grupo no existe, intenta sincronizar los grupos y vuelve a buscar.
    """
    codigo_sap = str(item_sap.get("ItemsGroupCode"))
    
    if not codigo_sap:
        print(f"⚠ No se proporcionó código de grupo para el artículo {item_doc.name}")
        return

    nombre_grupo = frappe.db.get_value("Item Group", {"custom_number": codigo_sap}, "item_group_name")

    if not nombre_grupo:
        print(f"❌ Grupo con custom_number '{codigo_sap}' no encontrado, intentando sincronizar...")
        try:
            sincronizar_articulos_grupo()
        except Exception as e:
            frappe.log_error(f"Error al sincronizar grupos de artículos: {str(e)}")
            return
        
        # Intentar nuevamente obtener el nombre
        nombre_grupo = frappe.db.get_value("Item Group", {"custom_number": codigo_sap}, "item_group_name")
        if not nombre_grupo:
            print(f"🚫 No se pudo encontrar el grupo después de sincronizar. Código: {codigo_sap}")
            return

    if item_doc.item_group != nombre_grupo:
        item_doc.item_group = nombre_grupo
        print(f"✅ Asignado grupo '{nombre_grupo}' al artículo {item_doc.name}")
    else:
        print(f"ℹ El artículo {item_doc.name} ya tiene asignado el grupo '{nombre_grupo}'")


def sincronizar_articulo_precio(item_code, item_prices, registro_sap):
    """Sincroniza los precios del artículo con las listas de precios en ERPNext."""
    if not item_code or not item_prices:
        return

    # Obtener la unidad de medida por defecto desde InventoryUoMEntry
    inv_uom_entry = registro_sap.get("InventoryUoMEntry")

    uom_por_defecto = None
    if inv_uom_entry:
        uom_doc = frappe.get_all("UOM", filters={"custom_absentry": inv_uom_entry}, fields=["name"], limit=1)
        if uom_doc:
            uom_por_defecto = uom_doc[0].name
            print(f"✅ InventoryUoMEntry por defecto nombre: {uom_por_defecto}")

            # Intentar actualizar los campos del artículo relacionados con UOM
            try:
                item_doc = frappe.get_doc("Item", item_code)

                campos_uom = {
                    "stock_uom": item_doc.stock_uom,
                    "weight_uom": item_doc.weight_uom,
                    "purchase_uom": item_doc.purchase_uom,
                    "sales_uom": item_doc.sales_uom,
                }

                cambios = False
                for campo in campos_uom:
                    if getattr(item_doc, campo) != uom_por_defecto:
                        setattr(item_doc, campo, uom_por_defecto)
                        cambios = True

                if cambios:
                    item_doc.save()
                    frappe.db.commit()
                    print(f"✅ UOM actualizado en campos: stock, weight, purchase, sales para {item_code}: {uom_por_defecto}")
            except Exception as e:
                frappe.log_error(f"❌ Error actualizando campos de UOM para {item_code}: {str(e)}")
        else:
            print(f"⚠️ No se encontró UOM con custom_absentry={inv_uom_entry}")

    for precio in item_prices:
        price_list_id = precio.get("PriceList")
        # Evitar valores inválidos
        if price_list_id == -1:
            continue

        # Validar existencia de la lista de precios
        price_list_doc = frappe.get_all("Price List", filters={"custom_pricelistno": price_list_id}, fields=["name"], limit=1)

        if not price_list_doc:
            # Si no existe, intenta sincronizar la lista de precios desde SAP
            sincronizar_lista_precio()  # función ya existente que creará las listas
            # Vuelve a verificar si ya existe
            price_list_doc = frappe.get_all("Price List", filters={"custom_sap_pricelist": price_list_id}, fields=["name"], limit=1)
            if not price_list_doc:
                frappe.log_error(f"Lista de precios SAP {price_list_id} no encontrada incluso después de sincronización.")
                continue  # Salta si aún no existe

        price_list_name = price_list_doc[0].name
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
                uom_doc = frappe.get_all("UOM", filters={"custom_absentry": uom_entry}, fields=["name"], limit=1)
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
        doc.save()
        frappe.db.commit()
    else:
        doc = frappe.new_doc("Item Price")
        doc.update(data)
        doc.insert()
        frappe.db.commit()



def sincronizar_uoms(item_code, registro_sap):
    try:
        item_doc = frappe.get_doc("Item", item_code)

        # Obtener UoMPrices desde el primer bloque de ItemPrices
        item_prices = registro_sap.get("ItemPrices", [])
        uom_prices = []
        if item_prices and isinstance(item_prices, list):
            uom_prices = item_prices[0].get("UoMPrices", [])

        if not uom_prices:
            frappe.log_error("No se encontró 'UoMPrices'", json.dumps(registro_sap, indent=2))
            return

        # Procesar los UOMs como desees...
        for uom_price in uom_prices:
            uom_entry = uom_price.get("UoMEntry")
            if not uom_entry:
                continue

            # Buscar el UOM en ERPNext por el campo personalizado `custom_absentry`
            uom = frappe.db.get_value("UOM", {"custom_absentry": uom_entry}, "name")
            if not uom:
                continue  # Podrías llamar aquí a sincronizar_lista_uom() si deseas crearlo

            # Evitar duplicados
            ya_asignado = any(row.uom == uom for row in item_doc.uoms)
            if not ya_asignado:
                item_doc.append("uoms", {
                    "uom": uom,
                    "conversion_factor": float(uom_price.get("Factor", 1.0)) or 1.0
                })

        item_doc.save()
        frappe.db.commit()

    except Exception as e:
        frappe.log_error(f"Error al sincronizar UOMs para {item_code}: {str(e)}")
        frappe.db.rollback()

