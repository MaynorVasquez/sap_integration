import frappe
from frappe import _
import json
import traceback  # Importación añadida
from datetime import datetime
from frappe.utils import flt, cint
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

        if not DocEntry:
            continue

        try:
            # ============================================================
            # 1. OBTENER DELIVERY NOTE COMPLETA DESDE SAP
            # ============================================================
            full_data = obtener_delivery_note_completo(DocEntry, company)

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
            print("\n========================================")
            print("ANTES DE INSERTAR DELIVERY NOTE")
            print("========================================")

            for item in doc.items:
                print(
                    f"idx={item.idx} | "
                    f"name={item.name} | "
                    f"item_code={item.item_code} | "
                    f"custom_linenum={item.custom_linenum} | "
                    f"so_detail={item.so_detail} | "
                    f"si_detail={item.si_detail}"
                )

            doc.flags.sap_delivery_note_sync = True
            doc.insert()
            #doc.flags.sap_delivery_note_sync = True
            dn_name = doc.name

            #doc.reload()

            print("\n========================================")
            print("DESPUES DE INSERTAR / RELOAD")
            print("========================================")

            for item in doc.items:
                print(
                    f"idx={item.idx} | "
                    f"name={item.name} | "
                    f"item_code={item.item_code} | "
                    f"custom_linenum={item.custom_linenum} | "
                    f"so_detail={item.so_detail} | "
                    f"si_detail={item.si_detail}"
                )

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


def obtener_delivery_note_completo(docentry, company):
    session = login_sap(company)
    url = f"https://apisap.yaesta.com.gt/b1s/v2/DeliveryNotes({docentry})"
    response = session.get(url)
    print(f"Inicio de sesión exitoso para DocEntry {docentry}")
    response.raise_for_status()
    return response.json()

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