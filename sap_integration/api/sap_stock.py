import frappe
from frappe import _
import requests
import json
import traceback
from .blueprint import mapping_blueprint, construir_url_sap
from .sap_auth import login_sap
from .logs import log_sincronizacion
from frappe.utils import nowdate, nowtime, getdate, today
from erpnext.stock.utils import get_bin  # ✅ Si vas a validar stock luego
from datetime import datetime
from frappe.utils import flt
import time

@frappe.whitelist()
def sincronizar_lista_stock(docname=None, doctype_logs = None, almacen = None):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []

    try:
        debug_messages.append("Iniciando autenticación con SAP...")
        session = login_sap()
        if not session or not isinstance(session, requests.Session):
            raise Exception("No se pudo establecer la sesión con SAP.")
        print("Conexión exitosa...")

        mapeo_lista = mapping_blueprint("Mapeo Inventario SAP", "ItemCode", "itemcode")
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos desde el blueprint")
        debug_messages.append("✔ Mapeo de campos exitoso")
        print("✔ Mapeo de campos exitoso")

        top = 20
        skip = 0
        page = 0
        max_reintentos = 5
        wait_times = [1, 3, 5, 8, 13]

        print("Inicio de paginación URL: ", mapeo_lista["url"])

        while True:
            # 🚩 si hay almacén → ignorar filtros del mapeo
            if almacen:
                sap_whscode = frappe.db.get_value("Warehouse", almacen, "custom_whscode")
                url_final = f"{mapeo_lista['base_url']}?$filter=WhsCode eq '{sap_whscode}'"
            else:
                url_final = construir_url_sap(mapeo_lista, top=top, skip=skip)

            debug_messages.append(f"🌐 URL: {url_final}")

            intentos = 0
            lista_datos = []

            while intentos < max_reintentos:
                try:
                    response = session.get(url_final, timeout=30)

                    if response.status_code == 401:
                        debug_messages.append("🔐 Sesión expirada, reautenticando con SAP")
                        session = login_sap()
                        intentos += 1
                        continue

                    response.raise_for_status()
                    data = response.json()
                    lista_datos = data.get("value", [])
                    debug_messages.append(f"📄 Página {page} → Registros recibidos: {len(lista_datos)}")
                    detalles.extend(lista_datos)
                    break

                except Exception as e:
                    debug_messages.append(f"⚠ Intento #{intentos + 1} fallido en página {page}: {e}")
                    print(f"⚠ Intento #{intentos + 1} fallido en página {page}: {e}")

                    if intentos == 2:
                        debug_messages.append("🔁 Reemplazando sesión SAP tras varios fallos consecutivos...")
                        session = login_sap()

                    if intentos < len(wait_times):
                        time.sleep(wait_times[intentos])

                    intentos += 1

            else:
                debug_messages.append(f"❌ Error persistente después de {max_reintentos} intentos. Página {page}. Abortando.")
                return {
                    "status": "error",
                    "message": f"Error persistente al obtener datos de SAP en página {page}",
                    "debug": debug_messages,
                }

            if not lista_datos:
                print("✅ Fin de la paginación...")
                break

            skip += top
            page += 1
            print(f"✅ Página {page} procesada correctamente")

        debug_messages.append(f"✅ Total registros acumulados: {len(detalles)}")

        if detalles:
            procesar_registros_lotes_multiple(detalles, debug_messages)
            total_procesados = len(detalles)
        else:
            debug_messages.append("⚠ No se encontraron registros para procesar.")

    except Exception as e:
        error_msg = f"✗ Error general: {str(e)}\n{traceback.format_exc()}"
        debug_messages.append(error_msg)
        return {
            "status": "error",
            "message": "Fallo en la sincronización",
            "debug": debug_messages,
        }

    finally:
        if session:
            print("Cerrando Sesión")
            session.close()

        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Exitoso" if total_procesados > 0 else "Sin cambios",
                total=total_procesados,
                detalles=detalles,
                errores=""
            )

    return {
        "status": "success",
        "total": total_procesados,
        "debug": debug_messages
    }




def procesar_registros_lotes_multiple(registros_sap, debug_messages, warehouse_default=None):
    """
    Procesa múltiples registros SAP, calcula diferencias reales con ERP
    y acumula movimientos para un único Stock Entry por tipo ("In" o "Out").
    """
    items_in = []
    items_out = []

    registros_unicos = set()

    for registro_sap in registros_sap:
        try:
            item_code = registro_sap.get("ItemCode")
            whs_code = registro_sap.get("WhsCode") or warehouse_default
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
                #debug_messages.append(f"✔ Sin cambios: {item_code}, lote {batch}, almacén {whs_code}")
                continue


            clave_unica = f"{item_code}|{batch}|{warehouse}|{diferencia}"

            if clave_unica in registros_unicos:
                debug_messages.append(f"🔁 Registro duplicado ignorado: {clave_unica}")
                continue

            registros_unicos.add(clave_unica)

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

                # Verificar si el ítem usa lotes
                usa_lotes = frappe.get_value("Item", item_code, "has_batch_no")

                item_data = {
                    "item_code": item_code,
                    "qty": item["qty"],
                    "allow_zero_valuation_rate": 1,
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


def crear_batch_si_no_existe(registro):
    item_code = registro.get("ItemCode")
    batch_id = registro.get("BatchNum", "").strip()
    fecha_exp = registro.get("ExpDate")

    if not item_code or not batch_id:
        return
        
    # Buscar si ya existe el lote con ese batch_id e ítem
    lote = frappe.get_value("Batch", {"batch_id": batch_id, "item": item_code}, "name")

    if not lote:
        try:
            lote_doc = frappe.new_doc("Batch")
            lote_doc.batch_id = batch_id
            lote_doc.item = item_code
            lote_doc.expiry_date = fecha_exp
            #lote_doc.flags.ignore_validate = True
            lote_doc.flags.ignore_mandatory = True
            lote_doc.insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), f"✗ Error al crear lote {batch_id}")
    else:
        try:
            frappe.db.set_value("Batch", lote, "expiry_date", fecha_exp)
            print(f"🛠 Lote existente actualizado: {batch_id}")
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), f"✗ Error al actualizar lote {batch_id}")


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

