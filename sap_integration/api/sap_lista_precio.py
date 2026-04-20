import frappe
from frappe import _
import json
import traceback  # Importación añadida
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual

@frappe.whitelist()

def sincronizar_lista_precio(docname=None):
    doctype_logs = "Sincronizacion Lista Precios SAP"
    doctype_target =  "Price List"
    doctype_mapeo = "Mapeo Lista De Precios SAP"
    key_erpnext = "custom_pricelistno"
    key_sap = "PriceListNo"

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
                                                key_erpnext
                                                )

        resultados.append({
            "company": empresa.company,
            "endpoint": empresa.endpoint,
            "resultado": resultado
        })

    return resultados

def procesar_datos(lista_mapeo, mapeo_lista, doctype, company,debug_messages):
#def procesar_datos(lista_precio, mapeo_lista, doctype):
    """"Crea o actualiza lista de precios en ERPNEXT"""
    try:
        # Obtener campos clave
        sap_key_field = mapeo_lista["key_field"]          # Ej: "KeySAP"
        erp_key_field = mapeo_lista["erp_key_field"]      # Ej: "custom_ERPNEXT"
        sap_id = lista_mapeo.get(sap_key_field)
        

        if not sap_id:
            frappe.log_error("Dato sin código", json.dumps(lista_mapeo, indent=2))
            return None, None  # No se puede continuar sin ID

        # Buscar datos ERPNEXT
        lista_existente = frappe.get_all(
            doctype,
            filters={
                erp_key_field: sap_id,
                "custom_company": company
            },
            limit=1
        )

        # ✅ Ahora se utiliza el head 
        campos = mapeo_lista.get("sap_fields", {}).get("head", {})

        # Mapear datos SAP -> ERP
        datos_lista_precio = {}
        nuevo_nombre = None
        company_abbr = frappe.get_value("Company", company, "abbr")
        for erp_field, sap_field in campos.items():
            valor = lista_mapeo.get(sap_field)

            # Corrección de moneda
            if erp_field == "currency" and valor == "QTZ":
                valor = "GTQ"

            if erp_field == "enabled":
                valor = 1 if valor == "tYES" else 0
            
            if erp_field == "price_list_name":
                valor = f"{company_abbr} - {valor}"
            
            if erp_field == "name":
                nuevo_nombre = f"{company_abbr} - {valor}"
                continue

            datos_lista_precio[erp_field] = valor
        
        
        # Asegurar que el campo clave esté presente
        datos_lista_precio[erp_key_field] = sap_id
        # Asegurar campos obligatorios en ERPNext
        datos_lista_precio.setdefault("selling", 1)
        datos_lista_precio.setdefault("buying", 1)
        datos_lista_precio["custom_company"] = company

        if lista_existente:
            # Actualizar lista de precios existente
            lista_precio_doc = frappe.get_doc(doctype, lista_existente[0].name)
            for campo, valor in datos_lista_precio.items():
                if campo != "name":
                    setattr(lista_precio_doc, campo, valor)

                debug_messages.append(f"Update --> campo: {campo} --- valor: {valor}")
                setattr(lista_precio_doc, campo, valor)
                
                lista_precio_doc.flags.ignore_permissions = True 
                lista_precio_doc.save()
                frappe.db.commit()

            if nuevo_nombre and lista_precio_doc.name != nuevo_nombre:
                if not frappe.db.exists(doctype, nuevo_nombre):
                    frappe.rename_doc(doctype, lista_precio_doc.name, nuevo_nombre, force=True)

            return f"{sap_id} (actualizado)", datos_lista_precio
        else:
            # Crea Lista de precios Nuevo
            lista_precio_doc = frappe.new_doc(doctype)
            for campo, valor in datos_lista_precio.items():
                debug_messages.append(f"insert --> campo: {campo} --- valor: {valor}")
                setattr(lista_precio_doc, campo, valor)
            # 👇 Esto ignora los permisos del usuario actual
            lista_precio_doc.flags.ignore_permissions = True 
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



