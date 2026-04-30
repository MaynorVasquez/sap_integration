import frappe
from frappe import _
import json
import traceback  # Importación añadida
from datetime import datetime
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual
from frappe.utils import nowdate, nowtime, getdate, today
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
    """
    Procesa múltiples registros SAP, calcula diferencias reales con ERP
    y acumula movimientos para un único Stock Entry por tipo ("In" o "Out").
    También elimina lotes que ya no vienen de SAP.
    """
    items_in = []
    items_out = []

    registros_unicos = set()

    for registro_sap in registros_sap:
        print("entro den el for")
        try:
            print("entro en el try")
            codigo_sap = registro_sap.get("ItemCode")
            print(f"codigo sap: {codigo_sap}")

            codigo_erpnext = frappe.db.sql("""
                SELECT T0.name
                FROM `tabItem` T0
                INNER JOIN `tabItem Default` T1
                    ON T0.name = T1.parent
                WHERE T0.custom_itemcode = %s
                AND T1.company = %s
                LIMIT 1
            """, (codigo_sap, company), as_dict=True)
            item_code = codigo_erpnext[0]["name"] if codigo_erpnext else None

            print(f"codigo erpnext: {item_code}")

            whs_code = registro_sap.get("WhsCode")
            warehouse = obtener_nombre_almacen(whs_code)
            raw_batch = (registro_sap.get("BatchNum") or "").strip()
            custom_batchnum = (registro_sap.get("BatchNum") or "").strip()
            batch = f"{item_code}-{raw_batch}"
            cantidad_sap = flt(registro_sap.get("Quantity") or 0)
            fecha_exp = registro_sap.get("ExpDate")
            valuation_rate = flt(registro_sap.get("AvgPrice") or 0)

            # Verifica lote vencido y ajusta la fecha si es necesario
            if fecha_exp and getdate(fecha_exp) < getdate(today()):
                fecha_exp = today()

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

            # Si no hay diferencia, se omite
            if abs(diferencia) < 0.000001:
                continue

            clave_unica = f"{item_code}|{batch}|{warehouse}|{diferencia}"
            if clave_unica in registros_unicos:
                debug_messages.append(f"🔁 Registro duplicado ignorado: {clave_unica}")
                continue

            registros_unicos.add(clave_unica)

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

    # --- Detectar lotes en ERP que ya no vienen en SAP ---
    try:
        # set con los lotes que llegaron de SAP
        lotes_sap = {
            (registro.get("ItemCode"),
             f"{registro.get('ItemCode')}-{(registro.get('BatchNum') or '').strip()}",
             obtener_nombre_almacen(registro.get("WhsCode") ))
            for registro in registros_sap
            if registro.get("ItemCode")
        }

        # traer lotes con saldo > 0 en ERP para los almacenes involucrados
        warehouses_sap = {
            obtener_nombre_almacen(registro.get("WhsCode"))
            for registro in registros_sap
            if registro.get("ItemCode")
        }
        warehouses_sap = tuple(warehouses_sap) if warehouses_sap else ("",)

        lotes_erp = frappe.db.sql(f"""
            SELECT 
                T0.item_code,
                T1.batch_no,
                T3.batch_qty,
                T0.warehouse
            FROM `tabSerial and Batch Bundle` T0
            JOIN `tabSerial and Batch Entry` T1 ON T1.parent = T0.name
            JOIN `tabBatch` T3 ON T3.item = T0.item_code AND T3.batch_id = T1.batch_no
            WHERE T0.docstatus = 1
              AND T3.batch_qty > 0
              AND T0.warehouse IN {warehouses_sap if len(warehouses_sap) > 1 else f"('{warehouses_sap[0]}')"}
            GROUP BY T0.item_code, T0.warehouse, T1.batch_no
        """, as_dict=True)

        for row in lotes_erp:
            clave = (row.item_code, row.batch_no, row.warehouse)
            if clave not in lotes_sap:
                # Este lote no vino en SAP → salida completa
                movimiento = {
                    "item_code": row.item_code,
                    "qty": row.batch_qty,
                    "warehouse": row.warehouse,
                    "valuation_rate": 0,   # puedes ajustar si quieres cuadrar valor
                    "batch_no": row.batch_no
                }
                items_out.append(movimiento)
                debug_messages.append(
                    f"🗑 Lote {row.batch_no} del item {row.item_code} en {row.warehouse} "
                    f"no vino en SAP, salida total {row.batch_qty}"
                )
    except Exception as e:
        debug_messages.append(f"⚠ Error detectando lotes faltantes: {e}")

    # Crear los Stock Entry si hay datos
    if items_in:
        crear_stock_entry_multiple(items_in, tipo="In", debug_messages=debug_messages)
    if items_out:
        crear_stock_entry_multiple(items_out, tipo="Out", debug_messages=debug_messages)


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
                    debug_messages.append(f"✅ Ítem #{idx} agregado al Stock Entry")

            except Exception as item_error:
                mensaje_error = f"⚠ Error con ítem #{idx} (Item: {item.get('item_code')}, Lote: {item.get('batch_no')}): {item_error}"
                if debug_messages is not None:
                    debug_messages.append(mensaje_error)
                frappe.log_error(frappe.get_traceback(), mensaje_error)

        if not se.items:
            if debug_messages is not None:
                debug_messages.append("✗ No se agregó ningún ítem válido al Stock Entry.")
            return

        se.flags.ignore_mandatory = True
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
        frappe.log_error(frappe.get_traceback(), "Error en crear stock_entry multiple")
        if debug_messages is not None:
            debug_messages.append(f"✗ Error general creando Stock Entry ({tipo_entrada}): {e}")
        print(f"✗ Error creando Stock Entry: {e}")


def get_stock_qty(item_code, warehouse, batch_no=None):
    try:
        if batch_no:
            query = """
                SELECT T3.batch_qty AS qty
                FROM `tabSerial and Batch Bundle` T0
                JOIN `tabSerial and Batch Entry` T1 ON T1.parent = T0.name
                join `tabBatch` T3 on T3.item = T0.item_code and T3.batch_id = T1.batch_no
                WHERE T0.item_code = %s
                  AND T0.warehouse = %s
                  AND T1.batch_no = %s
                  AND T0.docstatus = 1
                GROUP BY T0.item_code, T0.warehouse, T1.batch_no
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


def obtener_nombre_almacen(codigo_sap):
    try:
        return frappe.db.get_value("Warehouse", {"custom_warehousecode": codigo_sap}, "name")
    except Exception as e:
        frappe.log_error(f"Error buscando almacén por código SAP {codigo_sap}: {e}", "Stock Sync")
        return None
