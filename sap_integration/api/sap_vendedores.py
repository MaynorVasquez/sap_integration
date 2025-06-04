import frappe
from frappe import _
import requests
import json
import traceback  # Importación añadida
from .mapeos import get_mapeo_vendedores
from .sap_auth import login_sap 
from .logs import log_sincronizacion

@frappe.whitelist()
def sincronizar_lista_vendedores(docname=None):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []

    try:
        # 1. Autenticación
        debug_messages.append("Iniciando autenticación con SAP...")
        session = login_sap()

        if not session or not isinstance(session, requests.Session):
            raise Exception("La sesión SAP no se creó correctamente")
        debug_messages.append("✔ Autenticación exitosa")

        # 2. Obtener vendedores
        mapeo_lista = get_mapeo_vendedores()
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos")
        debug_messages.append("✔ Mapeo de lista vendedores obtenido")

        # 3. Configuración
        base_url = "https://apisap.yaesta.com.gt/b1s/v1/SalesPersons"
        select_fields = ",".join(mapeo_lista["sap_fields"].values())

                # 4. Paginación
        page, skip = 1, 0
        while True:
            current_url = f"{base_url}?$select={select_fields}&$top=20&$skip={skip}"
            debug_messages.append(f"\nPágina {page} - URL: {current_url}")

            response = session.get(current_url, timeout=30)
            response.raise_for_status()
            data = response.json()

            lista_vendedores = data.get('value', [])

            if not lista_vendedores:
                debug_messages.append("✓ Fin de paginación alcanzado")
                break

            for lista_vendedor in lista_vendedores:
                #result = procesar_lista_vendedor(lista_vendedor, mapeo_lista)
                result, datos_mapeados = procesar_lista_vendedor(lista_vendedor, mapeo_lista)
                if result:
                    total_procesados += 1
                    debug_messages.append(f"✓ Lista de vendedores {result} procesado")
                    detalles.append(datos_mapeados)
                    print("🔍 JSON detalles que se enviará al log:")
                    print(json.dumps(detalles, indent=2, ensure_ascii=False))                  

            frappe.db.commit()
            skip += 20
            page += 1

    except Exception as e:
        error_msg = f"Error durante sincronización: {str(e)}\n{traceback.format_exc()}"
        debug_messages.append(f"✗ {error_msg}")
        frappe.log_error(title="Error sincronizando vendedores desde SAP", message=error_msg)

        if docname:
            log_sincronizacion(
                doctype="Sincronizacion person sales SAP",
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
                doctype="Sincronizacion person sales SAP",
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
def procesar_lista_vendedor(lista_vendedor, mapeo_lista):
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
        vendedor_existente = frappe.get_all("Sales Person", filters={erp_key_field: sap_id}, limit=1)

        # Mapear datos SAP -> ERP
        datos_lista_vendedor = {}
        for erp_field, sap_field in mapeo_lista["sap_fields"].items():
            valor = lista_vendedor.get(sap_field)

            if erp_field == "Enabled":
                valor = 1 if valor == "tYES" else 0

            datos_lista_vendedor[erp_field] = valor
        
        # Asegurar que el campo clave esté presente
        datos_lista_vendedor[erp_key_field] = sap_id
        print("procesando vendedor ",sap_id)

        if vendedor_existente:
            # Actualizar lista de precios existente
            lista_vendedor_doc = frappe.get_doc("Sales Person", vendedor_existente[0].name)
            for campo, valor in datos_lista_vendedor.items():
                setattr(lista_vendedor_doc, campo, valor)
            
            try:
                lista_vendedor_doc.save()
            except frappe.exceptions.DocumentHasBeenModifiedError:
                frappe.db.rollback()
            return f"{sap_id} (actualizado)", datos_lista_vendedor
        else:
            # Crea Vendedor Nuevo
            lista_vendedor_doc = frappe.new_doc("Sales Person")
            for campo, valor in datos_lista_vendedor.items():
                setattr(lista_vendedor_doc, campo, valor)
            lista_vendedor_doc.insert()
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
    