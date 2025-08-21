import frappe
from frappe import _
import requests
import json
import traceback  # Importación añadida
from .blueprint import mapping_blueprint, construir_url_sap
from .sap_auth import login_sap 
from .logs import log_sincronizacion

@frappe.whitelist()
def sincronizar_lista_vendedores(docname=None):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    doctype_logs = "Sincronizacion person sales SAP"
    doctype_target = "Sales Person"

    try:
        # 1. Autenticación
        debug_messages.append("Iniciando autenticación con SAP...")
        session = login_sap()

        if not session or not isinstance(session, requests.Session):
            raise Exception("La sesión SAP no se creó correctamente")
        debug_messages.append("✔ Autenticación exitosa")

        # 2. Obtener vendedores
        mapeo_lista = mapping_blueprint("Mapeo Vendedores SAP", "SalesEmployeeCode", "custom_salesemployeecode")
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos desde el blueprint")
        debug_messages.append("✔ Mapeo de campos exitoso")
        print("✔ Mapeo de campos exitoso")

        top = 20
        skip = 0
        page = 0
        print("Inicio de paginación URL: ", mapeo_lista["url"])

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
        frappe.log_error(title="Error sincronizando vendedores desde SAP", message=error_msg)

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

@frappe.whitelist()
def procesar_datos(lista_vendedor, mapeo_lista, doctype):
    """"Crea o actualiza lista de precios en ERPNEXT"""
    try:
        # Obtener campos clave
        sap_key_field = mapeo_lista["key_field"]          # Ej: "SalesEmployeeCode"
        erp_key_field = mapeo_lista["erp_key_field"]      # Ej: "custom_salesemployeecode"
        sap_id = lista_vendedor.get(sap_key_field)

        if not sap_id:
            frappe.log_error("Vendedor sin código", json.dumps(lista_vendedor, indent=2))
            return None, None  # No se puede continuar sin ID

        # Buscar vendedor ERPNEXT
        #vendedor_existente = frappe.get_all(doctype, filters={erp_key_field: sap_id}, limit=1)
        vendedor_existente = frappe.get_all(doctype, filters={erp_key_field: sap_id}, limit=1)

        # Mapear datos SAP -> ERP
        datos_lista_vendedor = {}
        for erp_field, sap_field in mapeo_lista["sap_fields"].items():
            valor = lista_vendedor.get(sap_field)
            if erp_field == "enabled":
                valor = 1 if valor == "tYES" else 0
            datos_lista_vendedor[erp_field] = valor
        
        # Asegurar que el campo clave esté presente
        datos_lista_vendedor[erp_key_field] = sap_id
        # 🔹 Imprimir JSON completo a enviar
        print("📤 Enviando a ERPNext:\n", json.dumps(datos_lista_vendedor, indent=2, ensure_ascii=False))

        if vendedor_existente:
            lista_vendedor_doc = frappe.get_doc(doctype, vendedor_existente)
            print(f"lista vendedor doc: {lista_vendedor_doc}")
            for campo, valor in datos_lista_vendedor.items():
                #lista_vendedor_doc.set(campo, valor)
                setattr(lista_vendedor_doc, campo, valor)         
            try:
                # 👇 Esto ignora los permisos del usuario actual
                lista_vendedor_doc.flags.ignore_permissions = True 
                lista_vendedor_doc.save()
                frappe.db.commit()  # ✅ commit después de guardar
            except frappe.exceptions.DocumentHasBeenModifiedError:
                frappe.db.rollback()
            return f"{sap_id} (actualizado)", datos_lista_vendedor
        else:
            # Crea Vendedor Nuevo
            lista_vendedor_doc = frappe.new_doc(doctype)
            for campo, valor in datos_lista_vendedor.items():
                setattr(lista_vendedor_doc, campo, valor)
            # 👇 Esto ignora los permisos del usuario actual
            lista_vendedor_doc.flags.ignore_permissions = True 
            lista_vendedor_doc.insert()
            frappe.db.commit()  # ✅ commit después de insertar
            return f"{sap_id} (creado)", datos_lista_vendedor

    except Exception as e:
        frappe.log_error(f"Error al procesar lista vendedor {sap_id}: {str(e)}\n{traceback.format_exc()}")
        return None, None

@frappe.whitelist()
def asignar_vendedor_por_codigo_sap(datos_doc, sales_employee_code, campo_destino="sales_person", reintento=True):
    """
    Asigna el 'name' del Sales Person (buscado por custom_salesemployeecode=sales_employee_code)
    al campo especificado en datos_doc (por defecto 'sales_person').

    Si el vendedor no existe y reintento=True, intenta sincronizar desde SAP y reintenta la asignación.
    """
    if not sales_employee_code or str(sales_employee_code) == "-1":
        return False  # Nada que asignar

    vendedor_name = frappe.db.get_value("Sales Person", {"custom_salesemployeecode": sales_employee_code}, "name")

    if vendedor_name:
        datos_doc[campo_destino] = vendedor_name
        return True
    elif reintento:
        sincronizar_lista_vendedores()  # Asegúrate de que esta función está disponible
        return asignar_vendedor_por_codigo_sap(datos_doc, sales_employee_code, campo_destino, reintento=False)
    else:
        frappe.logger().info(f"No se encontró Sales Person con custom_salesemployeecode = {sales_employee_code} tras reintento")
        return False
    