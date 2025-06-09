import frappe
from frappe import _
import requests
import json
import traceback
from .testing import mapping_blueprint, construir_filtro
from .sap_auth import login_sap
from .logs import log_sincronizacion
from frappe.utils import nowdate, nowtime
from erpnext.stock.utils import get_bin  # ✅ Si vas a validar stock luego

def sincronizar_lista_stock(docname=None):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []

    try:
        # 1. Autenticación con SAP
        session = login_sap()
        if not session or not isinstance(session, requests.Session):
            raise Exception("No se pudo establecer la sesión con SAP.")

        # 2. Obtener la estructura del mapeo de campos
        mapeo_lista = mapping_blueprint("Mapeo Inventario SAP", "ItemCode", "itemcode")
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos desde el blueprint")
        debug_messages.append("✔ Mapeo de campos exitoso")

        try:
            base_url = mapeo_lista["url"]
            campos = mapeo_lista["sap_fields"]
            select_fields = ",".join(campos.values())
        except Exception as e:
            error_msg = f"✗ Error: {str(e)}\n{traceback.format_exc()}"
            frappe.log_error("Error en sincronización de stock SAP", error_msg)
            return {
                "status": "error",
                "message": "fallo en la construccion URL",
                "debug": debug_messages
            }

        # Construcción de filtros avanzados
        try:            
            filtros = mapeo_lista.get("filters", [])
            if filtros:
                filtro_sap = construir_filtro(filtros)
            else:
                filtro_sap = ""
        except Exception as e:
            error_msg = f"✗ Error: {str(e)}\n{traceback.format_exc()}"
            return {
                "status": "error",
                "message": "fallo en la construcción del filtro",
                "debug": debug_messages
            }

        page, skip = 0, 0
        top = 50

        while True:
            url_final = f"{base_url}?"
            params = []

            if filtro_sap:
                params.append(f"$filter={filtro_sap}")
            if select_fields:
                params.append(f"$select={select_fields}")
            params.append(f"$top={top}")
            params.append(f"$skip={skip}")
            url_final += "&".join(params)
            debug_messages.append(url_final)

            response = session.get(url_final, timeout=30)
            response.raise_for_status()
            data = response.json()
            lista_datos = data.get("value", [])
            detalles.extend(lista_datos)
            debug_messages.append(detalles)

            if not lista_datos:
                break

            for registro_sap in lista_datos:
                try:
                    
                    procesado = procesar_registro_con_lote(registro_sap, campos, detalles, debug_messages)
                    if procesado:
                        total_procesados += 1
                except Exception as single_error:
                    debug_messages.append(f"✗ Error procesando registro: {single_error}")

            #frappe.db.commit()
            skip += top
            page += 1

    except Exception as e:
        error_msg = f"✗ Error: {str(e)}\n{traceback.format_exc()}"
        #frappe.log_error("Error en sincronización de stock SAP", error_msg)
        return {
            "status": "error",
            "message": "Fallo en la sincronización",
            "debug": debug_messages
        }

    finally:
        if session:
            session.close()

    return {
        "status": "success",
        "total": total_procesados,
        "debug": debug_messages,
        "detalles": detalles
    }


def procesar_registro_con_lote(registro_sap, campos, detalles, debug_messages):
    try:
        valores_sap = {
            erp_field: registro_sap.get(sap_field)
            for erp_field, sap_field in campos.items()
        }

        item_code = valores_sap.get("itemcode")
        whscode = valores_sap.get("whscode")
        quantity = float(valores_sap.get("quantity") or 0)
        batchnum = valores_sap.get("batchnum")
        expdate = valores_sap.get("expdate")

        if not item_code or not whscode or quantity <= 0:
            debug_messages.append(f"✗ Registro inválido: {registro_sap}")
            return False

        batch_no = None
        if batchnum:
            batch = frappe.get_all("Batch", filters={"batch_id": batchnum, "item": item_code})
            if not batch:
                batch_no = crear_batch_si_no_existe(item_code, batchnum, expdate)
                debug_messages.append(f"✔ Lote creado: {batch_no}")
            else:
                batch_no = batch[0].name

        qty_actual = get_stock_qty(item_code, whscode, batch_no)
        if qty_actual == quantity:
            debug_messages.append(f"✓ Stock igual para {item_code} en almacén {whscode} lote {batch_no}, no se hace ajuste.")
            return False

        crear_stock_entry(item_code, whscode, quantity, batch_no, detalles)
        debug_messages.append(f"✔ Stock Entry creado para {item_code} en almacén {whscode}, lote {batch_no}")
        return True

    except Exception as e:
        debug_messages.append(f"✗ Error procesando registro SAP: {e}")
        return False

def crear_stock_entry(item_code, whscode, quantity, batch_no, detalles):
    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.stock_entry_type = "Material Receipt"
    stock_entry.purpose = "Material Receipt"
    stock_entry.company = frappe.defaults.get_user_default("Company")
    stock_entry.posting_date = nowdate()
    stock_entry.posting_time = nowtime()

    stock_entry.append("items", {
        "item_code": item_code,
        "qty": quantity,
        "s_warehouse": None,
        "t_warehouse": whscode,
        "batch_no": batch_no,
    })

    stock_entry.insert(ignore_permissions=True)
    stock_entry.submit()

    detalles.append({
        "item_code": item_code,
        "warehouse": whscode,
        "qty": quantity,
        "batch": batch_no,
    })

def crear_batch_si_no_existe(item_code, batch_id, expdate=None):
    nuevo_batch = frappe.new_doc("Batch")
    nuevo_batch.batch_id = batch_id
    nuevo_batch.item = item_code
    if expdate:
        # Asegúrate que expdate esté en formato YYYY-MM-DD
        if isinstance(expdate, str):
            try:
                expdate = expdate.split("T")[0]  # por si viene con timestamp tipo ISO
            except:
                pass
        nuevo_batch.expiry_date = expdate
    nuevo_batch.insert(ignore_permissions=True)
    return nuevo_batch.name

def get_stock_qty(item_code, warehouse, batch_no=None):
    filters = {
        "item_code": item_code,
        "warehouse": warehouse,
    }
    if batch_no:
        filters["batch_no"] = batch_no

    bin_data = frappe.get_all("Bin", filters=filters, fields=["actual_qty"])
    return bin_data[0].actual_qty if bin_data else 0.0
