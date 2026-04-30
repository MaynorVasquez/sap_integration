import frappe
from frappe import _
import requests
import json
import traceback  # Importación añadida
from datetime import datetime
from frappe.model.document import Document
from .sap_auth import login_sap  # El punto indica mismo directorio
from .blueprint import mapping_blueprint, construir_url_sap
from .logs import log_sincronizacion, filter_sap_response_items
from .last_update import obtener_filtro_ultima_sync, actualizar_last_sync
from .sap_lista_precio import asignar_lista_precios_por_codigo_sap
from .sap_clientes_grupos import sincronizar_lista_clientes_grupos

@frappe.whitelist()
def sincronizar_clientes_desde_sap(docname=None):
    """Sincroniza clientes desde SAP a ERPNext"""
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    doctype_logs = "Sincronizacion clientes SAP"
    doctype_target = "Customer"

    try:
        # 1. Autenticación
        debug_messages.append("Iniciando autenticación con SAP...")
        session = login_sap()

        if not session or not isinstance(session, requests.Session):
            raise Exception("La sesión SAP no se creó correctamente")
        debug_messages.append("✔ Autenticación exitosa")

        # 2. Obtener la estructura del mapeo de campos
        mapeo_lista = mapping_blueprint("Mapeo Cliente", "CardCode", "custom_cardcode")
        if not mapeo_lista or "sap_fields" not in mapeo_lista:
            raise Exception("No se pudo obtener el mapeo de campos")
        debug_messages.append("✔ Mapeo de campos obtenido")


        syncs = obtener_filtro_ultima_sync("Sync Tracker", "Sync Record", "Clientes")
        sync_records = syncs["data"] if syncs["success"] else {}


        # 4. Paginación
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
                    print(f"respueta: {response}")
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
                procesado, resultado = procesar_dato(detalle, mapeo_lista, sync_records, doctype_target, debug_messages)
                if procesado:
                    total_procesados += 1
                    debug_messages.append(f"✅ Procesado: {procesado}")
                    print(f"✅ Procesado: {procesado}")
                    # log_sincronizacion(doctype_logs, procesado, resultado)  # ← Descomenta si deseas guardar log por registro
                else:
                    debug_messages.append(f"♻️ Cliente no procesa{detalle.get('CardCode', 'Desconocido')} – Motivo: {resultado} ✅")
                    print(f"✅ Cliente no procesado: {detalle.get('CardCode', 'Desconocido')} – Motivo: {resultado} ✅")
        
        print(f"✅ Total de registros procesados: {len(detalles)}")
        

    except Exception as e:
        error_msg = f"Error durante sincronización: {str(e)}"
        debug_messages.append(f"✗ {error_msg}")
        frappe.log_error(title="Error sincronizando clientes desde SAP", message=error_msg)

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
                detalles=detalles,  # o clientes si quieres guardar solo eso
                errores=""
            )


    return {
        "status": "success" if total_procesados > 0 else "warning",
        "total": total_procesados,
        "debug": debug_messages
    }


def procesar_dato(cliente_sap, mapeo_cliente, sync_records, doctype_target, debug_messages):
    sap_key_field = mapeo_cliente["key_field"]          
    erp_key_field = mapeo_cliente["erp_key_field"]
    for lista_mapeo in registros_sap:
        try:
            # Obtener campos clave
            sap_key_field = mapeo_cliente["key_field"]          
            erp_key_field = mapeo_cliente["erp_key_field"]     
            sap_id = cliente_sap.get(sap_key_field)

            if not sap_id:
                frappe.log_error("Cliente SAP sin custom_cardcode", json.dumps(cliente_sap, indent=2))
                return None, "Falta campo clave SAP ID"
            
            # Obtener campos de fecha y hora de actualización o creación
            update_date = cliente_sap.get("UpdateDate").split("T")[0]
            update_time = cliente_sap.get("UpdateTime")

            # Si no hay fecha/hora de actualización, usar fecha/hora de creación
            if not update_date or not update_time:
                update_date = cliente_sap.get("CreateDate").split("T")[0]
                update_time = cliente_sap.get("CreateTime")

            # Validar que al menos uno de los dos pares exista
            if not update_date or not update_time:
                frappe.log_error("Faltan campos UpdateDate/UpdateTime y CreateDate/CreateTime", json.dumps(cliente_sap, indent=2))
                return None, "Fecha de actualización no valida"

            # Convertir a datetime
            print(f"fecha de actualizacion: {update_date}")
            print(f"hora de actualizacion: {update_time}")
            update_str = f"{update_date} {update_time}"
            try:
                update_datetime = datetime.strptime(update_str, "%Y-%m-%d %H:%M:%S")
            except Exception as e:
                frappe.log_error("Error al convertir datetime", f"{update_str}\n{traceback.format_exc()}")
                return None, "Error al convertir la fecha de actualización"
            
            last_sync = sync_records.get(sap_id)
            if last_sync:
                last_sync_dt = datetime.strptime(last_sync, "%Y-%m-%d %H:%M:%S")
                if update_datetime <= last_sync_dt:
                    return None, "Cliente sin cambios"

            # Buscar cliente en ERPNext por el campo clave
            cliente_existente = frappe.get_all(doctype_target, filters={erp_key_field: sap_id}, limit=1)

            # Mapear datos SAP -> ERP
            datos_cliente = {}
            for erp_field, sap_field in mapeo_cliente["sap_fields"].items():
                valor = cliente_sap.get(sap_field)

                if erp_field == "disabled":
                    valor = 0 if valor == "tYES" else 1

                datos_cliente[erp_field] = valor
            
            # Limpieza de campos None
            datos_cliente = {k: v for k, v in datos_cliente.items() if v is not None}
            
            # Asignar lista de precios por código SAP
            listnum_sap = cliente_sap.get("PriceListNum")
            asignar_lista_precios_por_codigo_sap(datos_cliente, listnum_sap)

            # Asegurar que el campo clave esté presente
            datos_cliente[erp_key_field] = sap_id

            print("procesando código de cliente: ",sap_id)
            if cliente_existente:
                # Actualizar cliente existente
                cliente_doc = frappe.get_doc(doctype_target, cliente_existente[0].name)
                try:
                    cliente_doc.update(datos_cliente)
                    asignar_vendedor(cliente_doc, cliente_sap)
                    asignar_cliente_grupo(cliente_doc, cliente_sap)
                    # 👇 Esto ignora los permisos del usuario actual
                    cliente_doc.flags.ignore_permissions = True 
                    cliente_doc.save()
                    frappe.db.commit()  # ✅ commit después de guardar
                except frappe.exceptions.DocumentHasBeenModifiedError:
                    frappe.log_error(f"Error al actualizar cliente o asignar vendedor para {sap_id}: {str(e)}\n{traceback.format_exc()}")
                    return None, "Error DocumentHasBeenModifiedError"
                try:                
                    procesar_direcciones(cliente_sap, cliente_sap.get("BPAddresses", []), sap_id, debug_messages)
                except frappe.exceptions.DocumentHasBeenModifiedError:
                    frappe.log_error(f"error al procesar direccion {sap_id}: {str(e)}\n{traceback.format_exc()}")
                    return None, "Error DocumentHasBeenModifiedError"
                
                # Actualizar registro de sincronización
                actualizar_last_sync("Clientes", sap_id, update_datetime)
                return f"{sap_id} (actualizado)", datos_cliente
            else:
                # Crear cliente nuevo                    
                cliente_doc = frappe.new_doc(doctype_target)
                print(datos_cliente)
                cliente_doc.update(datos_cliente)                
                cliente_doc.insert()
                procesar_direcciones(cliente_sap, cliente_sap.get("BPAddresses", []), sap_id, debug_messages)
                asignar_vendedor(cliente_doc, cliente_sap)
                asignar_cliente_grupo(cliente_doc, cliente_sap)
                # 👇 Esto ignora los permisos del usuario actual
                cliente_doc.flags.ignore_permissions = True 
                cliente_doc.save()
                frappe.db.commit()  # ✅ commit después de guardar
                # Actualizar registro de sincronización
                actualizar_last_sync("Clientes", sap_id, update_datetime)
                return f"{sap_id} (creado)", datos_cliente

        except Exception as e:
            id_log = sap_id if "sap_id" in locals() else "DESCONOCIDO"
            frappe.log_error(f"Error al procesar cliente {sap_id}: {str(e)}\n{traceback.format_exc()}")
            continue
    return None, None


def asignar_vendedor(cliente_doc, cliente_sap):
    sales_employee_code = cliente_sap.get("SalesPersonCode")
    if sales_employee_code is not None and sales_employee_code != -1:
        vendedor = frappe.get_all("Sales Person", filters={"custom_salesemployeecode": sales_employee_code}, limit=1)
        if vendedor:
            nombre_vendedor = vendedor[0].name
            ya_asignado = any(st.sales_person == nombre_vendedor for st in cliente_doc.get("sales_team", []))
            if not ya_asignado:
                cliente_doc.append("sales_team", {
                    "sales_person": nombre_vendedor,
                    "allocated_percentage": 100
                })
                print(f"Asignado vendedor {nombre_vendedor} a cliente {cliente_doc.name}")
            else:
                print(f"Vendedor {nombre_vendedor} ya asignado a cliente {cliente_doc.name}")
        else:
            print(f"No se encontró vendedor con código {sales_employee_code}")
    else:
        print("Código de vendedor inválido o -1")



def asignar_cliente_grupo(cliente_doc, cliente_sap):
    """
    Asigna el Customer Group a un cliente según el GroupCode recibido de SAP.
    Si el grupo no existe, lo sincroniza y vuelve a intentar.
    """
    group_code_cliente = cliente_sap.get("GroupCode")
    grupo = frappe.get_all("Customer Group", filters={"custom_code": group_code_cliente}, limit=1)

    # Si no existe, sincronizar grupos e intentar de nuevo
    if not grupo:
        print(f"No se encontró Customer Group con código SAP '{group_code_cliente}', sincronizando...")
        sincronizar_lista_clientes_grupos()
        grupo = frappe.get_all("Customer Group", filters={"custom_code": group_code_cliente}, limit=1)

    if grupo:
        grupo_nombre = grupo[0].name
        if cliente_doc.customer_group != grupo_nombre:
            cliente_doc.customer_group = grupo_nombre
            print(f"Asignado grupo de cliente '{grupo_nombre}' al cliente {cliente_doc.name}")
        else:
            print(f"Cliente {cliente_doc.name} ya tiene asignado el grupo '{grupo_nombre}'")
    else:
        print(f"No se pudo encontrar ni crear el Customer Group con código SAP '{group_code_cliente}'")



def procesar_direcciones(cliente_sap, bp_addresses, card_code, debug_messages):
    """
    Procesa las direcciones del cliente desde SAP y las sincroniza con ERPNext.
    Maneja la creación y actualización de registros tipo Address, incluyendo links como child table.
    """

    billto_default = cliente_sap.get("BilltoDefault")
    shipto_default = cliente_sap.get("ShipToDefault")

    if not bp_addresses:
        frappe.logger().info(f"[{card_code}] Cliente sin direcciones en SAP.")
        return

    # 2. Obtener la estructura del mapeo de campos
    mapeo_direcciones = mapping_blueprint("Mapeo Cliente Direcciones", "BPCode", "custom_cardcode")
    if not mapeo_direcciones or "sap_fields" not in mapeo_direcciones:
        raise Exception("No se pudo obtener el mapeo de campos")
    print("✔ Mapeo de campos obtenido direcciones")

    cliente_erp = frappe.get_value("Customer", {"custom_cardcode": card_code}, "name")
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

            direccion_data = {
                "doctype": "Address",
                "address_title": address_title,
                mapeo_direcciones["erp_key_field"]: card_code,
                "links": [{
                    "link_doctype": "Customer",
                    "link_name": cliente_erp
                }]
            }

            # 🔹 Normalizar tipo de dirección desde SAP
            tipo_sap = direccion.get("AddressType")  # <-- campo que viene de SAP
            print(f"el tipo de direccion es: {tipo_sap}")
            if tipo_sap == "bo_BillTo":
                direccion_data["address_type"] = "Billing"
                direccion_data["is_primary_address"] = 1 if address_title == billto_default else 0
                #direccion_data["address_title"] = f"{address_title} -facturación"
                #print(f"[DEBUG] Título asignado (Billing): {direccion_data['address_title']}")
            elif tipo_sap == "bo_ShipTo":
                direccion_data["address_type"] = "Shipping"
                direccion_data["is_shipping_address"] = 1 if address_title == shipto_default else 0
                #direccion_data["address_title"] = f"{address_title} -envío"
                #print(f"[DEBUG] Título asignado (Shipping): {direccion_data['address_title']}")

            # 🔹 Mapear los demás campos
            for campo_erp, campo_sap in mapeo_direcciones["sap_fields"].items():
                if campo_erp in ["custom_cardcode", "address_title","address_type","is_primary_address","is_shipping_address"]:
                    continue

                valor = direccion.get(campo_sap)
                if not valor:
                    # Si el campo es address_line1 o city, poner por defecto "Ciudad"
                    if campo_erp in ["address_line1", "city"]:
                        valor = "Ciudad"
                        frappe.logger().warning(
                            f"⚠️ {campo_erp} estaba vacío para '{address_title}', se asignó valor por defecto: Ciudad"
                        )

                if campo_erp == "country":
                    valor = country_map.get(valor, valor or "Desconocido")

                direccion_data[campo_erp] = valor

            # 🔹 Buscar si la dirección ya existe en ERPNext
            direcciones_existentes = frappe.get_all(
                "Address",
                filters={
                    "address_title": direccion_data["address_title"],   # 👈 ya con sufijo facturación/envío
                    mapeo_direcciones["erp_key_field"]: card_code,
                    "address_type": direccion_data.get("address_type")
                },
                fields=["name"]
            )

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

                try:
                    direccion_doc.save(ignore_version=True)  # <-- evita error por modificación concurrente
                    frappe.logger().info(f"✓ Dirección actualizada: {direccion_doc.name}")
                    print(f"Dirección actualizada con título: {direccion_data['address_title']}")
                except Exception as e:
                    debug_messages.append(
                        f"[{card_code}] Error actualizando dirección '{direccion_data['address_title']}': {str(e)}\nDatos: {direccion_data}"
                    )
                    print(f"⚠️ Error actualizando dirección '{direccion_data['address_title']}': {e}")
                    continue

            else:
                print(f"Insertando nueva dirección con título: {direccion_data['address_title']}")
                if len(direccion_data.get("address_line1", "")) > 140:
                    direccion_data["address_line1"] = direccion_data["address_line1"][:139]
                    frappe.logger().warning(
                        f"⚠️ address_line1 truncado a 139 caracteres para '{direccion_data['address_title']}'"
                    )

                direccion_doc = frappe.get_doc(direccion_data)
                direccion_doc.insert()
                frappe.logger().info(f"✓ Dirección creada: {direccion_doc.name}")

        except Exception as e:
            frappe.log_error(
                f"Error procesando dirección '{direccion.get(address_title_field)}' "
                f"de {card_code}: {str(e)}\nDatos: {direccion}"
            )
            print(f"Error en dirección '{direccion.get(address_title_field)}' ")
            continue  # <-- evita que el error detenga el resto