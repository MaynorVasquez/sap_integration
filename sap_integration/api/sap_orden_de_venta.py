from frappe import _
import frappe
from datetime import date
from collections import defaultdict
from .sap_auth import login_sap 
from .blueprint import mapping_blueprint1
from .usuarios_autorizados import verificar_autorizacion
from sap_integration.utils.url_endpoint_post import url_endpoint_post
from sap_integration.utils.logs_transactional import logs_transactional
import requests

def enviar_ov(doc, method):
    debug_messages = []
    try:
        doctype_target = "Sales Order"
        sales_order = frappe.get_doc(doctype_target, doc)
        company = sales_order.company
        doctype_mapeo = "Mapeo Orden De Venta SAP"
        doctype_logs = "SAP Logs Transactional Sales Order"
        

        url = url_endpoint_post(doctype_mapeo,company)

        usuario_actual = frappe.session.user
        doctype_actual = doc.doctype  # Ej: "Sales Order"

        # Verificar autorización
        if not verificar_autorizacion(usuario_actual, doctype_actual):
            print(f"El usuario {usuario_actual} no enviara el documento a sap tipo  {doctype_actual}")
            #frappe.msgprint(f"⚠ El usuario {usuario_actual} no está autorizado para sincronizar {doctype_actual} con SAP")
            return
        # 1. Login a SAP
        session = login_sap(company)
        if not session or not isinstance(session, requests.Session):
            raise Exception("La sesión SAP no se creó correctamente")
        debug_messages.append("✔ Autenticación exitosa")

        # 2. Obtener el mapeo del blueprint
        mapeo = mapping_blueprint1(doctype_mapeo,"DocEntry","DocEntry")
        if not mapeo or "sap_fields" not in mapeo:
            frappe.throw(_("No se pudo obtener el mapeo de campos desde el blueprint"))

        # 2b. Verificar si la orden ya existe en SAP (U_OrdenDeCompra = po_no y Cancelled = 'tNO')
        filter_url = f"{url}?$filter=U_OrdenDeCompra eq '{doc.po_no}' and U_GLN eq '{doc.custom_gln}' and Cancelled eq 'tNO'"
        check_resp = session.get(filter_url, timeout=30)
        if check_resp.status_code == 200:
            existing = check_resp.json().get("value", [])
            if existing:
                sap_docnum = existing[0].get("DocNum")
                frappe.msgprint(_("La orden ya existe en SAP con DocNum: {0}").format(sap_docnum))
                frappe.db.set_value("Sales Order", doc.name, "custom_docnum", sap_docnum)
                frappe.db.commit()
                return existing[0]  # No se envía POST nuevamente        

        # 3. Construir el payload usando el doc completo
        payload = construir_payload_sap(doc, mapeo)
        debug_messages.append(f"✔ Payload construido: {payload}")

        # 5. Enviar a SAP
        response = session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        # 6. Validar respuesta
        if response.status_code in (200, 201):
            data = response.json()
            sap_docnum = data.get("DocNum")
            frappe.msgprint(f"Orden de venta enviada correctamente a SAP: {sap_docnum}")
            # 6. Capturar DocNum de la respuesta y actualizar en ERPNext  
            respuesta = f"Factura enviada éxito, referencia SAP: {sap_docnum}"          
            if sap_docnum:
                frappe.db.set_value("Sales Order", doc.name, "custom_docnum", sap_docnum)
                frappe.db.commit()
            logs_transactional(doctype_logs, doc, "Success" , payload, respuesta, doctype_mapeo,doctype_target)
            return data
        else:
            logs_transactional(doctype_logs, doc,"Error" ,payload, response.text, doctype_mapeo,doctype_target)
            frappe.log_error(response.text, "Error al enviar OV a SAP")
            frappe.throw(_("Error al enviar la factura a SAP: {0}").format(response.text))

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Excepción enviando SAP")
        frappe.throw(_("Error inesperado enviando la factura a SAP: {0}").format(str(e)))

def construir_payload_sap(doc, mapeo):
    payload = {
        "DocEntry": "0",
        "DocType": "dDocument_Items",
        "DocumentLines": []
    }

    # === HEAD dinámico ===
        # HEAD
    for campo_erp, campo_sap in mapeo["sap_fields"].get("head", {}).items():
        if campo_erp == "customer":
            customer_code = doc.get("customer")
            if customer_code:
                customer_doc = frappe.get_doc("Customer", customer_code)
                valor = customer_doc.get("custom_cardcode") or customer_code
            else:
                valor = None
        elif campo_erp == "custom_nit":
            customer_code = doc.get("customer")
            if customer_code:
                customer_doc = frappe.get_doc("Customer", customer_code)
                valor = customer_doc.get("custom_nit")
            else:
                valor = None
        elif campo_erp == "currency":
            moneda_erp = doc.get("currency")
            valor = "QTZ" if moneda_erp == "GTQ" else moneda_erp
        elif campo_erp == "U_Vendedor":  # ← nuevo campo que ya está mapeado
            sales_team = doc.get("sales_team") or []
            if sales_team:
                valor = sales_team[0].sales_person
            else:
                valor = None
        elif campo_erp == "SalesPersonCode":  # ← nuevo campo que ya está mapeado
            sales_team = doc.get("sales_team") or []
            if sales_team:
                vendedor_code = sales_team[0].sales_person
                vededor_doc = frappe.get_doc("Sales Person", vendedor_code)
                valor = vededor_doc.get("custom_salesemployeecode") or vendedor_code
            else:
                valor = None
        elif campo_erp == "shipping_address_name":
            shiptocode = doc.get("shipping_address_name") or ""   # Si es None → ""
            if shiptocode and shiptocode.lower().endswith(("-envío", "-facturación", "-shipping", "-billing")):
                shiptocode = shiptocode.rsplit("-", 1)[0].strip()
            valor = shiptocode
        else:
            valor = doc.get(campo_erp)
            # Si es fecha, convertir a string YYYYMMDD
            if isinstance(valor, date):
                valor = valor.strftime("%Y%m%d")

        if valor is not None:
            payload[campo_sap] = valor
    # Obtener impuestos de la factura
    tax_code_sap = None
    plantilla_impuestos = doc.get("taxes_and_charges")

    if plantilla_impuestos:
        # Buscamos el código de SAP directamente en el maestro de la plantilla
        tax_code_sap = frappe.get_cached_value(
            "Sales Taxes and Charges Template", 
            plantilla_impuestos, 
            "custom_taxcode"
        )

    # === DETALLE dinámico ===
    for idx, item in enumerate(doc.get("items", [])):
        linea = {"LineNum": str(idx)}
        # Obtenemos el item_doc una sola vez por cada línea para ahorrar recursos
        item_code_original = item.get("item_code")
        item_doc = frappe.get_cached_doc("Item", item_code_original) if item_code_original else None
        item_code_limpio = item_doc.get("custom_itemcode") or item_code_original if item_doc else item_code_original
        for campo_erp, campo_sap in mapeo["sap_fields"].get("DocumentLines", {}).items():
            if campo_erp == "warehouse":
                valor = None
                warehouse_code = item.get("warehouse")
                if warehouse_code:
                    wh_doc = frappe.get_doc("Warehouse", warehouse_code)
                    valor = wh_doc.get("custom_warehousecode") or warehouse_code
            elif campo_erp == "uom":
                valor = None
                uom_name = item.get("uom")
                if uom_name:
                    uom_doc = frappe.get_doc("UOM", uom_name)
                    valor = uom_doc.get("custom_absentry") or uom_name
            elif campo_erp == "item_code":
                valor = item_code_limpio
            elif campo_erp == "account_head":
                valor = tax_code_sap
            else:
                valor = item.get(campo_erp)

            if valor is not None:
                linea[campo_sap] = valor

        payload["DocumentLines"].append(linea)

    return payload