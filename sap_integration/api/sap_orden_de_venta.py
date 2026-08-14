from frappe import _
import frappe
from datetime import date
from collections import defaultdict
from .sap_auth import login_sap 
from .blueprint import mapping_blueprint1
from .usuarios_autorizados import verificar_autorizacion
from sap_integration.utils.url_endpoint_post import url_endpoint_post
from sap_integration.utils.logs_transactional import logs_transactional
from sap_integration.utils.obtener_filtros_validacion_sap import obtener_filtros_validacion_sap
import requests
from frappe.utils import flt
import json
from frappe.exceptions import ValidationError

def enviar_ov(doc, method):
    debug_messages = []
    try:
        # Ignorar documentos creados por la integración/API
        if doc.flags.get("sap_sales_order_sync"):
            print(f"Documento {doc.name} creado por integración SAP. No se enviará nuevamente a SAP.")
            return
        
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
            print("La sesión SAP no se creó correctamente")
        print("✔ Autenticación exitosa")

        # Si ya tiene referencia SAP no hacer nada
        if doc.custom_docnum:
            print(
                f"La OV {doc.name} ya tiene DocNum SAP: "
                f"{doc.custom_docnum}"
            )
            return

        # 2. Obtener el mapeo del blueprint
        mapeo = mapping_blueprint1(doctype_mapeo,"DocEntry","DocEntry")
        if not mapeo or "sap_fields" not in mapeo:
            frappe.throw(_("No se pudo obtener el mapeo de campos desde el blueprint"))
        print("Mapeo exitoso")

        # =================================================================
        # 2b. VALIDACIÓN DINÁMICA DE DUPLICADOS DESDE CONFIGURACIÓN UI
        # =================================================================
        filtros = ["Cancelled eq 'tNO'"]
        ejecutar_validacion = False
        ejecutar_validacion, filtros_dinamicos = obtener_filtros_validacion_sap(
            doc.customer, 
            doctype_actual, 
            doc
        )
        # Ejecutar la petición a SAP solo si pasó los criterios dinámicos
        print(f"Validacion es: {ejecutar_validacion}")
        if ejecutar_validacion:
            filtros.extend(filtros_dinamicos)
            filter_url = f"{url}?$filter={' and '.join(filtros)}"
            print(f"Validando duplicados en SAP con la URL: {filter_url}")

            check_resp = session.get(filter_url, timeout=30)
            if check_resp.status_code == 200:
                existing = check_resp.json().get("value", [])
                if existing:
                    sap_docnum = existing[0].get("DocNum")
                    sap_docentry = existing[0].get("DocEntry")
                    frappe.msgprint(_("La orden ya existe en SAP con DocNum: {0}").format(sap_docnum))
                    frappe.db.set_value(doctype_target, doc.name, {"custom_docnum" : sap_docnum, "custom_docentry" : sap_docentry})
                    frappe.db.commit()
                    return existing[0]  # Se detiene la ejecución, evita el POST duplicado
        else:
            print("Omitiendo validación: Cliente no configurado o campos de control vacíos.")



        # 3. Construir el payload usando el doc completo
        payload = construir_payload_sap(doc, mapeo)
        print(f"URL: {url}")
        print(f"Datos: {json.dumps(payload, indent=2)}")
        # 5. Enviar a SAP
        response = session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        print(f"Respuesta SAP: {response}")
        # 6. Validar respuesta
        if response.status_code in (200, 201):
            data = response.json()
            sap_docnum = data.get("DocNum")
            sap_docentry = data.get("DocEntry")
            frappe.msgprint(f"Orden de venta enviada correctamente a SAP: {sap_docnum}")
            # 6. Capturar DocNum de la respuesta y actualizar en ERPNext  
            respuesta = f"Factura enviada éxito, referencia SAP: {sap_docnum}"          
            if sap_docnum:
                frappe.db.set_value("Sales Order", doc.name,  {"custom_docnum" : sap_docnum, "custom_docentry" : sap_docentry})
                frappe.db.commit()
            logs_transactional(doctype_logs, doc, "Success" , payload, respuesta, doctype_mapeo,doctype_target)
            return data
        else: 
            #logs_transactional(doctype_logs, doc,"Error" ,payload, response.text, doctype_mapeo,doctype_target)
            frappe.log_error(response.text, "Error al enviar OV a SAP")
            frappe.throw(_("Error al enviar OV SAP, Valide el sigueinte error: {0}").format(response.text))
    except ValidationError:
        raise
    except Exception as e:
        #frappe.log_error(frappe.get_traceback(), "Excepción enviando SAP")
        frappe.throw(_("Error SAP: {0}").format(str(e)))

def construir_payload_sap(doc, mapeo):
    payload = {
        "DocEntry": "0",
        "DocType": "dDocument_Items",
        "DocumentLines": []
    }

    # === HEAD DINÁMICO ===
    for campo_erp, campo_sap in mapeo["sap_fields"].get("head", {}).items():
        # 1. Asignar por defecto el valor directo de ERPNext (ej: po_no)
        valor = doc.get(campo_erp)
        # 2. Interceptar solo si el campo requiere una transformación especial
        if campo_erp == "customer":
            if valor:
                customer_doc = frappe.get_cached_doc("Customer", valor)
                valor = customer_doc.get("custom_cardcode") or valor

        elif campo_erp == "custom_nit":
            customer_code = doc.get("customer")
            if customer_code:
                customer_doc = frappe.get_cached_doc("Customer", customer_code)
                valor = customer_doc.get("custom_nit")
            else:
                valor = None

        elif campo_erp == "currency":
            if valor == "GTQ":
                valor = "QTZ"

        # Evaluamos por campo_sap para asegurar la lógica del negocio de SAP
        elif campo_sap == "U_Vendedor":
            sales_team = doc.get("sales_team") or []
            valor = sales_team[0].sales_person if sales_team else None

        elif campo_sap == "SalesPersonCode":
            sales_team = doc.get("sales_team") or []
            if sales_team:
                vendedor_code = sales_team[0].sales_person
                vendedor_doc = frappe.get_cached_doc("Sales Person", vendedor_code)
                valor = vendedor_doc.get("custom_salesemployeecode") or vendedor_code
            else:
                valor = None

        elif campo_erp == "shipping_address_name":
            shiptocode = valor or ""
            if shiptocode and shiptocode.lower().endswith(("-envío", "-facturación", "-shipping", "-billing")):
                shiptocode = shiptocode.rsplit("-", 1)[0].strip()
            valor = shiptocode

        # Formateo automático de fechas para cualquier campo mapeado del HEAD
        if isinstance(valor, date):
            valor = valor.strftime("%Y%m%d")

        # 3. Guardar en el payload si el valor es válido
        if valor is not None:
            payload[campo_sap] = valor


    # --- Procesamiento previo de Impuestos para el Detalle ---
    tax_code_sap = None
    plantilla_impuestos = doc.get("taxes_and_charges")

    if plantilla_impuestos:
        tax_code_sap = frappe.get_cached_value(
            "Sales Taxes and Charges Template", 
            plantilla_impuestos, 
            "custom_taxcode"
        )
        
    iva_rate = 0
    if doc.get("taxes"):
        iva_rate = flt(doc.taxes[0].rate)
    factor_iva = 1 + (iva_rate / 100)


    # === DETALLE DINÁMICO (DocumentLines) ===
    for idx, item in enumerate(doc.get("items", [])):
        linea = {"LineNum": str(idx)}
        
        for campo_erp, campo_sap in mapeo["sap_fields"].get("DocumentLines", {}).items():
            # 1. Asignar por defecto el valor de la línea de ERPNext
            valor = item.get(campo_erp)

            # 2. Interceptar transformaciones especiales de las líneas
            if campo_erp == "warehouse":
                if valor:
                    wh_doc = frappe.get_cached_doc("Warehouse", valor)
                    valor = wh_doc.get("custom_warehousecode") or valor

            elif campo_erp == "uom":
                if valor:
                    uom_doc = frappe.get_cached_doc("UOM", valor)
                    valor = uom_doc.get("custom_absentry") or valor

            elif campo_erp == "item_code":
                if valor:
                    item_doc = frappe.get_cached_doc("Item", valor)
                    valor = item_doc.get("custom_itemcode") or valor

            elif campo_erp == "account_head":
                valor = tax_code_sap

            elif campo_erp == "net_rate":
                descuento = flt(item.get("discount_amount"))  
                if descuento > 0:
                    valor = flt(valor or 0) + (descuento / factor_iva)
            elif campo_erp == "custom_linenum":
                valor = str(idx)

            # 3. Guardar en la línea si el valor es válido
            if valor is not None:
                linea[campo_sap] = valor

        payload["DocumentLines"].append(linea)

    return payload

