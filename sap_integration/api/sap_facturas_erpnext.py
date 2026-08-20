import frappe
from frappe import _
import json
import traceback  # Importación añadida
from datetime import datetime
from frappe.utils import flt, cint
from frappe.utils import getdate, nowdate,get_datetime
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual
from sap_integration.utils.logs_transactional import logs_transactional
from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice as make_invoice_from_so
from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice as make_invoice_from_dn
from sap_integration.api.sap_auth import login_sap

@frappe.whitelist()
def sincronizar_facturas_erpnext(docname=None):
    doctype_logs = "Sincronizacion Facturas SAP"
    doctype_target =  "Sales Invoice"
    doctype_mapeo = "Mapeo Factura SAP"
    key_erpnext = "custom_docnum"
    key_sap = "DocNum"
    campos_delta = {
        "create_date": "CreationDate", # Nombre del campo en SAP para fecha de creación
        "create_time": "DocTime",      # Nombre del campo en SAP para hora de creación
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

def procesar_datos(registros_sap, mapeo_lista, doctype, company, debug_messages):
    sap_key_field = mapeo_lista["key_field"]   # "DocNum"
    erp_key_field = mapeo_lista["erp_key_field"]

    for lista_mapeo in registros_sap:
        try:
            sap_id = lista_mapeo.get(sap_key_field)
            DocEntry = lista_mapeo.get("DocEntry")
            DocNum = lista_mapeo.get("DocNum")
            Series = lista_mapeo.get("Series")

            if Series == 306:
                print(f"Factura {DocNum} pertenece a facturas de tienda. Se omite la sincronización.")
                continue

            factura = frappe.db.get_value(doctype, 
                                {"custom_docnum": DocNum,
                                 "company": company,
                                 "docstatus": 1}, 
                                 "name")
            if factura:
                print(f"La factura ya existe DocEntry: {DocEntry} -- DocNum: {DocNum}")
                continue

            DocumentReferences = lista_mapeo.get("DocumentReferences", [])
            es_factura_reserva = lista_mapeo.get("ReserveInvoice") == "tYES"
            
            # --- 1. Detección Dinámica de Referencias ---
            tipo_ref_sap = None
            doctype_erp = None
            
            for ref in DocumentReferences:
                if ref.get("RefObjType") == "rot_DeliveryNotes":
                    tipo_ref_sap = "rot_DeliveryNotes"
                    doctype_erp = "Delivery Note"
                    break # Si hay DN, toma prioridad sobre SO
                elif ref.get("RefObjType") == "rot_SalesOrder":
                    tipo_ref_sap = "rot_SalesOrder"
                    doctype_erp = "Sales Order"

            # --- REGLA DE NEGOCIO: ¿Debe descargar stock la Factura? ---
            # Si es reserva O viene de una Delivery Note, NO descarga stock (update_stock = 0)
            if es_factura_reserva or doctype_erp == "Delivery Note":
                descarga_stock = 0
            else:
                descarga_stock = 1

            print(f"Reserva: {es_factura_reserva} | Doctype Origen: {doctype_erp} | Descarga Stock en Factura: {descarga_stock}")

            sap_ref_dict = {}
            if tipo_ref_sap:
                for ref in DocumentReferences:
                    if ref.get("RefObjType") == tipo_ref_sap:
                        sap_ref_dict[ref.get("RefDocEntr")] = ref.get("RefDocNum")
            print(f"Documentos Base de SAP; {tipo_ref_sap}")

            # --- 2. Buscar documentos base en ERPNext ---
            erpnext_ref_names = {}
            if sap_ref_dict:
                for base_entry, doc_num in sap_ref_dict.items():
                    doc_name = frappe.db.get_value(doctype_erp, {"custom_docnum": doc_num, "company": company}, "name")
                    print(f"Documento encontrado: {doctype_erp} ---- {doc_name}")
                    if doc_name:
                        if doctype_erp == "Sales Order":
                            print(f"Verificando estado de Orden de Venta {doc_name}")
                            so = frappe.get_doc("Sales Order", doc_name)
                            print(f"SO {so.name} - Docstatus actual: {so.docstatus}")
                            if so.docstatus == 0:
                                print(f"Sometiendo Orden de Venta {so.name}...")
                                so.flags.sap_sales_order_sync = True
                                so.submit()
                                print(f"Orden de Venta {so.name} sometida correctamente.")
                            elif so.docstatus == 1:
                                print(f"Orden de Venta {so.name} ya estaba sometida.")
                            elif so.docstatus == 2:
                                frappe.throw(
                                    f"La Orden de Venta {so.name} "
                                    f"está cancelada y no puede utilizarse "
                                    f"para crear la Delivery Note.")
                            else:
                                frappe.throw(
                                    f"La Orden de Venta {so.name} "
                                    f"tiene un DocStatus no válido: "
                                    f"{so.docstatus}")
                        erpnext_ref_names[base_entry] = doc_name
                    else:
                        print(f"{doctype_erp} SAP {doc_num} no existe en ERPNext", f"Error {doctype_erp} Consolidada")
            print(f"Referencias ERPNEXT encontradas: {erpnext_ref_names}")

            # --- 3. BIFURCACIÓN ESTRATÉGICA ---
            if not erpnext_ref_names:
                # Factura Directa (Sin Referencias)
                crear_factura_directa(lista_mapeo, mapeo_lista, doctype, company)
                continue 

            # --- 4. Flujo para Facturas CON Documento Base (SO o DN) ---
            
            # Solo si la factura rebaja stock consultamos la API para traer el detalle de lotes
            lineas_sap = lista_mapeo.get("DocumentLines", [])
            print(f"La factura descargada stock: {descarga_stock}")
            if descarga_stock == 1:
                print(f"Factura rebaja stock directo. Obteniendo detalle de lotes para DocEntry: {DocEntry}")
                payload_completo = obtener_documento_completo_sap(DocEntry, company)
                lineas_sap = payload_completo.get("DocumentLines", [])

            primera_ref_erp = list(erpnext_ref_names.values())[0]                
            
            if doctype_erp == "Sales Order":
                doc = make_invoice_from_so(primera_ref_erp)
            else:
                doc = make_invoice_from_dn(primera_ref_erp)

            doc.custom_docnum = lista_mapeo.get("DocNum")
            doc.custom_docentry = lista_mapeo.get("DocEntry")
            doc.custom_uuid = lista_mapeo.get("U_CAE")
            doc.custom_numero = lista_mapeo.get("U_DocNum")
            doc.custom_serie = lista_mapeo.get("U_DocSerie")
            fecha_sap = lista_mapeo.get("U_Fac_FechaC")
            if fecha_sap:
                doc.custom_fecha = get_datetime(fecha_sap)
            # Asignación del flag update_stock a nivel de documento ERPNext
            doc.update_stock = descarga_stock 

            doc.items = []

            # --- 5. Procesar detalle de items para referenciadas ---
            for linea_sap in lineas_sap:
                base_entry = linea_sap.get("BaseEntry")
                ItemCode_SAP = linea_sap.get("ItemCode")
                BaseLine = linea_sap.get("BaseLine")

                ItemCode_ERPNEXT_query = frappe.db.sql("""
                    SELECT T0.name FROM `tabItem` T0
                    INNER JOIN `tabItem Default` T1 ON T0.name = T1.parent
                    WHERE T0.custom_itemcode = %s AND T1.company = %s LIMIT 1
                """, (ItemCode_SAP, company), as_list=True)

                item_code = ItemCode_ERPNEXT_query[0][0] if ItemCode_ERPNEXT_query else ItemCode_SAP
                erp_doc_name = erpnext_ref_names.get(base_entry)
                
                nueva_entrada = {
                    "item_code": item_code,
                    "qty": linea_sap.get("Quantity"),
                    "rate": linea_sap.get("Price") or 0,
                    "custom_linenum": linea_sap.get("LineNum"),
                    "use_serial_batch_fields": 0,
                    "batch_no": None,
                    "serial_no": None
                }

                if doctype_erp == "Sales Order" and erp_doc_name:
                    so_item = frappe.get_all("Sales Order Item", 
                        filters={"parent": erp_doc_name, "item_code": item_code, "custom_linenum": BaseLine},
                        fields=["name", "rate", "uom", "stock_uom", "conversion_factor", "warehouse"], limit=1)
                    if so_item:
                        nueva_entrada.update({
                            "sales_order": erp_doc_name,
                            "so_detail": so_item[0].name,
                            "rate": so_item[0].rate,
                            "uom": so_item[0].uom,
                            "stock_uom": so_item[0].stock_uom,
                            "conversion_factor": so_item[0].conversion_factor,
                            "warehouse": so_item[0].warehouse,
                            "delivery_note": None,
                            "dn_detail": None
                        })

                elif doctype_erp == "Delivery Note" and erp_doc_name:
                    print(f"El documento Base de la factura es: {doctype_erp} --- {erp_doc_name}")
                    print(f"Filtros: Docname: {erp_doc_name} ----- ItemCode: {item_code} ---- BaseLine: {BaseLine}")
                    print(f"Base entry: {base_entry} ------ DocNum: {doc_num} -- ItemCode: {ItemCode_SAP}")
                    dn_item = frappe.get_all("Delivery Note Item", 
                        filters={"parent": erp_doc_name, "item_code": item_code, "custom_linenum": BaseLine},
                        fields=["name", "rate", "uom", "stock_uom", "conversion_factor", "warehouse", "against_sales_order", "so_detail"], limit=1)
                    print(f"Valores de la Linea de la {doctype_erp} ---- ")
                    print(json.dumps(dn_item, indent=4))
                    if dn_item:
                        ref_name = dn_item[0].name
                        linea_sap["_ref_detail"] = ref_name  # <--- Guardamos la referencia única
                        nueva_entrada.update({
                            "delivery_note": erp_doc_name,
                            "dn_detail": ref_name,
                            "sales_order": dn_item[0].against_sales_order,
                            "so_detail": dn_item[0].so_detail,
                            "rate": dn_item[0].rate,
                            "uom": dn_item[0].uom,
                            "stock_uom": dn_item[0].stock_uom,
                            "conversion_factor": dn_item[0].conversion_factor,
                            "warehouse": dn_item[0].warehouse,
                            "custom_linenum": linea_sap.get("LineNum"),
                            "use_serial_batch_fields": 0,
                            "batch_no": None,
                            "serial_no": None
                        })
                # Si logramos armar la línea, la agregamos
                if nueva_entrada:
                    print(f"\n--- Agregando Línea al Delivery Note ---")
                    print(json.dumps(nueva_entrada, indent=4))
                    doc.append("items", nueva_entrada)

            # --- 6. Inserción Inicial ---
           
            doc.insert()
            si_name = doc.name
            doc.reload()

            # --- 7. Creación y Asignación de Lotes ---
            # Este bloque se ignora automáticamente si descarga_stock == 0 (venga de DN o sea Reserva)
            if descarga_stock == 1:
                todos_lotes = []
                for linea in lineas_sap:
                    line_num = linea.get("LineNum")
                    batch_numbers_linea = linea.get("BatchNumbers", [])
                    for lote in batch_numbers_linea:
                        lote["_LineNum"] = line_num
                        lote["Quantity"] = lote.get("Quantity", 0) 
                        todos_lotes.append(lote)
                print(f"Todos los obtenidos de SAP: ")
                print(json.dumps( todos_lotes, indent=4))
                        
                for item in doc.items:
                    line_num_erp = item.custom_linenum
                    lotes = [b for b in todos_lotes if b.get("_LineNum") == line_num_erp]
                    
                    if lotes:                            
                        bundle_id = crear_paquete_de_lotes(
                            item_code=item.item_code,
                            warehouse=item.warehouse,
                            lotes_sap=lotes,
                            voucher_type=doc.doctype,
                            voucher_no=si_name,
                            voucher_detail_no=item.name,  
                            company=company
                        )
                        item.serial_and_batch_bundle = bundle_id

            # --- 8. Guardado y Sometido Final ---
            doc.flags.sap_sales_invoice = True
            doc.save()
            doc.submit()
            frappe.db.commit()
            print(f"Sales Invoice Referenciada {doc.name} creada exitosamente.")

        except Exception as e:
            frappe.db.rollback()
            frappe.log_error(message=frappe.get_traceback(), title=f"Error Sales Invoice: DocNum {DocNum} -- DocEntry {DocEntry}")
            frappe.db.commit() 
            continue

    return None, None

def crear_factura_directa(lista_mapeo, mapeo_lista, doctype, company):
    """
    Procesa y crea una Sales Invoice directa (sin SO ni DN previa).
    """
    sap_id = lista_mapeo.get(mapeo_lista["key_field"])
    CardCode = lista_mapeo.get("CardCode")
    erp_key_field = mapeo_lista["erp_key_field"]
    DocEntry = lista_mapeo.get("DocEntry")

    SalesPersonCode = lista_mapeo.get("SalesPersonCode")
    shiptocode = lista_mapeo.get("ShipToCode")
    CardCode = lista_mapeo.get("CardCode")

    # --- 1. Lógica de Reserva y Llamada a SAP ---
    es_reserva = lista_mapeo.get("ReserveInvoice") == "tYES"
    descarga_stock = 0 if es_reserva else 1

    # Si la factura rebaja stock, necesitamos los lotes. 
    # Hacemos la segunda llamada a SAP usando el DocEntry.
    lineas_sap = lista_mapeo.get("DocumentLines", [])
    if descarga_stock == 1:
        try:
            print(f"Factura Directa rebaja stock. Obteniendo detalle de lotes para DocEntry: {DocEntry}")
            payload_completo = obtener_documento_completo_sap(DocEntry, company)
            lineas_sap = payload_completo.get("DocumentLines", [])
        except Exception as e:
            frappe.throw(f"Error al obtener el detalle completo de SAP para el DocEntry {DocEntry}: {str(e)}")

    # --- Validación de existencia ---
    if frappe.get_all(doctype, filters={erp_key_field: sap_id, "company": company , "docstatus" : 1}, limit=1):
        print(f"El documento SAP {sap_id} ya existe en ERPNext. Omitiendo...")
        return

    # --- Búsqueda de Entidades Principales ---
    cardcode_erpnext = frappe.get_value(
        "Customer",
        filters={
            "custom_cardcode": CardCode,
            "custom_company": company
        },
        fieldname="name"
    )
    if not cardcode_erpnext:
        frappe.throw(f"El cliente {CardCode} no existe en ERPNext")
    
    price_list_erpnext = frappe.get_value(
        "Customer",
        filters={
            "custom_cardcode": CardCode,
            "custom_company": company
        },
        fieldname="default_price_list"
    )

    direccion_envio = frappe.get_value(
        "Address",
        filters={
            "address_title": shiptocode,
            "custom_company": company,
            "address_type" : "Shipping",
            "custom_cardcode": CardCode
        },
        fieldname="name"
    )

    dato_vendedor = frappe.get_value(
        "Sales Person",
        filters={
            "custom_salesemployeecode": SalesPersonCode,
            "custom_company": company
        },
        fieldname="name"
    )

    sales_team = []
    if dato_vendedor:
        sales_team.append({
            "sales_person": dato_vendedor,
            "allocated_percentage": 100.0
        })

    dato_lista = {}
    # --- Construcción de Cabecera ---
    docdate_sap = lista_mapeo.get("DocDate")
    docduedate_sap = lista_mapeo.get("DocDueDate")
    fecha_doc = getdate(docdate_sap[:10]) if docdate_sap else None
    fecha_vencimiento = getdate(docduedate_sap[:10]) if docduedate_sap else None
    
    # fecha_final_entrega = None
    # if fecha_vencimiento:
    #     fecha_hoy_obj = getdate(nowdate())
    #     fecha_final_entrega = fecha_hoy_obj if fecha_vencimiento < fecha_hoy_obj else fecha_vencimiento
    #     dato_lista["delivery_date"] = fecha_final_entrega

    campos_head = mapeo_lista.get("sap_fields", {}).get("head", {})
    for erp_field, sap_field in campos_head.items():
        valor = lista_mapeo.get(sap_field)
        if isinstance(valor, (list, dict)):
            continue
        elif erp_field == "posting_date":
            valor = fecha_doc
        elif erp_field == "due_date":
            valor = fecha_vencimiento
        elif erp_field == "currency" and valor == "QTZ":
            valor = "GTQ"
        elif erp_field == "shipping_address_name":
            valor = direccion_envio
        elif erp_field == "customer":
            valor = cardcode_erpnext

        dato_lista[erp_field] = valor

    dato_lista["company"] = company
    dato_lista["update_stock"] = descarga_stock

    # --- Impuestos (Taxes) ---
    taxes_erpnext = []
    if lineas_sap and lineas_sap[0].get("TaxCode"):
        plantilla_erpnext = frappe.db.get_value("Sales Taxes and Charges Template",
            {"custom_taxcode": lineas_sap[0].get("TaxCode"), "company": company}, "name")
        
        if plantilla_erpnext:
            dato_lista["taxes_and_charges"] = plantilla_erpnext
            for tax in frappe.get_doc("Sales Taxes and Charges Template", plantilla_erpnext).get("taxes"):
                taxes_erpnext.append({
                    "charge_type": tax.charge_type, "account_head": tax.account_head,
                    "description": tax.description, "rate": flt(tax.rate),
                    "included_in_print_rate": tax.included_in_print_rate, "cost_center": tax.cost_center
                })
            dato_lista["taxes"] = taxes_erpnext

    # --- Detalle de Ítems ---
    items = []
    for linea in lineas_sap:
        ItemCode_SAP = linea.get("ItemCode")
        ItemCode_ERPNEXT_query = frappe.db.sql("""
            SELECT T0.name
            FROM `tabItem` T0
            INNER JOIN `tabItem Default` T1
                ON T0.name = T1.parent
            WHERE T0.custom_itemcode = %s
            AND T1.company = %s
            LIMIT 1
        """, (ItemCode_SAP, company), as_list=True)

        # CORRECCIÓN: Manejar lista vacía
        if ItemCode_ERPNEXT_query:
            ItemCode_ERPNEXT = ItemCode_ERPNEXT_query[0][0]
        else:
            ItemCode_ERPNEXT = ItemCode_SAP # Fallback preventivo

        warehouse_sap = linea.get("WarehouseCode")
        warehouse_erpnext = frappe.get_value(
            "Warehouse",
            filters={"custom_warehousecode":warehouse_sap,"company" : company},
            fieldname="name"
        )

        uom_sap = linea.get("UoMEntry")
        uom_erpnext = frappe.get_value(
            "UOM",
            filters={"custom_absentry":uom_sap,"custom_company" : company},
            fieldname="name"
        )

        item_data = {}
        campos_lineas = mapeo_lista.get("sap_fields", {}).get("DocumentLines", {}) 
        
        item_data = {
            "item_code": ItemCode_ERPNEXT,
            "warehouse": warehouse_erpnext,
            "uom": uom_erpnext,
            "included_in_print_rate": 1,
            "custom_linenum": linea.get("LineNum"), # Vital guardar el LineNum de SAP para cruzar los lotes luego
            "use_serial_batch_fields": 0, # Fundamental para v15
            "batch_no": None,
            "serial_no": None
        }
        # if fecha_final_entrega: item_data["delivery_date"] = fecha_final_entrega

        for erp_field, sap_field in campos_lineas.items():
            valor = linea.get(sap_field)
            if erp_field == "discount_percentage": 
                item_data[erp_field] = valor if valor > 0 else 0
            elif erp_field == "net_rate": 
                precio_despues_impuestos = linea.get("PriceAfterVAT")
                item_data["rate"] = precio_despues_impuestos
                continue
            elif erp_field not in ["item_code", "warehouse", "uom"]: 
                item_data[erp_field] = valor
                print(f"se agregado el precio con impuestos")
        items.append(item_data)

    dato_lista["custom_company"] = company
    #dato_lista["docstatus"] = 1
    dato_lista["disable_rounded_total"] = 1
    dato_lista["selling_price_list"] = price_list_erpnext

    doc_data = {
        "doctype": doctype,
        **dato_lista,
        "sales_team": sales_team,
        "items": items
    }

    print(f"Datos: {json.dumps(doc_data, indent=2, default=str)}")
    doc = frappe.get_doc(doc_data)
    doc.flags.ignore_permissions = True 
    doc.insert()
    si_name = doc.name

    # --- 8. Vinculación de Lotes (Serial and Batch Bundles) ---
    if descarga_stock == 1:
        todos_lotes = []
        for linea in lineas_sap:
            line_num = linea.get("LineNum")

            batch_numbers_linea = linea.get("BatchNumbers", [])

            for lote in batch_numbers_linea:
                lote["_LineNum"] = line_num
                # Normalizar la cantidad del lote para ERPNext (Cantidad SAP / Factor de Conversión)
                lote_qty_sap = lote.get("Quantity", 0)
                lote["Quantity"] = lote_qty_sap 
                todos_lotes.append(lote)

        for item in doc.items:
            line_num_erp = item.custom_linenum
            # Desactivar y limpiar legacy fields (ya lo hicimos en el append, pero se mantiene por seguridad)
            item.use_serial_batch_fields = 0
            item.batch_no = None
            item.serial_no = None
            
            lotes = [b for b in todos_lotes if b.get("_LineNum") == line_num_erp]
            
            if lotes:                            
                bundle_id = crear_paquete_de_lotes(
                    item_code=item.item_code,
                    warehouse=item.warehouse,
                    lotes_sap=lotes,
                    voucher_type=doc.doctype,
                    voucher_no=si_name,
                    voucher_detail_no=item.name,  
                    company=company
                )
                item.serial_and_batch_bundle = bundle_id
                
            else:
                sap_line = next((l for l in lineas_sap if l.get("LineNum") == line_num_erp), None)
                item.qty = sap_line.get("Quantity", 0) if sap_line else 0
        # --- 5. Guardar los cambios y someter ---
        for item in doc.items:
            print("------------------------")
            print(item.item_code)
            print("qty:", item.qty)
            print("uom:", item.uom)
            print("conversion:", item.conversion_factor)
            print("stock_qty:", item.stock_qty)

        
    # --- 9. Guardado Final ---
    doc.flags.sap_sales_invoice = True
    doc.save()
    doc.submit()
    frappe.db.commit()
    print(f"Sales Invoice Directa {doc.name} creada exitosamente.")



def crear_paquete_de_lotes(item_code, warehouse, lotes_sap, voucher_type, voucher_no, voucher_detail_no, company ):
    # 1. Determinar el tipo de transacción
    if voucher_type == "Sales Invoice":
        type_of_transaction = "Outward"
    else:
        type_of_transaction = "Inward"

    # 2. Crear el documento principal del paquete (Cabecera)
    bundle = frappe.get_doc({
        "doctype": "Serial and Batch Bundle",
        "voucher_type": voucher_type,
        "voucher_no": voucher_no,
        "voucher_detail_no": voucher_detail_no,  # <--- CLAVE ÚNICA DE LA FILA (item.name)
        "item_code": item_code,
        "warehouse": warehouse,
        "type_of_transaction": type_of_transaction,
        "company": company,
        "has_batch_no": 1
    })

    print(f"Creando Bundle {type_of_transaction} para {item_code} en {warehouse} (Fila: {voucher_detail_no})...")

    # 3. Procesar e insertar cada lote en las líneas del Bundle
    for lote in lotes_sap:
        sap_batch_number = lote["BatchNumber"]
        qty = lote["Quantity"]

        # Buscar el lote real en ERPNext usando custom_batchnum
        batch_name = frappe.get_value(
            "Batch",
            {"custom_batchnum": sap_batch_number, "item": item_code},
            "name"
        )

        if not batch_name:
            frappe.throw(
                f"Sincronización abortada: No se encontró el lote '{sap_batch_number}' "
                f"para el artículo '{item_code}' en ERPNext."
            )

        print(f"Lote mapeado: SAP({sap_batch_number}) -> ERPNext({batch_name}). Qty: {qty}")
        
        # En v15/v16 para Outward la cantidad se mantiene positiva en la tabla entries
        # bundle.append("entries", {
        #     "batch_no": batch_name,
        #     "qty": qty, 
        #     "warehouse": warehouse
        # })
        nueva_entrada_lote = {
            "batch_no": batch_name,
            "qty": qty, 
            "warehouse": warehouse
        }

        # 2. Imprimimos en consola con formato JSON legible
        print(f"\n--- Agregando Lote {batch_name} al Bundle ---")
        print(json.dumps(nueva_entrada_lote, indent=4))

        # 3. Anexamos la variable al documento
        bundle.append("entries", nueva_entrada_lote)

    
    # 4. Insertar el Bundle en estado Borrador
    bundle.insert(ignore_permissions=True)

    return bundle.name


def obtener_documento_completo_sap(docentry, company):
    session = login_sap(company)
    url = f"https://apisap.yaesta.com.gt/b1s/v2/Invoices({docentry})"
    response = session.get(url)
    print(f"Inicio de sesión exitoso para DocEntry {docentry}")
    response.raise_for_status()
    return response.json()