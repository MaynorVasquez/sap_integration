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
            # --- 1. Obtener la nota de entrega completa desde SAP (con lotes) ---
            full_data = obtener_delivery_note_completo(DocEntry, company)

            DeliveryNote = frappe.db.get_value(doctype, 
                                    {"custom_docnum": DocNum, 
                                    "custom_docentry" : DocEntry,
                                    "company": company,
                                    "docstatus": 1}, 
                                    "name")
            if DeliveryNote:
                print(f"La DeliveryNote ya existe DocEntry: {DocEntry} -- DocNum: {DocNum}")
                continue
            
            # --- 2. Identificar Referencias en SAP ---
            DocumentReferences = full_data.get("DocumentReferences", [])
            sap_so_dict = {}
            sap_si_dict = {}
            
            for ref in DocumentReferences:
                ref_type = ref.get("RefObjType")
                if ref_type == "rot_SalesOrder":
                    sap_so_dict[ref.get("RefDocEntr")] = ref.get("RefDocNum")
                elif ref_type == "rot_SalesInvoice":
                    sap_si_dict[ref.get("RefDocEntr")] = ref.get("RefDocNum")

            print(f"Referencias SAP - Orders: {sap_so_dict} | Invoices: {sap_si_dict}")

            # --- 3. Determinar Modo y Construir Cabecera ---
            doc = None
            modo_creacion = None
            documento_base_global = None

            if sap_si_dict:
                print(f"Estas una Delivery note con base Factura de Cliente (Reserva) {sap_si_dict}")
                # ESCENARIO 1: Priorizamos la Factura de Cliente (Reserva)
                modo_creacion = "Factura"
                erpnext_si_names = {}
                
                for base_entry, doc_num in sap_si_dict.items():
                    si_name = frappe.db.get_value("Sales Invoice", {"custom_docnum": doc_num, "company": company}, "name")
                    if si_name:
                        erpnext_si_names[base_entry] = si_name

                if not erpnext_si_names:
                    frappe.throw("La Factura de SAP no existe en ERPNext.")
                
                print(f"Creando DN a partir de Factura de Reserva: {erpnext_si_names}")
                documento_base_global = list(erpnext_si_names.values())[0]
                doc = make_dn_from_si(documento_base_global)
                dict_nombres_base = erpnext_si_names

            elif sap_so_dict:
                # ESCENARIO 2: Solo hay Orden de Venta
                print(f"Estas una Delivery note con base Orden de venta {sap_so_dict}")
                modo_creacion = "Orden"
                erpnext_so_names = {}
                
                for base_entry, doc_num in sap_so_dict.items():
                    so_name = frappe.db.get_value("Sales Order", {"custom_docnum": doc_num, "company": company}, "name")
                    if so_name:
                        erpnext_so_names[base_entry] = so_name
                        
                if not erpnext_so_names:
                    frappe.throw("La Orden de Venta de SAP no existe en ERPNext.")

                print(f"Creando DN a partir de Orden de Venta: {erpnext_so_names}")
                documento_base_global = list(erpnext_so_names.values())[0]
                doc = make_dn_from_so(documento_base_global)
                dict_nombres_base = erpnext_so_names
                
            else:
                frappe.throw(f"No se encontraron referencias válidas (SO o SI) en SAP para DocEntry {DocEntry}")
            
            # Configuramos campos generales
            doc.custom_docnum = full_data.get("DocNum")
            doc.custom_entry = full_data.get("DocEntry")
            doc.items = [] # Vaciamos líneas predeterminadas
            
            lineas_sap = full_data.get("DocumentLines", [])
            print(f"Líneas de SAP a procesar: {len(lineas_sap)} en Modo {modo_creacion}")

            # --- 4. Procesamiento de Líneas (Dinámico según el Modo) ---
            for linea_sap in lineas_sap:
                base_entry = linea_sap.get("BaseEntry")
                ItemCode_SAP = linea_sap.get("ItemCode")
                BaseLine = linea_sap.get("BaseLine")

                # Traducción del ItemCode
                ItemCode_ERPNEXT_query = frappe.db.sql("""
                    SELECT T0.name
                    FROM `tabItem` T0
                    INNER JOIN `tabItem Default` T1 ON T0.name = T1.parent
                    WHERE T0.custom_itemcode = %s AND T1.company = %s LIMIT 1
                """, (ItemCode_SAP, company), as_list=True)
                item_code = ItemCode_ERPNEXT_query[0][0] if ItemCode_ERPNEXT_query else ItemCode_SAP 
                
                # Identificamos el nombre del documento padre para esta línea
                doc_padre_erpnext = dict_nombres_base.get(base_entry) or documento_base_global
                if not doc_padre_erpnext:
                    continue 
                print(f"Procesando línea SAP BaseEntry {base_entry} -> ERPNext Doc: {doc_padre_erpnext}")

                nueva_entrada_lote = None
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

                # LÓGICA MODO FACTURA
                if modo_creacion == "Factura":
                    si_item = frappe.get_all("Sales Invoice Item", 
                        filters={"parent": doc_padre_erpnext, "item_code": item_code, "custom_linenum": BaseLine},
                        fields=["name", "rate", "uom", "stock_uom", "conversion_factor", "warehouse", "sales_order", "so_detail"],
                        limit=1
                    )
                    print(f"detalle de item de la Factura: {si_item}")
                    #continue  # Saltamos si no encontramos el item en la Factura

                    if si_item:
                        ref_name = si_item[0].name
                        linea_sap["_ref_detail"] = ref_name  # <--- Guardamos la referencia única
                        nueva_entrada_lote.update({
                            "against_sales_invoice": doc_padre_erpnext,            
                            "si_detail": ref_name,
                            "against_sales_order": si_item[0].sales_order, # Heredado de la Factura
                            "so_detail": si_item[0].so_detail,      # Heredado de la Factura
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
                # LÓGICA MODO ORDEN DE VENTA
                elif modo_creacion == "Orden":
                    so_item = frappe.get_all("Sales Order Item", 
                        filters={"parent": doc_padre_erpnext, "item_code": item_code, "custom_linenum": BaseLine},
                        fields=["name", "rate", "uom", "stock_uom", "conversion_factor", "warehouse"],
                        limit=1
                    )
                    print(f"detalle de item de la Orden: {so_item}")
                    if so_item:
                        ref_name = so_item[0].name
                        linea_sap["_ref_detail"] = ref_name  # <--- Guardamos la referencia única
                        nueva_entrada_lote.update( {
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

                # Si logramos armar la línea, la agregamos
                if nueva_entrada_lote:
                    print(f"\n--- Agregando Línea al Delivery Note ---")
                    print(json.dumps(nueva_entrada_lote, indent=4))
                    doc.append("items", nueva_entrada_lote)
        
            # Insertamos el documento
            doc.insert()
            dn_name = doc.name
            doc.reload() # Importante para los lotes

            # --- 5. Procesar cada línea y asociar lotes ---
            print(f"Procensando lotes para cada línea del Delivery Note Paso ####5 {dn_name}...")
            todos_lotes = []
            for linea in lineas_sap:
                line_num = linea.get("LineNum")
                for lote in linea.get("BatchNumbers", []):
                    lote["_LineNum"] = line_num
                    lote["Quantity"] = lote.get("Quantity", 0)
                    todos_lotes.append(lote)

            print(f"Todos los obtenidos de SAP: ")
            print(json.dumps( todos_lotes, indent=4))


            for item in doc.items:
                ref_detail_erp = item.si_detail if modo_creacion == "Factura" else item.so_detail
                line_num_erp = item.custom_linenum

                 # Buscamos la línea de SAP exacta basándonos en esa referencia
                sap_line = next((l for l in lineas_sap if l.get("_ref_detail") == ref_detail_erp), None)

                if not sap_line:
                    print(
                        f"⚠️ No existe línea SAP para custom_linenum={line_num_erp}. "
                        f"Item ERPNext={item.item_code}"
                    )
                    continue
            
                # Rescatamos el LineNum real y original con el que SAP nos mandó esta fila
                line_num_sap = sap_line.get("LineNum")

                # Obtenemos los lotes respetando el LineNum de SAP
                lotes = [
                    b for b in todos_lotes
                    if b.get("_LineNum") == line_num_sap
                ]
                
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
                    # sap_line = next((l for l in lineas_sap if l.get("LineNum") == line_num_erp), None)
                    # item.qty = sap_line.get("Quantity", 0) if sap_line else 0
                    item.qty = sap_line.get("Quantity", 0)

            # --- 6. Guardar y Someter ---
            for item in doc.items:
                print("------------------------")
                print("Item:", item.item_code)
                print("Linked SO:", item.against_sales_order)
                print("Linked SI:", item.against_sales_invoice)

            doc.save()
            doc.submit()
            frappe.db.commit()
            print(f"Delivery Note {doc.name} sometida exitosamente.")

        except Exception as e:
            frappe.db.rollback()
            frappe.log_error(message=frappe.get_traceback(), title=f"Error DN SAP {sap_id}")
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