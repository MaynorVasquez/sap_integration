import frappe
from frappe import _
import json
import traceback  # Importación añadida
from datetime import datetime
from frappe.utils import flt, add_days,today
from frappe.utils import getdate, nowdate
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual
from sap_integration.utils.logs_transactional import logs_transactional
# Importamos ambas funciones con un alias para evitar conflictos
from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note as make_dn_from_so
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_delivery_note as make_dn_from_si
from sap_integration.api.sap_auth import login_sap
from erpnext.stock.doctype.batch.batch import get_batch_qty


@frappe.whitelist()
def sincronizar_notas_entregas_erpnext(docname=None):
    doctype_logs = "Sincronizacion Nota de Entrega SAP"
    doctype_target =  "Delivery Note"
    doctype_mapeo = "Mapeo Nota de Entrega SAP"
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
        sap_id = lista_mapeo.get(sap_key_field)
        DocEntry = lista_mapeo.get("DocEntry")
        DocNum = lista_mapeo.get("DocNum")
        cancel_status = lista_mapeo.get("CancelStatus")
        print(f"Valor de cancelación {cancel_status}")

        if not DocEntry:
            continue

        try:
            # ============================================================
            # 1. OBTENER DELIVERY NOTE COMPLETA DESDE SAP
            # ============================================================
            full_data = obtener_delivery_note_completo(DocEntry, company)
            cancel_status = full_data.get("CancelStatus")
            if cancel_status == "csCancellation":
                # Obtener las líneas del documento SAP
                document_lines = full_data.get("DocumentLines", [])
                print(f"Se inicia proceso de cancelación de Nota de entrega")

                if document_lines:
                    # DocEntry del documento original
                    base_entry = document_lines[0].get("BaseEntry")
                    if base_entry:
                        # Buscar la factura original en ERPNext
                        # usando el custom_docentry que guardaste desde SAP
                        print(f"Delivery Note que se anulara es: {base_entry}")
                        facturas = frappe.get_all(
                            "Delivery Note",
                            filters={
                                "custom_docentry": base_entry
                            },
                            fields=["name", "docstatus"]
                        )
                        if facturas:
                            factura = frappe.get_doc(
                                "Delivery Note",
                                facturas[0].name
                            )
                            if factura.docstatus == 1:
                                factura.flags.ignore_links = True
                                factura.cancel()
                                frappe.db.commit()
                                print(f"¡Éxito! La Nota de entrega {factura} ha sido cancelada.")
                                continue

            DeliveryNote = frappe.db.get_value(
                doctype,
                {
                    "custom_docnum": DocNum,
                    "company": company,
                    "docstatus": 1
                },
                "name"
            )

            if DeliveryNote:
                print(
                    f"La DeliveryNote ya existe "
                    f"DocEntry: {DocEntry} -- DocNum: {DocNum}"
                )
                continue

            # ============================================================
            # 2. OBTENER REFERENCIAS DE SAP
            # ============================================================
            DocumentReferences = full_data.get("DocumentReferences", [])
            lineas_sap = full_data.get("DocumentLines", [])

            sap_so_dict = {}
            sap_si_dict = {}

            for ref in DocumentReferences:
                ref_type = ref.get("RefObjType")
                ref_entry = ref.get("RefDocEntr")
                ref_num = ref.get("RefDocNum")

                if not ref_entry:
                    continue

                if ref_type == "rot_SalesOrder":
                    sap_so_dict[ref_entry] = ref_num

                elif ref_type == "rot_SalesInvoice":
                    sap_si_dict[ref_entry] = ref_num

            print(
                f"Referencias SAP - Orders: {sap_so_dict} | "
                f"Invoices: {sap_si_dict}"
            )

            # ============================================================
            # 3. DETERMINAR EL DOCUMENTO BASE REAL
            #
            #    IMPORTANTE:
            #    DocumentLines.BaseType es la fuente de verdad.
            #
            #    17 = Sales Order
            #    13 = Sales Invoice
            # ============================================================
            bases_lineas = {}

            for linea in lineas_sap:
                base_type = linea.get("BaseType")
                base_entry = linea.get("BaseEntry")

                print(
                    f"Línea SAP {linea.get('LineNum')} -> "
                    f"BaseType={base_type}, "
                    f"BaseEntry={base_entry}, "
                    f"BaseLine={linea.get('BaseLine')}"
                )

                if base_type not in (17, 13):
                    continue

                if not base_entry:
                    continue

                bases_lineas.setdefault(base_type, set()).add(base_entry)

            print(f"Bases detectadas en DocumentLines: {bases_lineas}")

            tipos_detectados = set(bases_lineas.keys())

            # ============================================================
            # VALIDACIÓN
            # ============================================================

            if not tipos_detectados:
                frappe.throw(
                    f"No se encontraron líneas con BaseType 17 o 13 "
                    f"para la Delivery Note SAP {DocNum} "
                    f"(DocEntry {DocEntry})"
                )

            # ------------------------------------------------------------
            # CASO: HAY ORDEN Y FACTURA EN LAS MISMAS LÍNEAS
            # ------------------------------------------------------------
            if tipos_detectados == {17, 13}:
                frappe.throw(
                    f"La Delivery Note SAP {DocNum} contiene líneas "
                    f"basadas tanto en Orden de Venta (BaseType 17) "
                    f"como en Factura de Cliente (BaseType 13). "
                    f"Base SO: {bases_lineas.get(17, set())} | "
                    f"Base SI: {bases_lineas.get(13, set())}. "
                    f"El proceso actual no soporta documentos base mixtos."
                )

            # ============================================================
            # VARIABLES GENERALES
            # ============================================================
            doc = None
            modo_creacion = None
            documento_base_global = None
            dict_nombres_base = {}

            # ============================================================
            # 4A. DELIVERY NOTE BASADA EN ORDEN DE VENTA
            # ============================================================
            if tipos_detectados == {17}:

                modo_creacion = "Orden"

                entradas_so = bases_lineas[17]

                print(f"Delivery Note basada en Orden(es) de Venta. BaseEntry encontrados: {entradas_so}")

                erpnext_so_names = {}

                for base_entry in entradas_so:

                    # BaseEntry = DocEntry de SAP
                    # Usamos DocumentReferences únicamente para resolver
                    # el DocNum correspondiente.
                    doc_num = sap_so_dict.get(base_entry)

                    if not doc_num:
                        frappe.throw(
                            f"No se encontró DocumentReference para "
                            f"Sales Order BaseEntry={base_entry} "
                            f"en Delivery Note SAP {DocNum}."
                        )

                    so_name = frappe.db.get_value(
                        "Sales Order",
                        {
                            "custom_docnum": doc_num,
                            "company": company
                        },
                        "name"
                    )

                    if so_name:
                        erpnext_so_names[base_entry] = so_name

                if not erpnext_so_names:
                    frappe.throw(
                        f"La Orden de Venta de SAP no existe en ERPNext. "
                        f"BaseEntry: {entradas_so}"
                    )

                print(f"Creando DN a partir de Orden de Venta: {erpnext_so_names}")

                # ============================================================
                # SOMETER TODAS LAS ORDENES DE VENTA
                # ============================================================
                for base_entry, so_name in erpnext_so_names.items():
                    print(f"Verificando estado de Orden de Venta {so_name}")

                    so = frappe.get_doc("Sales Order", so_name)
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

                documento_base_global = list(erpnext_so_names.values())[0]
                doc = make_dn_from_so(documento_base_global)
                dict_nombres_base = erpnext_so_names

            # ============================================================
            # 4B. DELIVERY NOTE BASADA EN FACTURA
            # ============================================================
            elif tipos_detectados == {13}:

                modo_creacion = "Factura"
                entradas_si = bases_lineas[13]

                print(f"Delivery Note basada en Factura de Cliente. "
                    f"BaseEntry encontrados: {entradas_si}")

                # --------------------------------------------------------
                # Igual que con SO, tu función actual genera la cabecera
                # desde un documento base único.
                # --------------------------------------------------------
                if len(entradas_si) > 1:
                    frappe.throw(
                        f"La Delivery Note SAP {DocNum} contiene "
                        f"varias Facturas como documento base: "
                        f"{entradas_si}. "
                        f"El proceso actual espera una sola Factura."
                    )

                erpnext_si_names = {}

                for base_entry in entradas_si:

                    # BaseEntry = DocEntry de SAP
                    doc_num = sap_si_dict.get(base_entry)

                    if not doc_num:
                        frappe.throw(
                            f"No se encontró DocumentReference para "
                            f"Sales Invoice BaseEntry={base_entry} "
                            f"en Delivery Note SAP {DocNum}."
                        )

                    si_name = frappe.db.get_value(
                        "Sales Invoice",
                        {
                            "custom_docnum": doc_num,
                            "company": company
                        },
                        "name"
                    )

                    if si_name:
                        erpnext_si_names[base_entry] = si_name

                if not erpnext_si_names:
                    frappe.throw(
                        f"La Factura de SAP no existe en ERPNext. "
                        f"BaseEntry: {entradas_si}"
                    )

                print(
                    f"Creando DN a partir de Factura de Reserva: "
                    f"{erpnext_si_names}"
                )

                documento_base_global = list(erpnext_si_names.values())[0]

                doc = make_dn_from_si(documento_base_global)

                dict_nombres_base = erpnext_si_names

            # ============================================================
            # 5. CONFIGURACIÓN GENERAL DE DELIVERY NOTE
            # ============================================================
            doc.custom_docnum = full_data.get("DocNum")
            doc.custom_docentry = full_data.get("DocEntry")
            doc.custom_comments = full_data.get("Comments")

            # Vaciamos las líneas que Frappe haya creado automáticamente
            doc.items = []

            print(f"Líneas de SAP a procesar: {len(lineas_sap)} "
                f"en Modo {modo_creacion}")

            # ============================================================
            # 6. PROCESAMIENTO DE LÍNEAS
            # ============================================================
            for linea_sap in lineas_sap:

                base_type = linea_sap.get("BaseType")
                base_entry = linea_sap.get("BaseEntry")
                ItemCode_SAP = linea_sap.get("ItemCode")
                BaseLine = linea_sap.get("BaseLine")

                print(
                    f"\nProcesando línea SAP:"
                    f"\n  LineNum: {linea_sap.get('LineNum')}"
                    f"\n  ItemCode: {ItemCode_SAP}"
                    f"\n  BaseType: {base_type}"
                    f"\n  BaseEntry: {base_entry}"
                    f"\n  BaseLine: {BaseLine}"
                )

                # --------------------------------------------------------
                # VALIDAMOS QUE LA LÍNEA CORRESPONDA AL MODO
                # --------------------------------------------------------
                if modo_creacion == "Orden" and base_type != 17:
                    frappe.throw(
                        f"Inconsistencia en Delivery Note SAP {DocNum}. "
                        f"La cabecera fue determinada como Orden de Venta, "
                        f"pero la línea {linea_sap.get('LineNum')} tiene "
                        f"BaseType={base_type}."
                    )

                if modo_creacion == "Factura" and base_type != 13:
                    frappe.throw(
                        f"Inconsistencia en Delivery Note SAP {DocNum}. "
                        f"La cabecera fue determinada como Factura, "
                        f"pero la línea {linea_sap.get('LineNum')} tiene "
                        f"BaseType={base_type}."
                    )

                # --------------------------------------------------------
                # Validar BaseEntry
                # --------------------------------------------------------
                doc_padre_erpnext = dict_nombres_base.get(base_entry)

                if not doc_padre_erpnext:
                    frappe.throw(
                        f"No se encontró documento base en ERPNext "
                        f"para la línea SAP {linea_sap.get('LineNum')}. "
                        f"BaseType={base_type}, "
                        f"BaseEntry={base_entry}, "
                        f"BaseLine={BaseLine}"
                    )

                print(
                    f"Procesando línea SAP "
                    f"BaseType={base_type} "
                    f"BaseEntry={base_entry} "
                    f"-> ERPNext Doc: {doc_padre_erpnext}"
                )

                # ========================================================
                # TRADUCCIÓN DEL ITEM
                # ========================================================
                ItemCode_ERPNEXT_query = frappe.db.sql(
                    """
                    SELECT T0.name
                    FROM `tabItem` T0
                    INNER JOIN `tabItem Default` T1
                        ON T0.name = T1.parent
                    WHERE T0.custom_itemcode = %s
                      AND T1.company = %s
                    LIMIT 1
                    """,
                    (ItemCode_SAP, company),
                    as_list=True
                )

                item_code = (
                    ItemCode_ERPNEXT_query[0][0]
                    if ItemCode_ERPNEXT_query
                    else ItemCode_SAP
                )

                # ========================================================
                # ESTRUCTURA BASE DE LA LÍNEA
                # ========================================================
                nueva_entrada_lote = {
                    "item_code": item_code,
                    "qty": linea_sap.get("Quantity"),
                    "rate": linea_sap.get("Price") or 0,
                    "warehouse": linea_sap.get("WarehouseCode"),
                    "custom_linenum": linea_sap.get("LineNum"),
                    "use_serial_batch_fields": 0,
                    "batch_no": None,
                    "serial_no": None
                }

                # ========================================================
                # 6A. LÓGICA FACTURA
                # ========================================================
                if modo_creacion == "Factura":
                    si_item = frappe.get_all(
                        "Sales Invoice Item",
                        filters={"parent": doc_padre_erpnext,"item_code": item_code,"custom_linenum": BaseLine},
                        fields=["name","rate","uom","stock_uom","conversion_factor","warehouse","sales_order","so_detail"],
                        limit=1
                    )
                    print(f"Detalle de item de la Factura: {si_item}")

                    if not si_item:
                        frappe.throw(
                            f"No se encontró la línea de Factura "
                            f"en ERPNext para:"
                            f"\nFactura: {doc_padre_erpnext}"
                            f"\nItem: {item_code}"
                            f"\nBaseLine SAP: {BaseLine}"
                            f"\nLineNum SAP: {linea_sap.get('LineNum')}"
                        )

                    ref_name = si_item[0].name

                    # Guardamos referencia única entre SAP y ERPNext
                    linea_sap["_ref_detail"] = ref_name

                    nueva_entrada_lote.update({
                        "against_sales_invoice": doc_padre_erpnext,
                        "si_detail": ref_name,

                        # Heredados de la factura
                        "against_sales_order": si_item[0].sales_order,
                        "so_detail": si_item[0].so_detail,

                        "rate": si_item[0].rate,
                        "uom": si_item[0].uom,
                        "stock_uom": si_item[0].stock_uom,
                        "conversion_factor": si_item[0].conversion_factor,
                        "warehouse": si_item[0].warehouse,

                        "custom_linenum": linea_sap.get("LineNum"),
                        "use_serial_batch_fields": 0,
                        "batch_no": None,
                        "serial_no": None
                    })

                # ========================================================
                # 6B. LÓGICA ORDEN DE VENTA
                # ========================================================
                elif modo_creacion == "Orden":

                    so_item = frappe.get_all(
                        "Sales Order Item",
                        filters={
                            "parent": doc_padre_erpnext, "item_code": item_code,"custom_linenum": BaseLine},
                        fields=["name","rate","uom","stock_uom","conversion_factor", "warehouse","custom_linenum"],
                        limit=1
                    )

                    print(f"Detalle de item de la Orden: {so_item}")

                    if not so_item:
                        frappe.throw(
                            f"No se encontró la línea de Orden de Venta "
                            f"en ERPNext para:"
                            f"\nOrden: {doc_padre_erpnext}"
                            f"\nItem: {item_code}"
                            f"\nBaseLine SAP: {BaseLine}"
                            f"\nLineNum SAP: {linea_sap.get('LineNum')}"
                        )

                    ref_name = so_item[0].name

                    # Guardamos referencia única entre SAP y ERPNext
                    linea_sap["_ref_detail"] = ref_name
                    nueva_entrada_lote.update({
                        "against_sales_order": doc_padre_erpnext,
                        "so_detail": ref_name,
                        "rate": so_item[0].rate,
                        "uom": so_item[0].uom,
                        "stock_uom": so_item[0].stock_uom,
                        "conversion_factor": so_item[0].conversion_factor,
                        "warehouse": so_item[0].warehouse,
                        "custom_linenum": linea_sap.get("LineNum"),
                        "use_serial_batch_fields": 0,
                        "batch_no": None,
                        "serial_no": None
                    })

                # ========================================================
                # AGREGAR LÍNEA
                # ========================================================
                if nueva_entrada_lote:

                    print(
                        "\n--- Agregando Línea al Delivery Note ---"
                    )

                    print(
                        json.dumps(
                            nueva_entrada_lote,
                            indent=4
                        )
                    )

                    doc.append(
                        "items",
                        nueva_entrada_lote
                    )

            # ============================================================
            # 7. INSERTAR DELIVERY NOTE
            # ============================================================

            doc.flags.sap_delivery_note_sync = True
            doc.ignore_pricing_rule = 1
            doc.insert()
            
            #doc.flags.sap_delivery_note_sync = True
            dn_name = doc.name

            # #doc.reload()

            # ============================================================
            # 8. PROCESAR LOTES
            # ============================================================
            print(
                f"Procesando lotes para cada línea del "
                f"Delivery Note Paso ####5 {dn_name}..."
            )

            todos_lotes = []

            for linea in lineas_sap:

                line_num = linea.get("LineNum")

                for lote in linea.get("BatchNumbers", []):

                    lote["_LineNum"] = line_num
                    lote["Quantity"] = lote.get("Quantity", 0)

                    todos_lotes.append(lote)

            print("Todos los obtenidos de SAP:")

            print(
                json.dumps(
                    todos_lotes,
                    indent=4
                )
            )

            # ============================================================
            # 9. ASOCIAR LOTES A CADA LÍNEA ERPNext
            # ============================================================
            for item in doc.items:

                if modo_creacion == "Factura":
                    ref_detail_erp = item.si_detail
                else:
                    ref_detail_erp = item.so_detail

                line_num_erp = item.custom_linenum

                # --------------------------------------------------------
                # Buscar línea SAP exacta
                # --------------------------------------------------------
                sap_line = next(
                    (
                        l for l in lineas_sap
                        if l.get("_ref_detail") == ref_detail_erp
                    ),
                    None
                )

                if not sap_line:

                    print(
                        f"⚠️ No existe línea SAP para "
                        f"custom_linenum={line_num_erp}. "
                        f"Item ERPNext={item.item_code}"
                    )

                    continue

                # --------------------------------------------------------
                # LineNum original de SAP
                # --------------------------------------------------------
                line_num_sap = sap_line.get("LineNum")
                item.custom_linenum = sap_line.get("LineNum")

                # --------------------------------------------------------
                # Obtener lotes correspondientes
                # --------------------------------------------------------
                lotes = [
                    b
                    for b in todos_lotes
                    if b.get("_LineNum") == line_num_sap
                ]

                # ========================================================
                # CREAR SERIAL AND BATCH BUNDLE
                # ========================================================
                if lotes:
                    print(f"lotes encontrados ----- {lotes}")

                    bundle_id = crear_paquete_de_lotes(
                        item_code=item.item_code,
                        warehouse=item.warehouse,
                        lotes_sap=lotes,
                        voucher_type="Delivery Note",
                        voucher_no=dn_name,
                        voucher_detail_no=item.name,
                        company=company
                    )

                    item.serial_and_batch_bundle = bundle_id

                else:

                    item.qty = sap_line.get(
                        "Quantity",
                        0
                    )

            # ============================================================
            # 10. DEBUG FINAL
            # ============================================================
            for item in doc.items:

                print("------------------------")
                print("Item:", item.item_code)
                print(
                    "Linked SO:",
                    item.against_sales_order
                )
                print(
                    "Linked SI:",
                    item.against_sales_invoice
                )
                print(
                    "SO Detail:",
                    item.so_detail
                )
                print(
                    "SI Detail:",
                    item.si_detail
                )
                print(
                    "Custom Line Num:",
                    item.custom_linenum
                )

            # ============================================================
            # 11. GUARDAR Y SOMETER
            # ============================================================
            doc.save()

            doc.submit()

            frappe.db.commit()

            print(
                f"Delivery Note {doc.name} "
                f"sometida exitosamente."
            )

        except Exception as e:

            frappe.db.rollback()

            frappe.log_error(
                message=frappe.get_traceback(),
                title=f"Error DN SAP {sap_id}"
            )

            frappe.db.commit()

            continue

    return None, None



def crear_paquete_de_lotes(item_code, warehouse, lotes_sap, voucher_type, voucher_no, voucher_detail_no, company ):
    # 1. Determinar el tipo de transacción
    if voucher_type == "Delivery Note":
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
        ExpiryDate = lote.get("ExpiryDate")
        custom_batchnum = lote.get("BatchNumber")  # Usamos el BatchNumber de SAP como custom_batchnum


        batch_name = obtener_o_crear_batch( item_code, ExpiryDate, custom_batchnum)


        if not batch_name:
            print(f"Error: No se encontró el lote '{sap_batch_number}' para el artículo '{item_code}' en ERPNext.")
            frappe.throw(
                f"Sincronización abortada: No se encontró el lote '{sap_batch_number}' "
                f"para el artículo '{item_code}' en ERPNext."
            )
            

        qty_batch_disponible = obtener_stock_lote(item_code, warehouse, batch_name)
        print(f"Stock disponible para lote {batch_name} en almacén {warehouse}: {qty_batch_disponible}")

        print(f"Lote mapeado: SAP({sap_batch_number}) -> ERPNext({batch_name}). Qty: {qty}")

        if qty > qty_batch_disponible:
            print(f"⚠️ Advertencia: La cantidad solicitada ({qty}) para el lote {batch_name} "
                  f"excede el stock disponible ({qty_batch_disponible}). Ajustando a stock disponible.")
            Material_Receipt = crear_stock_entry_entrada(item_code, qty, batch_name, warehouse)
            print(f"Material Receipt creado: {Material_Receipt}")

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

def obtener_stock_lote(item_code, warehouse, batch_no):
    """
    Obtiene el stock disponible de un lote específico
    para un artículo y almacén.

    Retorna float.
    """

    try:
        stock = get_batch_qty(
            batch_no=batch_no,
            warehouse=warehouse,
            item_code=item_code,
            for_stock_levels=True
        )

        return flt(stock or 0)

    except Exception:
        frappe.log_error(
            message=frappe.get_traceback(),
            title=f"Error consultando stock lote {batch_no}"
        )
        raise

def obtener_o_crear_batch( item_code, expiry_date=None, custom_batchnum=None):
    if not custom_batchnum:
        return None

    # Buscar lote existente
    batch_name = frappe.db.get_value(
        "Batch",
        {
            "custom_batchnum": custom_batchnum,
            "item": item_code
        },
        "name"
    )
    

    if batch_name:
        print(f"✅ Lote existente encontrado: {batch_name} para item {item_code} con custom_batchnum {custom_batchnum}")
        return batch_name

    print(f"No se encontró lote existente para item {item_code} con custom_batchnum {custom_batchnum}. Creando nuevo lote...")

    batch_no = f"{item_code}-{custom_batchnum}"

    # Verifica lote vencido y ajusta la fecha si es necesario
    expiry_date = str(expiry_date).strip()
    # Eliminar la parte de hora/timezone
    if "T" in expiry_date:
        expiry_date = expiry_date.split("T")[0]
    if expiry_date and getdate(expiry_date) < getdate(today()):
        hoy = getdate(nowdate())
        expiry_date = add_days(hoy, 5)
        print(f"⚠ Lote vencido detectado para {item_code} lote {batch_no}. Fecha ajustada a {expiry_date}.")

    # Crear lote
    batch_doc = frappe.get_doc({
        "doctype": "Batch",
        "batch_id": batch_no,
        "item": item_code,
        "expiry_date": expiry_date,
        "custom_batchnum": custom_batchnum
    })

    batch_doc.insert(ignore_permissions=True)

    print(f"✅ Lote creado-----: {batch_doc.name} para item {item_code} con custom_batchnum {custom_batchnum}")

    return batch_doc.name

def crear_stock_entry_entrada(item_code, qty, batch_no, warehouse, valuation_rate=1):

    try:
        if not item_code:
            raise ValueError("No se indicó item_code.")

        if not qty or qty <= 0:
            raise ValueError(
                f"Cantidad inválida para {item_code}: {qty}"
            )

        if not warehouse:
            raise ValueError(
                f"No se indicó bodega para {item_code}."
            )

        # ==================================================
        # Crear Stock Entry
        # ==================================================

        se = frappe.new_doc("Stock Entry")

        se.stock_entry_type = "Material Receipt"
        se.purpose = "Material Receipt"

        item_data = {
            "item_code": item_code,
            "qty": qty,
            "basic_rate": valuation_rate,
            "valuation_rate": valuation_rate,
            "t_warehouse": warehouse
        }

        # Asignar lote
        if batch_no:
            item_data["batch_no"] = batch_no
            item_data["use_serial_batch_fields"] = 1

        se.append("items", item_data)

        print(
            f"📦 Material Receipt preparado: "
            f"{item_code} | Lote: {batch_no or 'N/A'} | "
            f"Cantidad: {qty} | Bodega: {warehouse} | "
            f"Costo: {valuation_rate}"
        )

        # ==================================================
        # Insertar y enviar
        # ==================================================

        se.flags.ignore_permissions = True

        se.insert(ignore_permissions=True)
        se.submit()

        frappe.db.commit()

        mensaje = (
            f"🚚 Stock Entry creado y enviado: {se.name} | "
            f"{item_code} | Lote: {batch_no or 'N/A'} | "
            f"Cantidad: {qty} | Bodega: {warehouse}"
        )

        print(mensaje)

        return se.name

    except Exception as e:
        frappe.db.rollback()
        mensaje = (
            f"Error creando Material Receipt: "
            f"Item={item_code}, "
            f"Lote={batch_no}, "
            f"Cantidad={qty}, "
            f"Bodega={warehouse}: {str(e)}"
        )
        frappe.log_error(
            frappe.get_traceback(),
            mensaje
        )
        raise

def obtener_delivery_note_completo(docentry, company):
    session = login_sap(company)
    url = f"https://apisap.yaesta.com.gt/b1s/v2/DeliveryNotes({docentry})"
    response = session.get(url)
    print(f"Inicio de sesión exitoso para DocEntry {docentry}")
    response.raise_for_status()
    return response.json()

