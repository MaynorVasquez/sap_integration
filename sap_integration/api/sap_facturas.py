import frappe
from frappe import _
from datetime import date
from sap_integration.api.sap_auth import login_sap
from sap_integration.api.blueprint import mapping_blueprint1
from sap_integration.utils.url_endpoint_post import url_endpoint_post
from sap_integration.utils.logs_transactional import logs_transactional

def factura_deudores(docname):
    session = None
    try:
        factura = frappe.get_doc("Sales Invoice", docname)
        company = factura.company
        doctype_mapeo = "Mapeo Factura SAP"
        doctype_logs = "SAP Logs Transactional Invoices"
        doctype_target = "Sales Invoice"

        url = url_endpoint_post(doctype_mapeo,company)

        response = None
        # 1. Login a SAP
        session = login_sap(company)


        # 2. Obtener el mapeo del blueprint
        mapeo = mapping_blueprint1(doctype_mapeo, "ItemCode", "ItemCode")
        if not mapeo or "sap_fields" not in mapeo:
            frappe.throw(_("No se pudo obtener el mapeo de campos desde el blueprint"))
        
        # 2b. Verificar si la orden ya existe en SAP (U_OrdenDeCompra = po_no y Cancelled = 'tNO')
        filter_url = f"{url}?$filter=NumAtCard eq '{docname}' and Cancelled eq 'tNO'"
        print(f"se busca antes la factura {filter_url}")
        check_resp = session.get(filter_url, timeout=30)
        if check_resp.status_code == 200:
            existing = check_resp.json().get("value", [])
            if existing:
                sap_docnum = existing[0].get("DocNum")
                frappe.msgprint(f"Factura ya exite en SAP B1 con folio No. {sap_docnum}")
                frappe.db.set_value(doctype_target, docname, "custom_docnum", sap_docnum)
                frappe.db.commit()
                return existing[0]  # No se envía POST nuevamente

        print(f"se inicia el proceso de contruir el payload")
        # 3. Obtener el documento de ERPNext
        doc = frappe.get_doc(doctype_target, docname)
        

        # 4. Construir el payload
        payload = construir_payload_sap(doc, mapeo)

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
            print(f"Factura SAP: {sap_docnum}")
            frappe.msgprint(_(f"Factura enviada exitosamente a SAP {sap_docnum}"))
            respuesta = f"Factura enviada éxito, referencia SAP: {sap_docnum}"
            if sap_docnum:
                frappe.db.set_value(doctype_target, docname, "custom_docnum", sap_docnum)
                frappe.db.commit()
            logs_transactional(doctype_logs, docname, "Success" , payload, respuesta, doctype_mapeo,doctype_target)
            return data
        else:
            logs_transactional(doctype_logs, docname,"Error" ,payload, response.text, doctype_mapeo,doctype_target)
            frappe.log_error(response.text, f"Factura de deudores: {docname}")
            

    except Exception as e:
        frappe.log_error(response.text, f"Factura de deudores: {docname}")



def construir_payload_sap(doc, mapeo):
    payload = {
        "DocEntry": "0",
        "DocType": "dDocument_Items",
        "DocumentLines": []
    }

    # ========================================
    # 🔹 Obtener datos del cliente una sola vez
    # ========================================
    customer_code = doc.get("customer")
    custom_cardcode = None
    custom_nit = None

    if customer_code:
        try:
            customer_doc = frappe.get_doc("Customer", customer_code)
            custom_cardcode = customer_doc.get("custom_cardcode")
            custom_nit = customer_doc.get("custom_nit")
            print(f"Cliente: {customer_code}, CardCode SAP: {custom_cardcode}")
        except frappe.DoesNotExistError:
            frappe.log_error(f"Cliente no encontrado: {customer_code}", "Error al obtener datos del cliente")
    else:
        frappe.log_error("Documento sin cliente asociado", "Error en construir_payload_sap")

    # ========================================
    # 🔹 HEAD
    # ========================================
    for campo_erp, campo_sap in mapeo["sap_fields"].get("head", {}).items():

        if campo_erp == "customer":
            valor = custom_cardcode or customer_code

        # elif campo_erp == "custom_nit":
        #     valor = custom_nit

        elif campo_erp == "currency":
            moneda_erp = doc.get("currency")
            valor = "QTZ" if moneda_erp == "GTQ" else moneda_erp

        elif campo_erp in ["creation", "DocDueDate", "posting_date", "due_date"]:
            fecha = doc.get(campo_erp)
            valor = fecha.strftime("%Y-%m-%d") if fecha else None

        elif campo_erp == "custom_fecha":
            fecha = doc.get(campo_erp)
            valor = fecha.strftime("%d-%m-%Y %H:%M:%S") if fecha else None

        elif campo_erp == "custom_series":
            pos_profile_name = doc.get("pos_profile")
            if pos_profile_name:
                pos_doc = frappe.get_doc("POS Profile", pos_profile_name)
                valor = pos_doc.get("custom_serie_sap")
            else:
                valor = None

        elif campo_erp == "shipping_address_name":
            shiptocode = doc.get("shipping_address_name") or ""
            if shiptocode.lower().endswith(("-envío", "-facturación", "-shipping", "-billing", "-Shipping")):
                shiptocode = shiptocode.rsplit("-", 1)[0].strip()

            # Validación adicional para un cliente específico
            print(f"Verificando CardCode: {custom_cardcode}")
            if custom_cardcode == "C02683":
                shiptocode = "Tienda B2"

            valor = shiptocode

        else:
            valor = doc.get(campo_erp)

        if valor is not None:
            payload[campo_sap] = valor
    
    # Obtener impuestos de la factura
    impuestos = doc.get("taxes", [])[0] if doc.get("taxes") else {}


    # DETALLE
    for idx, item in enumerate(doc.get("items", [])):
        linea = {"LineNum": str(idx)}
        
        # Obtenemos el item_doc una sola vez por cada línea para ahorrar recursos
        item_code_original = item.get("item_code")
        item_doc = frappe.get_cached_doc("Item", item_code_original) if item_code_original else None
        item_code_limpio = item_doc.get("custom_itemcode") or item_code_original if item_doc else item_code_original
        for campo_erp, campo_sap in mapeo["sap_fields"].get("DocumentLines", {}).items():
            # USAR EL CÓDIGO LIMPIO
            if campo_erp == "item_code":
                valor = item_code_limpio
            
            elif campo_erp == "warehouse":
                warehouse_code = item.get("warehouse")
                whscode = None
                if warehouse_code:
                    wh_doc = frappe.get_doc("Warehouse", warehouse_code)
                    whscode = wh_doc.get("custom_warehousecode") or warehouse_code
                valor = whscode
            
            elif campo_erp == "uom":
                uom_name = item.get("uom")
                uom_code = None
                if uom_name:
                    uom_doc = frappe.get_doc("UOM", uom_name)
                    uom_code = uom_doc.get("custom_absentry") or uom_name
                valor = uom_code
                
            elif campo_erp == "price_list_rate":
                price_list = item.get("price_list_rate")
                tax_rate = impuestos.get("rate", 0)
                factor = (100 + tax_rate) / 100 if tax_rate else 1
                valor = "%.6f" % (price_list / factor) if price_list else None
                
            elif campo_erp == "taxcode":  
                valor = impuestos.get("description")
                
            else:
                valor = item.get(campo_erp)

            if valor is not None:
                linea[campo_sap] = valor

        # LOTES
        lotes = []
        batch_list = item.get("batches")
        if not batch_list:
            batch_list = []

        # fallback si solo tiene batch_no
        if not batch_list and item.get("batch_no"):
            batch_list = [{
                "BatchNumber": item.get("batch_no"),
                "Quantity": item.get("stock_qty"),
                "ItemCode": item.get("item_code"),
                "BaseLineNumber": str(idx)
            }]

        # nuevo: buscar dentro de serial_and_batch_bundle si tampoco batch_list ni batch_no
        if not batch_list and item.get("serial_and_batch_bundle"):
            try:
                bundle_doc = frappe.get_doc("Serial and Batch Bundle", item.get("serial_and_batch_bundle"))
                for b_item in bundle_doc.get("entries", []):               
                    batch_list.append({
                        "BatchNumber": b_item.batch_no,
                        "Quantity": abs(b_item.qty),  # abs() para quitar el negativo
                        "ItemCode": item.get("item_code"),
                        "BaseLineNumber": str(idx)
                    })
            except frappe.DoesNotExistError:
                frappe.log_error("No existe el bundle", "Error reconstruyendo batch_no desde serial_and_batch_bundle")

        # recorrer los lotes finales
        for lote in batch_list:
            lote_payload = {}
            batch_number_erp = lote.get("BatchNumber") or lote.get("batch_no")
            batchnum_sap = None

            if batch_number_erp:
                try:
                    batch_doc = frappe.get_doc("Batch", batch_number_erp)
                    batchnum_sap = batch_doc.get("custom_batchnum") or batch_number_erp
                except frappe.DoesNotExistError:
                    batchnum_sap = batch_number_erp

            for campo_erp, campo_sap in mapeo["sap_fields"]["BatchNumbers"].items():
                if campo_erp == "item_code":
                    valor = item_code_limpio
                elif campo_erp == "batch_no":
                    valor = batchnum_sap
                elif campo_erp == "stock_qty":
                    valor = lote.get("Quantity") or item.get("stock_qty")
                elif campo_erp == "BaseLineNumber":
                    valor = str(idx)
                else:
                    valor = lote.get(campo_erp)

                if valor is not None:
                    lote_payload[campo_sap] = valor

            if lote_payload:
                lotes.append(lote_payload)

        if lotes:
            linea["BatchNumbers"] = lotes

        payload["DocumentLines"].append(linea)

    return payload