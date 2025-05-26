import frappe
from frappe import _
import requests
import json
import traceback  # Importación añadida
import urllib.parse
from frappe.model.document import Document
from .sap_auth import login_sap  # El punto indica mismo directorio
from .mapeos import get_mapeo_cliente, get_mapeo_cliente_direcciones
from .logs import log_sincronizacion, filter_sap_response_items

@frappe.whitelist()
def sincronizar_clientes_desde_sap(docname=None):
    """Sincroniza clientes desde SAP a ERPNext"""
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

        # 2. Obtener mapeo
        mapeo_cliente = get_mapeo_cliente()
        if not mapeo_cliente or "sap_fields" not in mapeo_cliente:
            raise Exception("No se pudo obtener el mapeo de campos")
        debug_messages.append("✔ Mapeo de cliente obtenido")

        # 3. Configuración
        base_url = "https://apisap.yaesta.com.gt/b1s/v1/BusinessPartners"
        select_fields = ",".join(mapeo_cliente["sap_fields"].values())
        filter_condition = "U_smart_cli eq '1'"

        # 4. Paginación
        page, skip = 1, 0
        while True:
            current_url = f"{base_url}?$select={select_fields},BPAddresses&$filter={filter_condition}&$top=20&$skip={skip}"
            debug_messages.append(f"\nPágina {page} - URL: {current_url}")

            response = session.get(current_url, timeout=30)
            response.raise_for_status()
            data = response.json()

            debug_messages.append(f"Respuesta SAP (status {response.status_code}):")
            debug_messages.append(json.dumps(data, indent=2)[:500] + "...")

            clientes = data.get('value', [])

            clientes_sin_direcciones = filter_sap_response_items(clientes, exclude_keys=["BPAddresses"])
            detalles.extend(clientes_sin_direcciones)

            if not clientes:
                debug_messages.append("✓ Fin de paginación alcanzado")
                break

            for cliente in clientes:
                result = procesar_cliente(cliente, mapeo_cliente)
                if result:
                    total_procesados += 1
                    debug_messages.append(f"✓ Cliente {result} procesado")

            frappe.db.commit()
            skip += 20
            page += 1

    except Exception as e:
        error_msg = f"Error durante sincronización: {str(e)}\n{traceback.format_exc()}"
        debug_messages.append(f"✗ {error_msg}")
        frappe.log_error(title="Error sincronizando clientes desde SAP", message=error_msg)

        if docname:
            log_sincronizacion(
                doctype="Sincronizacion clientes SAP",
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
                doctype="Sincronizacion clientes SAP",
                docname=docname,
                status="Exitoso" if total_procesados > 0 else "Sin cambios",
                total=total_procesados,
                detalles=detalles,  # o clientes si quieres guardar solo eso
                errores=""
            )


    return {
        "status": "success" if total_procesados > 0 else "warning",
        "total": total_procesados,
        "debug": debug_messages
    }


def procesar_cliente(cliente_sap, mapeo_cliente):
    """Crea o actualiza un cliente en ERPNext a partir de los datos de SAP"""
    try:
        # Obtener campos clave
        sap_key_field = mapeo_cliente["key_field"]          # Ej: "CardCode"
        erp_key_field = mapeo_cliente["erp_key_field"]      # Ej: "code_sap"
        sap_id = cliente_sap.get(sap_key_field)

        if not sap_id:
            frappe.log_error("Cliente SAP sin CardCode", json.dumps(cliente_sap, indent=2))
            return None  # No se puede continuar sin ID

        # Buscar cliente en ERPNext por el campo clave
        cliente_existente = frappe.get_all("Customer", filters={erp_key_field: sap_id}, limit=1)

        # Mapear datos SAP -> ERP
        datos_cliente = {}
        for erp_field, sap_field in mapeo_cliente["sap_fields"].items():
            valor = cliente_sap.get(sap_field)

            if erp_field == "disabled":
                valor = 0 if valor == "tYES" else 1

            datos_cliente[erp_field] = valor

        # Asegurar que el campo clave esté presente
        datos_cliente[erp_key_field] = sap_id
        print("procesando código de cliente: ",sap_id)
        if cliente_existente:
            # Actualizar cliente existente
            cliente_doc = frappe.get_doc("Customer", cliente_existente[0].name)
            for campo, valor in datos_cliente.items():
                setattr(cliente_doc, campo, valor)
            cliente_doc.save()
            #print(f"[{sap_id}] Direcciones SAP encontradas:")
            #print(json.dumps(cliente_sap.get("BPAddresses", []), indent=2))
            procesar_direcciones(cliente_doc, cliente_sap.get("BPAddresses", []), sap_id)
            return f"{sap_id} (actualizado)"
        else:
            # Crear cliente nuevo
            cliente_doc = frappe.new_doc("Customer")
            for campo, valor in datos_cliente.items():
                setattr(cliente_doc, campo, valor)
            cliente_doc.insert()
            procesar_direcciones(cliente_doc, cliente_sap.get("BPAddresses", []), sap_id)
            return f"{sap_id} (creado)"

    except Exception as e:
        frappe.log_error(f"Error al procesar cliente {sap_id}: {str(e)}\n{traceback.format_exc()}")
        return None

def procesar_direcciones(cliente_doc, bp_addresses, card_code):
    """
    Procesa las direcciones del cliente desde SAP y las sincroniza con ERPNext.
    Maneja la creación y actualización de registros tipo Address, incluyendo links como child table.
    """
    if not bp_addresses:
        frappe.logger().info(f"[{card_code}] Cliente sin direcciones en SAP.")
        return

    try:
        mapeo_direcciones = get_mapeo_cliente_direcciones()
        if not mapeo_direcciones or not mapeo_direcciones.get("sap_fields"):
            frappe.throw("No se pudo obtener el mapeo de direcciones o es inválido.")
    except Exception as e:
        frappe.log_error(f"Error obteniendo mapeo de direcciones: {str(e)}")
        return

    cliente_erp = frappe.get_value("Customer", {"code_sap": card_code}, "name")
    if not cliente_erp:
        frappe.log_error(f"No se encontró cliente en ERPNext para SAP ID {card_code}")
        return

    country_map = {
        "NI": "Nicaragua",
        "GT": "Guatemala"
    }

    for direccion in bp_addresses:
        try:
            address_title_field = mapeo_direcciones["sap_fields"].get("address_title")
            address_title = direccion.get(address_title_field)

            if not address_title:
                frappe.logger().info(f"[{card_code}] Dirección sin título, omitida.")
                continue

            frappe.logger().info(f"Procesando dirección: {address_title}")

            direcciones_existentes = frappe.get_all(
                "Address",
                filters={
                    "address_title": address_title,
                    mapeo_direcciones["erp_key_field"]: card_code
                },
                fields=["name"]
            )

            direccion_data = {
                "doctype": "Address",
                "address_title": address_title,
                mapeo_direcciones["erp_key_field"]: card_code,
                "links": [{
                    "link_doctype": "Customer",
                    "link_name": cliente_erp
                }]
            }

            for campo_erp, campo_sap in mapeo_direcciones["sap_fields"].items():
                if campo_erp in ["CardCode", "address_title"]:
                    continue

                valor = direccion.get(campo_sap)
                if not valor:
                    # Si el campo es address_line1 o city, poner por defecto "Ciudad"
                    if campo_erp in ["address_line1", "city"]:
                        valor = "Ciudad"
                        frappe.logger().warning(f"⚠️ {campo_erp} estaba vacío para '{address_title}', se asignó valor por defecto: Ciudad")

                if campo_erp == "country":
                    valor = country_map.get(valor, valor or "Desconocido")

                direccion_data[campo_erp] = valor

            # Normalizar tipo de dirección
            tipo = direccion_data.get("address_type")
            if tipo == "bo_BillTo":
                direccion_data["address_type"] = "Billing"
            elif tipo == "bo_ShipTo":
                direccion_data["address_type"] = "Shipping"

            if direcciones_existentes:
                direccion_name = direcciones_existentes[0]["name"]
                direccion_doc = frappe.get_doc("Address", direccion_name)

                # Actualiza los campos (excepto links)
                direccion_doc.update({
                    k: v for k, v in direccion_data.items() if k != "links"
                })

                # Limpia y reasigna los links correctamente
                direccion_doc.set("links", [])
                for link in direccion_data["links"]:
                    direccion_doc.append("links", link)

                direccion_doc.save()
                #frappe.db.commit()
                frappe.logger().info(f"✓ Dirección actualizada: {direccion_doc.name}")
                print(f"Dirección actualizada con título: {address_title}")

            else:
                print(f"Insertando nueva dirección con título: {address_title}")
                # Truncar address_line1 si es necesario
                if len(direccion_data["address_line1"]) > 140:
                    direccion_data["address_line1"] = direccion_data["address_line1"][:139]
                    frappe.logger().warning(f"⚠️ address_line1 truncado a 139 caracteres para '{address_title}'")

                direccion_doc = frappe.get_doc(direccion_data)
                #print(direccion_doc.as_dict())
                direccion_doc.insert()
                frappe.logger().info(f"✓ Dirección creada: {direccion_doc.name}")

        except Exception as e:
            frappe.log_error(f"Error procesando dirección '{direccion.get(address_title_field)}' de {card_code}: {str(e)}")
            print(f"Error en dirección: {e}")
            print(direccion_doc.as_dict())