import frappe
from frappe import _
from datetime import date
from .sap_auth import login_sap 
from .blueprint import mapping_blueprint1, construir_url_sap

def factura_deudores(docname):
    """
    Envía una factura de ERPNext hacia SAP
    construyendo el payload dinámico.
    """
    try:
        response = None
        # 1. Login a SAP
        session = login_sap()

        # 2. Obtener el mapeo del blueprint
        mapeo = mapping_blueprint1("Mapeo Factura SAP", "ItemCode", "ItemCode")
        if not mapeo or "sap_fields" not in mapeo:
            frappe.throw(_("No se pudo obtener el mapeo de campos desde el blueprint"))

        url = mapeo.get("url")
        if not url:
            frappe.throw(_("No se encontró la URL destino en el mapeo"))
        
        # 2b. Verificar si la orden ya existe en SAP (U_OrdenDeCompra = po_no y Cancelled = 'tNO')
        filter_url = f"{url}?$filter=NumAtCard eq '{docname}' and Cancelled eq 'tNO'"
        check_resp = session.get(filter_url, timeout=30)
        if check_resp.status_code == 200:
            existing = check_resp.json().get("value", [])
            if existing:
                sap_docnum = existing[0].get("DocNum")
                frappe.msgprint(f"Factura ya exite en SAP B1 con folio No. {sap_docnum}")
                frappe.db.set_value("Sales Invoice", docname, "custom_docnum", sap_docnum)
                frappe.db.commit()
                return existing[0]  # No se envía POST nuevamente


        # 3. Obtener el documento de ERPNext
        doc = frappe.get_doc("Sales Invoice", docname)
        

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
            if sap_docnum:
                frappe.db.set_value("Sales Invoice", docname, "custom_docnum", sap_docnum)
                frappe.db.commit()
            return data
        else:
            frappe.log_error(response.text, f"Factura de deudores: {docname}")

    except Exception as e:
        frappe.log_error(response.text, f"Factura de deudores: {docname}")



def construir_payload_sap(doc, mapeo):
    """
    Construye el payload para SAP desde un documento ERPNext,
    usando mapeo de campos en niveles head, DocumentLines y BatchNumbers
    y resolviendo campos especiales (CardCode, WarehouseCode, BatchNumber)
    dinámicamente desde el backend.
    """

    payload = {
        "DocEntry": "0",
        "DocType": "dDocument_Items",
        "DocumentLines": []
    }

    # HEAD
    for campo_erp, campo_sap in mapeo["sap_fields"].get("head", {}).items():
        if campo_erp == "customer":
            customer_code = doc.get("customer")
            if customer_code:
                customer_doc = frappe.get_doc("Customer", customer_code)
                custom_cardcode = customer_doc.get("custom_cardcode")
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
        elif campo_erp in ["creation", "DocDueDate","posting_date","due_date"]:
            fecha = doc.get(campo_erp)
            valor = fecha.strftime("%Y-%m-%d") if fecha else None
        elif campo_erp in ["custom_fecha"]:
            fecha = doc.get(campo_erp)
            valor = fecha.strftime("%d-%m-%Y %H:%M:%S") if fecha else None
        elif campo_erp == "custom_series":
            pos_profile_name = doc.get("pos_profile")
            if pos_profile_name:
                pos_doc = frappe.get_doc("POS Profile", pos_profile_name)
                valor = pos_doc.get("custom_serie_sap")
        elif campo_erp == "shipping_address_name":
            shiptocode = doc.get("shipping_address_name") or ""   # Si es None → ""
            if shiptocode and shiptocode.lower().endswith(("-envío", "-facturación", "-shipping", "-billing")):
                shiptocode = shiptocode.rsplit("-", 1)[0].strip()
            
            # Validación adicional para custom_cardcode específico
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

        for campo_erp, campo_sap in mapeo["sap_fields"].get("DocumentLines", {}).items():
            if campo_erp == "warehouse":
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
                tax_rate = impuestos.get("rate", 0)  # si no existe, 0
                factor = (100 + tax_rate) / 100 if tax_rate else 1
                valor = "%.6f" % (price_list / factor) if price_list else None
            elif campo_erp == "taxcode":  
                # Mapeo directo de la descripción del impuesto (ej: IVA -> mapeo en SAP)
                tax_desc = impuestos.get("description")
                valor = tax_desc 
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
                if campo_erp == "batch_no":
                    valor = batchnum_sap
                elif campo_erp == "stock_qty":
                    valor = lote.get("Quantity") or item.get("stock_qty")
                elif campo_erp == "item_code":
                    valor = item.get("item_code")
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