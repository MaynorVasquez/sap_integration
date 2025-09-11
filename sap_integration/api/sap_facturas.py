import frappe
from frappe import _
from datetime import date
from .sap_auth import login_sap 
from .blueprint import mapping_blueprint1, construir_url_sap

def crear_factura_deudores(docname):
    """
    Envía una factura de ERPNext hacia SAP
    construyendo el payload dinámico.
    """
    try:
        # 1. Login a SAP
        session = login_sap()

        # 2. Obtener el mapeo del blueprint
        mapeo = mapping_blueprint1("Mapeo Factura SAP", "ItemCode", "ItemCode")
        if not mapeo or "sap_fields" not in mapeo:
            frappe.throw(_("No se pudo obtener el mapeo de campos desde el blueprint"))

        url = mapeo.get("url")
        if not url:
            frappe.throw(_("No se encontró la URL destino en el mapeo"))

        # 3. Obtener el documento de ERPNext
        print(docname)
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
            frappe.msgprint(_("Factura enviada exitosamente a SAP"))
            return response.json()
        else:
            frappe.log_error(response.text, "Error al enviar la factura a SAP")
            frappe.throw(_("Error al enviar la factura a SAP: {0}").format(response.text))

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Excepción enviando SAP")
        frappe.throw(_("Error inesperado enviando la factura a SAP: {0}").format(str(e)))



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
            valor = None
            if pos_profile_name:
                pos_doc = frappe.get_doc("POS Profile", pos_profile_name)
                valor = pos_doc.get("custom_series")
        elif campo_erp == "shipping_address_name":
            shiptocode = doc.get("shipping_address_name") or ""   # Si es None → ""
            if shiptocode and shiptocode.lower().endswith(("-envío", "-facturación", "-shipping", "-billing")):
                shiptocode = shiptocode.rsplit("-", 1)[0].strip()
            valor = shiptocode
        else:
            valor = doc.get(campo_erp)
        if valor is not None:
            payload[campo_sap] = valor

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
                valor = "%.6f" % (price_list / 1.12) if price_list else None
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
        print(batch_list)
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
                if campo_erp == "BatchNumber":
                    valor = batchnum_sap
                elif campo_erp == "qty":
                    valor = lote.get("Quantity") or item.get("qty")
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