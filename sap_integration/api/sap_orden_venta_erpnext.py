import frappe
from frappe import _
import json
import traceback  # Importación añadida
from datetime import datetime
from frappe.utils import flt
from frappe.utils import getdate, nowdate
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual
from erpnext.controllers.accounts_controller import update_child_qty_rate
from sap_integration.utils.logs_transactional import logs_transactional

@frappe.whitelist()
def sincronizar_orden_venta_erpnext(docname=None):
    doctype_logs = "Sincronizacion Orden de Venta SAP"
    doctype_target =  "Sales Order"
    doctype_mapeo = "Mapeo Orden De Venta SAP"
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

    sap_key_field = mapeo_lista["key_field"]
    erp_key_field = mapeo_lista["erp_key_field"]

    for lista_mapeo in registros_sap:
        try:
            sap_id = lista_mapeo.get(sap_key_field)
            SalesPersonCode = lista_mapeo.get("SalesPersonCode")
            shiptocode = lista_mapeo.get("ShipToCode")
            CardCode = lista_mapeo.get("CardCode")
            
            dato_existente = frappe.get_all(
                doctype,
                filters={
                    erp_key_field: sap_id,
                    "company": company
                },
                fields=["name"],
                limit=1
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
            
            cardcode_erpnext = frappe.get_value(
                "Customer",
                filters={
                    "custom_cardcode": CardCode,
                    "custom_company": company
                },
                fieldname="name"
            )
            
            price_list_erpnext = frappe.get_value(
                "Customer",
                filters={
                    "custom_cardcode": CardCode,
                    "custom_company": company
                },
                fieldname="default_price_list"
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

            campos_head = mapeo_lista.get("sap_fields", {}).get("head", {})
            dato_lista = {}

            docdate_sap = lista_mapeo.get("DocDate")
            docdate_erpnext = datetime.strptime(
                docdate_sap,
                "%Y-%m-%dT%H:%M:%SZ"
            ).date() if docdate_sap else None
            
            docduedate_sap = lista_mapeo.get("DocDueDate")
            docduedate_erpnext = datetime.strptime(
                docduedate_sap,
                "%Y-%m-%dT%H:%M:%SZ"
            ).date() if docduedate_sap else None

            for erp_field, sap_field in campos_head.items():
                valor = lista_mapeo.get(sap_field)
                if isinstance(valor, (list, dict)):
                    continue
                elif erp_field == "po_date":
                    valor = docdate_erpnext
                elif erp_field == "custom_docduedate":
                    valor = docduedate_erpnext
                elif erp_field == "currency" and valor == "QTZ":
                    valor = "GTQ"
                elif erp_field == "shipping_address_name":
                    valor = direccion_envio
                elif erp_field == "customer":
                    valor = cardcode_erpnext

                dato_lista[erp_field] = valor

            dato_lista["company"] = company

            fecha_final_entrega = None
            if docduedate_erpnext:
                fecha_entrega_obj = getdate(docduedate_erpnext)
                fecha_hoy_obj = getdate(nowdate())
                if fecha_entrega_obj < fecha_hoy_obj:
                    fecha_final_entrega = fecha_hoy_obj
                else:
                    fecha_final_entrega = fecha_entrega_obj
                # Asignar al encabezado
                dato_lista["delivery_date"] = fecha_final_entrega

            lineas_sap = lista_mapeo.get("DocumentLines", [])

            plantilla_erpnext = None
            taxes_erpnext = []
            multiplicador_impuesto = 1.0
            if lineas_sap:
                codigo_impuesto_sap = lineas_sap[0].get("TaxCode")
                if codigo_impuesto_sap:
                    plantilla_erpnext = frappe.db.get_value(
                        "Sales Taxes and Charges Template",
                        filters={
                            "custom_taxcode": codigo_impuesto_sap,
                            "company": company
                        },
                        fieldname="name"
                    )
            if plantilla_erpnext:                
                # 2. Cargamos el Doc de la plantilla para leer sus detalles
                doc_plantilla = frappe.get_doc("Sales Taxes and Charges Template", plantilla_erpnext)
                porcentaje_total_impuestos = 0.0
                # 3. Iteramos sobre la tabla 'taxes' de la plantilla y armamos la nuestra
                for tax in doc_plantilla.get("taxes"):
                    porcentaje_total_impuestos += flt(tax.rate)
                    taxes_erpnext.append({
                        "charge_type": tax.charge_type,
                        "account_head": tax.account_head,
                        "description": tax.description,
                        "rate": tax.rate,
                        # Dependiendo de tu config, a veces es útil forzar estos campos de Frappe:
                        "included_in_print_rate": tax.included_in_print_rate,
                        "cost_center": tax.cost_center
                    })
                if porcentaje_total_impuestos > 0:
                    multiplicador_impuesto = 1.0 + (porcentaje_total_impuestos / 100.0)

            # 4. Inyectamos tanto la cabecera como las líneas al payload final
            if plantilla_erpnext:
                dato_lista["taxes_and_charges"] = plantilla_erpnext
                if taxes_erpnext:
                    dato_lista["taxes"] = taxes_erpnext
                
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
                
                for erp_field, sap_field in campos_lineas.items():
                    valor = linea.get(sap_field)
                    if erp_field == "item_code":
                        valor = ItemCode_ERPNEXT
                    elif erp_field == "warehouse":
                        valor = warehouse_erpnext
                    elif erp_field == "uom":
                        valor = uom_erpnext
                    elif erp_field == "discount_percentage":
                        if valor > 0:
                            item_data["discount_percentage"] = valor
                        else:
                            # Si es negativo o cero, lo neutralizamos en ERPNext
                            item_data["discount_percentage"] = 0
                        continue
                    elif erp_field == "net_rate":
                        precio_despues_impuestos = linea.get("PriceAfterVAT")
                        item_data["rate"] = precio_despues_impuestos                 
                        continue
                          
                    item_data[erp_field] = valor
                
                if fecha_final_entrega:
                    item_data["delivery_date"] = fecha_final_entrega

                item_data["included_in_print_rate"] = 1
                
                    
                items.append(item_data)
            
            dato_lista["custom_company"] = company
            dato_lista["disable_rounded_total"] = 1
            dato_lista["selling_price_list"] = price_list_erpnext
            
            doc_data = {}

            if dato_existente:
                docname = dato_existente[0]["name"]
                doc = frappe.get_doc(doctype, docname)
                
                # Mapear las líneas actuales de ERPNext indexadas por tu identificador de SAP
                # Reemplaza 'custom_linenum' por el campo que uses para amarrar la línea de SAP
                lineas_erpnext_actuales = {d.custom_linenum: d for d in doc.items}

                if doc.docstatus == 0:
                    #ESTADO BORRADOR: Actualización total estándar
                    try:
                        # Tu lógica actual para reescribir/actualizar el documento completo
                        ###**************************************

                        campos_protegidos = ["name", "doctype", "docstatus", "creation", "modified", "owner", "amended_from"]
                        for key, value in dato_lista.items():
                            if key not in campos_protegidos:
                                doc.set(key, value)
                        
                        # CORRECCIÓN: Actualizar el equipo de ventas si existe en SAP
                        if sales_team:
                            doc.set("sales_team", []) # Limpiar el actual
                            for st in sales_team:
                                doc.append("sales_team", st)

                        # ==========================================
                        # INDEXAR LINEAS EXISTENTES ERPNEXT
                        # ==========================================
                        lineas_actuales = {}
                        for row in doc.items:
                            lineas_actuales[row.custom_linenum] = row

                        lineas_sap_keys = set()

                        # ==========================================
                        # RECORRER LINEAS SAP
                        # ==========================================
                        for item in items:
                            sap_line = item.get("custom_linenum")
                            if sap_line is None:
                                continue

                            lineas_sap_keys.add(sap_line)

                            # EXISTE -> ACTUALIZAR
                            if sap_line in lineas_actuales:
                                fila = lineas_actuales[sap_line]
                                if flt(fila.delivered_qty) > 0 or flt(fila.billed_amt) > 0:
                                    print(f"Línea {sap_line} omitida. Tiene entregas o facturación.")
                                    continue

                                for campo, valor in item.items():
                                    if campo in ("doctype", "name", "parent", "parentfield", "parenttype", "idx"):
                                        continue
                                    fila.set(campo, valor)
                            
                            # NO EXISTE -> CREAR
                            else:
                                doc.append("items", item)
                                
                                print(f"Nueva línea agregada: {sap_line}")

                        # ==========================================
                        # DETECTAR LINEAS ELIMINADAS EN SAP
                        # ==========================================
                        for sap_line, fila in lineas_actuales.items():
                            if sap_line in lineas_sap_keys:
                                continue

                            if flt(fila.delivered_qty) > 0 or flt(fila.billed_amt) > 0:
                                frappe.log_error(
                                    title="SAP Sync",
                                    message=f"La línea {sap_line} fue eliminada en SAP pero tiene movimientos en ERPNext. OV: {doc.name}"
                                )
                                continue

                            doc.remove(fila)
                            print(f"Línea eliminada: {sap_line}")
                        doc.save(ignore_permissions=True)
                        doc.ignore_pricing_rule = 1
                        frappe.db.commit()
                        doc_json_limpio = doc.as_dict()
                        print(f"OV en Borrador {docname} actualizada exitosamente.")
                        print(f"Datos: {json.dumps(doc, indent=2, default=str)}")
                        respuesta = f"Orden de venta Actualizada correctamente: {sap_id}"
                        logs_transactional("ERPNEXT Logs Transactional Sales Order", 
                                            sap_id, "Success" ,doc_json_limpio, respuesta, 
                                            "Mapeo Orden De Venta SAP",
                                            "Sales Order")

                        
                    except Exception as e:
                        frappe.db.rollback()
                        frappe.log_error(title=f"Error en actualización Borrador {docname}", message=frappe.get_traceback())
                        respuesta = f"Error al actualizar Borrador Orden de venta: {frappe.get_traceback()}"
                        logs_transactional("ERPNEXT Logs Transactional Sales Order", 
                                            sap_id, "Error" ,doc, respuesta, 
                                            "Mapeo Orden De Venta SAP",
                                            "Sales Order")

                elif doc.docstatus == 1:
                    continue
                    #ESTADO ENVIADO:se usa función nativa de erpnext 
                    try:
                        trans_items = []
                        lineas_procesadas_sap = set()
                        lineas_modificadas_existentes = []
                        hubo_cambios = False

                        # 1. Procesar Modificaciones y Nuevas Líneas desde SAP
                        for item_sap in items:
                            num_linea_sap = item_sap.get("custom_linenum")
                            
                            lineas_procesadas_sap.add(num_linea_sap)
                            
                            fila_existente = lineas_erpnext_actuales.get(num_linea_sap)
                            
                            if fila_existente:
                                # CASO A: La línea ya existe -> Validar si cambió Qty o Rate
                                # if fila_existente.qty != item_sap.get("qty") or fila_existente.rate != item_sap.get("rate"):
                                #     hubo_cambios = True
                                cambio_detectado = (
                                    fila_existente.qty != item_sap.get("qty") or 
                                    fila_existente.rate != item_sap.get("rate") or
                                    fila_existente.warehouse != item_sap.get("warehouse") or
                                    fila_existente.uom != item_sap.get("uom")
                                )
                                if cambio_detectado:
                                    hubo_cambios = True
                                    # Guardamos los datos destino para el post-procesamiento genérico
                                    lineas_modificadas_existentes.append({
                                        "docname": fila_existente.name,
                                        "warehouse": item_sap.get("warehouse"),
                                        "uom": item_sap.get("uom")
                                    })
                                trans_items.append({
                                    "docname": fila_existente.name,  # ID único de la fila en ERPNext (ej: "items-001")
                                    "item_code": item_sap.get("item_code"),
                                    "qty": item_sap.get("qty"),
                                    "rate": item_sap.get("rate"),
                                    "uom": item_sap.get("uom")
                                })
                            else:
                                # CASO B: La línea no existe en ERPNext -> Es NUEVA
                                hubo_cambios = True
                                trans_items.append({
                                    # Al NO enviar 'docname', ERPNext sabe que debe insertarla
                                    "item_code": item_sap.get("item_code"),
                                    "qty": item_sap.get("qty"),
                                    "rate": item_sap.get("rate"),
                                    "warehouse": item_sap.get("warehouse"),
                                    "delivery_date": item_sap.get("delivery_date"),
                                    "uom": item_sap.get("uom")

                                })

                        # 2. Procesar Eliminaciones (Líneas en ERPNext que ya no vienen en el JSON de SAP)
                        for num_linea_erp, fila_erp in lineas_erpnext_actuales.items():
                            if num_linea_erp not in lineas_procesadas_sap:
                                hubo_cambios = True

                        # 3. Ejecutar la función nativa si el payload sufrió alguna alteración
                        if hubo_cambios:
                            # Guardamos los IDs de las líneas que ya existían antes de actualizar
                            ids_lineas_originales = [d.name for d in lineas_erpnext_actuales.values()]
                            # Esta función mágica valida internamente si las líneas afectadas tienen o no DN/Invoice
                            update_child_qty_rate('Sales Order', json.dumps(trans_items, default=str), doc.name)
                            # ==========================================
                            # 4. POST-PROCESAMIENTO: ASIGNAR custom_linenum
                            # ==========================================
                            doc.reload() # Recargamos el documento para obtener los nuevos IDs generados
                            # APARTADO A: Actualizar filas EXISTENTES que cambiaron de Almacén o UOM
                            for mod in lineas_modificadas_existentes:
                                frappe.db.set_value(
                                    "Sales Order Item", 
                                    mod["docname"], 
                                    {
                                        "warehouse": mod["warehouse"]
                                    }
                                )

                            # Filtramos cuáles ítems de SAP eran los nuevos
                            lineas_nuevas_sap = [it for it in items if it.get("custom_linenum") not in lineas_erpnext_actuales]
                            print(f"Nuevas lineas: {lineas_nuevas_sap}")
                            # Filtramos cuáles filas en ERPNext son las recién creadas
                            filas_recien_creadas = [d for d in doc.items if d.name not in ids_lineas_originales]
                            # Emparejamos la fila de ERPNext con el ítem de SAP
                            for fila_erp in filas_recien_creadas:
                                for sap_item in lineas_nuevas_sap:
                                    # Validamos que coincida el artículo y la cantidad
                                    if fila_erp.item_code == sap_item.get("item_code") and flt(fila_erp.qty) == flt(sap_item.get("qty")):                                        
                                        # Inyectamos el custom_linenum directo a la base de datos
                                        frappe.db.set_value(
                                            "Sales Order Item", 
                                            fila_erp.name, 
                                            {
                                                "custom_linenum": sap_item.get("custom_linenum"),
                                                "warehouse": sap_item.get("warehouse")
                                            }
                                        )
                                        
                                        # Lo quitamos de la lista para evitar duplicados si hay artículos idénticos
                                        lineas_nuevas_sap.remove(sap_item)
                                        break
                            frappe.db.commit()
                            print(f"OV Enviada {doc.name} sincronizada con éxito (Cambios/Altas/Bajas procesados).")
                        else:
                            print(f"OV Enviada {doc.name} se encuentra idéntica a SAP. No requiere actualización.")

                    except Exception as e:
                        frappe.db.rollback()
                        frappe.log_error(title=f"Error en actualización quirúrgica OV {doc.name}", message=frappe.get_traceback())
                        respuesta = f"Error al actualizar los articulos: {frappe.get_traceback()}"
                        logs_transactional("ERPNEXT Logs Transactional Sales Order", 
                                            sap_id, "Error" , trans_items, respuesta, 
                                            "Mapeo Orden De Venta SAP",
                                            "Sales Order")

            else:
                # CREACIÓN DE DOCUMENTO NUEVO
                doc_data = {
                    "doctype": doctype,
                    **dato_lista,
                    "sales_team": sales_team,
                    "items": items
                }
                print(f"Datos: {json.dumps(doc_data, indent=2, default=str)}")
                
                doc = frappe.get_doc(doc_data)
                doc.flags.sap_sales_order_sync = True
                doc.flags.ignore_permissions = True 
                doc.insert()
                frappe.db.commit()
                respuesta = f"Orden de venta creada correctamente {sap_id}"
                logs_transactional("ERPNEXT Logs Transactional Sales Order", 
                                   sap_id, "Success" , doc_data, respuesta, 
                                   "Mapeo Orden De Venta SAP",
                                   "Sales Order")
                print(f"Orden de venta creada con exito....")
                
        except Exception as e:
            frappe.log_error(
                message=frappe.get_traceback(),
                title=f"Error al procesar dato {sap_id}"
            )
            respuesta = frappe.get_traceback()
            logs_transactional("ERPNEXT Logs Transactional Sales Order", 
                                   sap_id, "Error" , doc_data, respuesta, 
                                   "Mapeo Orden De Venta SAP",
                                   "Sales Order")
            continue

    return None, None