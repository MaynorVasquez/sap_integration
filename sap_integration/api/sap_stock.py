import frappe
from frappe import _
import json
import traceback  # Importación añadida
from datetime import datetime
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual
from frappe.utils import nowdate, nowtime, getdate, today, getdate, nowdate, add_days
from frappe.utils import flt
import time

@frappe.whitelist()
def sincronizar_lista_stock(docname=None, doctype_logs=None, almacen=None):

    if not doctype_logs:
        doctype_logs = "Sincronizacion Inventario SAP"
    usa_paginacion = True
    doctype_target = "Stock Entry"
    doctype_mapeo = "Mapeo Inventario SAP"
    key_erpnext = "custom_itemcode"
    key_sap = "ItemCode"
    sap_whscode = None
    config = frappe.get_doc(doctype_mapeo, docname)
    resultados = []
    empresas_a_procesar = []

    # 🔹 Caso 1: viene almacen → solo una empresa
    if almacen:
        sap_whscode = frappe.db.get_value("Warehouse", almacen, "custom_warehousecode")
        company = frappe.db.get_value("Warehouse", almacen, "company")

        # buscar la empresa en el config
        for empresa in config.company_detalle:
            if empresa.company == company:
                empresas_a_procesar.append(empresa)
                break

    # 🔹 Caso 2: no viene almacen → todas las empresas
    else:
        empresas_a_procesar = config.company_detalle

    # 🔹 Ejecutar proceso
    for empresa in empresas_a_procesar:
        resultado = procesar_empresa_individual(
            config,
            empresa,
            docname,
            procesar_datos,
            doctype_logs,
            doctype_target,
            doctype_mapeo,
            key_sap,
            key_erpnext,
            usa_paginacion,
            sap_whscode
        )

        resultados.append({
            "company": empresa.company,
            "endpoint": empresa.endpoint,
            "resultado": resultado
        })

    return resultados

def procesar_datos(registros_sap, mapeo_lista, doctype, company,debug_messages):
    items_in = []
    items_out = []

    registros_unicos = set()
    lotes_vistos_en_sap = set()

    for registro_sap in registros_sap:
        try:
            codigo_sap = registro_sap.get("ItemCode")
            item_data = frappe.db.sql("""
                SELECT T0.name, T0.disabled
                FROM `tabItem` T0
                INNER JOIN `tabItem Default` T1
                    ON T0.name = T1.parent
                WHERE T0.custom_itemcode = %s
                AND T1.company = %s
                LIMIT 1
            """, (codigo_sap, company), as_dict=True)
            if not item_data:
                debug_messages.append(f"❌ Omitido: El código SAP {codigo_sap} no existe en ERPNext.")
                print(f"❌ Omitido: El código SAP {codigo_sap} no existe en ERPNext.")
                continue
            if item_data[0].disabled:
                debug_messages.append(f"🚫 Omitido: El producto {item_data[0].name} ({codigo_sap}) está deshabilitado.")
                print(f"🚫 Omitido: El producto {item_data[0].name} ({codigo_sap}) está deshabilitado.")
                continue
            item_code = item_data[0]["name"]
            whs_code = registro_sap.get("WhsCode")

            warehouse= frappe.get_value(
                "Warehouse",
                filters={"custom_warehousecode": whs_code, "company": company},
                fieldname="name"
            )
            raw_batch = (registro_sap.get("BatchNum") or "").strip()
            custom_batchnum = (registro_sap.get("BatchNum") or "").strip()
            batch = f"{item_code}-{raw_batch}"
            cantidad_sap = flt(registro_sap.get("Quantity") or 0)
            fecha_exp = registro_sap.get("ExpDate")
            valuation_rate = flt(registro_sap.get("AvgPrice") or 0)

            # Verifica lote vencido y ajusta la fecha si es necesario
            if fecha_exp and getdate(fecha_exp) < getdate(today()):
                hoy = getdate(nowdate())
                fecha_exp = add_days(hoy, 5)
                print(f"⚠ Lote vencido detectado para {item_code} lote {batch}. Fecha ajustada a {fecha_exp}.")

            if not item_code or not warehouse or not batch:
                debug_messages.append(f"✗ Registro incompleto: {registro_sap}")
                continue

            cantidad_erp = flt(get_stock_qty(item_code, warehouse, batch))
            cantidad_erp_corregida = max(cantidad_erp, 0)  # evita negativos
            diferencia = round(cantidad_sap - cantidad_erp_corregida, 6)

            debug_messages.append(
                f"📦 {item_code} | Lote: {batch or 'SIN LOTE'} | Almacén: {warehouse} | SAP: {cantidad_sap} | ERP: {cantidad_erp} (corr: {cantidad_erp_corregida}) | Dif: {diferencia}"
            )
            print(f"📦 {item_code} | Lote: {batch or 'SIN LOTE'} | Almacén: {warehouse} | SAP: {cantidad_sap} | ERP: {cantidad_erp} (corr: {cantidad_erp_corregida}) | Dif: {diferencia}")
            lotes_vistos_en_sap.add((item_code, batch, warehouse))
            # Si no hay diferencia, se omite
            if abs(diferencia) < 0.000001:
                print(f"🚫 Se omite {item_code} ya que no hay diferencia")
                continue
            print(f"✅ sigue el proceso porque si hay diferena de {diferencia}")
            clave_unica = f"{item_code}|{batch}|{warehouse}|{diferencia}"
            if clave_unica in registros_unicos:
                debug_messages.append(f"🔁 Registro duplicado ignorado: {clave_unica}")
                continue

            registros_unicos.add(clave_unica)
            print(f"valores de registro unicos: {registros_unicos}")

            # Crear lote si no existe
            if batch:
                lote = frappe.get_value("Batch", {"batch_id": batch, "item": item_code}, "name")
                if not lote:
                    lote_doc = frappe.new_doc("Batch")
                    lote_doc.batch_id = batch
                    lote_doc.item = item_code
                    lote_doc.expiry_date = fecha_exp
                    lote_doc.custom_batchnum = custom_batchnum
                    lote_doc.flags.ignore_validate = True
                    lote_doc.flags.ignore_mandatory = True
                    lote_doc.insert(ignore_permissions=True)
                    debug_messages.append(f"✔ Lote creado: {batch}")
                else:
                    try:
                        frappe.db.set_value("Batch", lote, {
                            "expiry_date": fecha_exp,
                            "custom_batchnum": custom_batchnum
                        })
                    except Exception as e:
                        debug_messages.append(f"⚠ No se pudo actualizar fecha de lote {batch}: {e}")

            movimiento = {
                "item_code": item_code,
                "qty": abs(diferencia),
                "warehouse": warehouse,
                "valuation_rate": valuation_rate
            }
            print(f"Movimiento a realizar: {movimiento}")

            if batch:
                movimiento["batch_no"] = batch

            if diferencia > 0:
                items_in.append(movimiento)
                debug_messages.append(f"✔ Preparado para entrada: +{diferencia} del lote {batch or 'SIN LOTE'}")
            else:
                items_out.append(movimiento)
                debug_messages.append(f"✔ Preparado para salida: -{abs(diferencia)} del lote {batch or 'SIN LOTE'}")

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Error en procesar_registro_con_lote")
            debug_messages.append(f"✗ Error procesando registro SAP: {e} | Registro: {registro_sap}")

    try:        
        # Filtramos almacenes involucrados (esto se puede quedar parecido)
        warehouses_lista = list({item[2] for item in lotes_vistos_en_sap})
        if not warehouses_lista: return None, None
        
        wh_filter = tuple(warehouses_lista) if len(warehouses_lista) > 1 else f"('{warehouses_lista[0]}')"
        print(f"almacen {wh_filter}")
        lotes_erp = frappe.db.sql(f"""
            Select 
                T0.item_code,
                T1.batch_no,
                T0.warehouse,
                sum(T1.qty) qty
            from `tabSerial and Batch Bundle` T0
            JOIN `tabSerial and Batch Entry` T1 on T1.parent = T0.name
            WHERE T0.warehouse IN {wh_filter}
            and T0.docstatus = 1
            group by 
            T0.item_code,
            T0.warehouse,
            T1.batch_no
            having 
            sum(T1.qty) > 0
            ;
        """, as_dict=True)
   
        for row in lotes_erp:
            clave_erp = (row.item_code, row.batch_no, row.warehouse)
            
            # Ahora comparamos ERPNext contra ERPNext (nombres iguales)
            if clave_erp not in lotes_vistos_en_sap:
                movimiento = {
                    "item_code": row.item_code,
                    "qty": row.qty,
                    "warehouse": row.warehouse,
                    "valuation_rate": 0,
                    "batch_no": row.batch_no
                }
                items_out.append(movimiento)
                print(f"🗑️ Limpieza: {row.item_code} lote {row.batch_no}  QTY: {row.qty} no está en SAP, se retira.")
                debug_messages.append(f"🗑️ Limpieza: {row.item_code} lote {row.batch_no} QTY: {row.qty} no está en SAP, se retira.")
    except Exception as e:
        debug_messages.append(f"⚠ Error detectando lotes faltantes: {e}")

    # Crear los Stock Entry si hay datos
    if items_in:
        crear_stock_entry_multiple(items_in, tipo="In", debug_messages=debug_messages)
    if items_out:
        crear_stock_entry_multiple(items_out, tipo="Out", debug_messages=debug_messages)
    return None, None


def crear_stock_entry_multiple(items, tipo="In", debug_messages=None):
    if not items:
        if debug_messages is not None:
            debug_messages.append("⚠ Lista de ítems vacía. No se creó Stock Entry.")
        return

    tipo_entrada = "Material Receipt" if tipo == "In" else "Material Issue"

    try:
        se = frappe.new_doc("Stock Entry")
        se.stock_entry_type = tipo_entrada
        se.purpose = tipo_entrada

        for idx, item in enumerate(items, start=1):
            try:
                item_code = item.get("item_code")
                qty = item.get("qty")
                batch_no = item.get("batch_no")
                warehouse = item.get("warehouse")
                valuation_rate = item.get("valuation_rate")

                # Verificar si el ítem usa lotes
                usa_lotes = frappe.get_value("Item", item_code, "has_batch_no")

                item_data = {
                    "item_code": item_code,
                    "qty": item["qty"],
                    "basic_rate":  valuation_rate,
                    "valuation_rate": valuation_rate
                }

                # Asignar lote si aplica
                if batch_no and usa_lotes:
                    item_data["batch_no"] = batch_no
                    item_data["use_serial_batch_fields"] = 1

                if tipo == "In":
                    item_data["t_warehouse"] = warehouse
                else:
                    item_data["s_warehouse"] = warehouse

                se.append("items", item_data)

                if debug_messages is not None:
                    debug_messages.append(f"✅ {tipo_entrada} -- Ítem #{idx} agregado al Stock Entry -- {batch_no} -- {qty} -- {warehouse}")

            except Exception as item_error:
                mensaje = (
                    f"Error en ítem #{idx}\n"
                    f"Item: {item_code}\n"
                    f"Lote: {batch_no}\n"
                    f"Cantidad: {qty}\n"
                    f"Bodega: {warehouse}\n"
                    f"Detalle: {str(item_error)}"
                )

                frappe.log_error(frappe.get_traceback(), mensaje)

                if debug_messages is not None:
                    debug_messages.append("❌ " + mensaje)

                # Detiene todo el proceso
                raise

        if not se.items:
            if debug_messages is not None:
                debug_messages.append("✗ No se agregó ningún ítem válido al Stock Entry.")
            return

        #se.flags.ignore_mandatory = True
        se.flags.ignore_permissions = True
        se.insert(ignore_permissions=True)
        se.submit()
        frappe.db.commit()
        if debug_messages is not None:
            debug_messages.append(
                f"🚚 Stock Entry creado y enviado: {se.name} ({tipo_entrada}) con {len(se.items)} ítems."
            )
        print(f"✅ 🚚 Stock Entry creado y enviado: {se.name} ({tipo_entrada}) con {len(se.items)} ítems.")

    except Exception as e:
        frappe.db.rollback()

        mensaje = f"Error creando Stock Entry ({tipo_entrada}): {str(e)}"

        frappe.log_error(frappe.get_traceback(), mensaje)

        if debug_messages is not None:
            debug_messages.append("❌ " + mensaje)

        # Reenviar el error a la API
        raise


def get_stock_qty(item_code, warehouse, batch_no=None):
    try:
        if batch_no:
            query = """
                Select 
                    sum(T1.qty) qty
                from `tabSerial and Batch Bundle` T0
                JOIN `tabSerial and Batch Entry` T1 on T1.parent = T0.name
                where T0.item_code = %s
                and T0.warehouse = %s
                and T1.batch_no = %s
                and T0.docstatus = 1
                group by 
                T0.item_code,
                T0.warehouse,
                T1.batch_no;
            """
            params = (item_code, warehouse, batch_no)
        else:
            query = """
                SELECT SUM(T1.qty) AS qty
                FROM `tabSerial and Batch Bundle` T0
                JOIN `tabSerial and Batch Entry` T1 ON T1.parent = T0.name
                WHERE T0.item_code = %s
                  AND T0.warehouse = %s
                  AND T0.docstatus = 1
                GROUP BY T0.item_code, T0.warehouse
            """
            params = (item_code, warehouse)

        result = frappe.db.sql(query, params, as_dict=True)
        if result and result[0].qty is not None:
            return flt(result[0].qty)
        else:
            return 0.0

    except Exception as e:
        frappe.log_error(f"Error obteniendo qty de stock desde Serial and Batch: {e}", "Stock Sync")
        return 0.0
