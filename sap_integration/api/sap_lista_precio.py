import frappe
from frappe import _
import requests
import json
import traceback  # Importación añadida
from .blueprint import mapping_blueprint, construir_url_sap
from .sap_auth import login_sap 
from .logs import log_sincronizacion

@frappe.whitelist()
def sincronizar_lista_precio(docname=None):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    doctype_logs = "Sincronizacion Lista Precios SAP"
    doctype_target = "Price List"


    try:
        # 1. Autenticación
        debug_messages.append("Iniciando autenticación con SAP...")
        session = login_sap()

        if not session or not isinstance(session, requests.Session):
            raise Exception("La sesión SAP no se creó correctamente")
        debug_messages.append("✔ Autenticación exitosa")

        # 2. Obtener Lista de precios
        mapeo_lista = mapping_blueprint("Mapeo Lista De Precios SAP", "PriceListNo", "custom_pricelistno")
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos desde el blueprint")
        debug_messages.append("✔ Mapeo de campos exitoso")
        print("✔ Mapeo de campos exitoso")


        top = 20
        skip = 0
        page = 0
        print("Inicio de paginación URL: ", mapeo_lista["url"])

        # 4. Paginación

        while True:
            url_final = construir_url_sap(mapeo_lista, top=top, skip=skip)
            debug_messages.append(f"URL: {url_final}")

            intentos = 0
            max_reintentos = 3
            while intentos <= max_reintentos:
                try:
                    response = session.get(url_final, timeout=30)
                    if response.status_code == 401:
                        debug_messages.append("⚠ Sesión expirada, intentando nueva sesión")
                        session = login_sap()
                        intentos += 1
                        continue
                    response.raise_for_status()
                    data = response.json()
                    lista_datos = data.get("value", [])
                    detalles.extend(lista_datos)
                    break
                except Exception as e:
                    debug_messages.append(f"✗ Error al obtener datos desde SAP: {e}")
                    if intentos >= max_reintentos:
                        return {"status": "error", "message": "Error al obtener datos de SAP", "debug": debug_messages}
                    intentos += 1

            debug_messages.append(f"📄 Página {page} → Registros recibidos: {len(lista_datos)}")

            if not lista_datos:
                print("Fin de la paginación...")
                break

            skip += top
            page += 1

        debug_messages.append(f"✅ Total registros acumulados: {len(detalles)}")

        # Procesar todos los registros individualmente
        if detalles:
            for detalle in detalles:
                procesado, resultado = procesar_datos(detalle, mapeo_lista, doctype_target)
                if procesado:
                    total_procesados += 1
                    debug_messages.append(f"✔ Procesado: {procesado}")
                    # log_sincronizacion(doctype_logs, procesado, resultado)  # ← Descomenta si deseas guardar log por registro
                else:
                    debug_messages.append(f"✗ Falló procesar: {detalle}")

        
    except Exception as e:
        error_msg = f"Error durante sincronización: {str(e)}\n{traceback.format_exc()}"
        debug_messages.append(f"✗ {error_msg}")
        frappe.log_error(title="Error sincronizando listas de precios desde SAP", message=error_msg)

        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Error",
                total=total_procesados,
                detalles={},
                errores=error_msg
            )

        return {
            "status": "error",
            "message": "Ocurrió un error durante la sincronización",
            "debug": debug_messages,
            "total": total_procesados
        }
    
    finally:        
        if session and isinstance(session, requests.Session):
            session.close()
            debug_messages.append("✓ Sesión SAP cerrada correctamente")

        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Exitoso" if total_procesados > 0 else "Sin cambios",
                total=total_procesados,
                detalles=detalles, #Json devuelto
                errores=""
            )
    return {
        "status": "success" if total_procesados > 0 else "warning",
        "total": total_procesados,
        "debug": debug_messages
    }


def procesar_datos(lista_precio, mapeo_lista, doctype):
    """"Crea o actualiza lista de precios en ERPNEXT"""
    try:
        # Obtener campos clave
        sap_key_field = mapeo_lista["key_field"]          # Ej: "PriceListNo"
        erp_key_field = mapeo_lista["erp_key_field"]      # Ej: "custom_pricelistno"
        sap_id = lista_precio.get(sap_key_field)

        if not sap_id:
            frappe.log_error("Lista de precios sin código", json.dumps(lista_precio, indent=2))
            return None, None  # No se puede continuar sin ID

        # Buscar lista de precios ERPNEXT
        lista_existente = frappe.get_all(doctype, filters={erp_key_field: sap_id}, limit=1)

        # Mapear datos SAP -> ERP
        datos_lista_precio = {}
        for erp_field, sap_field in mapeo_lista["sap_fields"].items():
            valor = lista_precio.get(sap_field)

            # Corrección de moneda
            if erp_field == "currency" and valor == "QTZ":
                valor = "GTQ"

            if erp_field == "enabled":
                valor = 1 if valor == "tYES" else 0

            datos_lista_precio[erp_field] = valor
        
        print(datos_lista_precio)
        
        # Asegurar que el campo clave esté presente
        datos_lista_precio[erp_key_field] = sap_id
        # Asegurar campos obligatorios en ERPNext
        datos_lista_precio.setdefault("selling", 1)
        datos_lista_precio.setdefault("buying", 1)
        print("procesando lista de precio: ",sap_id)

        if lista_existente:
            # Actualizar lista de precios existente
            lista_precio_doc = frappe.get_doc(doctype, lista_existente[0].name)
            for campo, valor in datos_lista_precio.items():
                setattr(lista_precio_doc, campo, valor)
            
            try:
                lista_precio_doc.save()
            except frappe.exceptions.DocumentHasBeenModifiedError:
                frappe.db.rollback()
            return f"{sap_id} (actualizado)", datos_lista_precio
        else:
            # Crea Lista de precios Nuevo
            lista_precio_doc = frappe.new_doc(doctype)
            for campo, valor in datos_lista_precio.items():
                setattr(lista_precio_doc, campo, valor)
            lista_precio_doc.insert()
            return f"{sap_id} (creado)", datos_lista_precio

    except Exception as e:
        frappe.log_error(f"Error al procesar lista de precios {sap_id}: {str(e)}\n{traceback.format_exc()}")
        return None, None
    

def asignar_lista_precios_por_codigo_sap(datos_doc, listnum_sap, campo_destino="default_price_list", reintento=True):
    """
    Asigna el 'name' del Price List (buscado por custom_pricelistno=listnum_sap)
    al campo especificado en datos_doc (por defecto 'default_price_list').

    Si la lista no existe y reintento=True, intenta sincronizar desde SAP y reintenta la asignación.
    """
    if not listnum_sap or str(listnum_sap) == "-1":
        # Nada que asignar, o explícitamente no tiene lista de precios en SAP
        return False

    price_list_name = frappe.db.get_value("Price List", {"custom_pricelistno": listnum_sap}, "name")

    if price_list_name:
        datos_doc[campo_destino] = price_list_name
        return True
    elif reintento:
        # Intentar sincronizar listas de precios
        sincronizar_lista_precio()

        # Reintentar una vez sin permitir recursión infinita
        return asignar_lista_precios_por_codigo_sap(datos_doc, listnum_sap, campo_destino, reintento=False)
    else:
        frappe.logger().info(f"No se encontró Price List con custom_pricelistno = {listnum_sap} tras reintento")
        return False


