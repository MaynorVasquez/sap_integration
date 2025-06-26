import frappe
from frappe import _
import requests
import json
import traceback  # Importación añadida
from collections import defaultdict

def obtener_mapeo(doctype_padre, doctype_hijo, campos_mapeo):
    """
    Función genérica para obtener mapeos entre sistemas

    Args:
        doctype_padre (str): Nombre del Doctype padre (ej: "Mapeo Cliente")
        doctype_hijo (str): Nombre del Doctype hijo/table (ej: "Mapeo Campos SAP")
        campos_mapeo (dict): Diccionario con los campos a mapear 
                             (ej: {"campo_erp": "campo_erpnext", "campo_externo": "campo_sap"})

    Returns:
        dict: {"success": bool, "data": list, "count": int, "error": str}
    """
    try:
        # Validación de existencia de Doctypes
        if not frappe.db.exists("DocType", doctype_padre):
            return {"success": False, "error": _(f"Doctype padre '{doctype_padre}' no existe")}

        if not frappe.db.exists("DocType", doctype_hijo):
            return {"success": False, "error": _(f"Doctype hijo '{doctype_hijo}' no existe")}

        # Construcción dinámica de campos para la consulta
        campos_select = [
            f"parent AS documento_padre",
            f"{campos_mapeo['campo_erp']} AS campo_erpnext",
            f"{campos_mapeo['campo_externo']} AS campo_sap"
        ]

        # Campos opcionales
        if "tipo" in campos_mapeo:
            campos_select.append(f"{campos_mapeo['tipo']} AS tipo")
        if "valor" in campos_mapeo:
            campos_select.append(f"{campos_mapeo['valor']} AS valor")
        if "nivel" in campos_mapeo:
            campos_select.append(f"{campos_mapeo['nivel']} AS nivel")

        # Consulta a la base de datos
        registros = frappe.db.sql(f"""
            SELECT {', '.join(campos_select)}
            FROM `tab{doctype_hijo}`
            WHERE parenttype = %s
        """, doctype_padre, as_dict=True)

        return {
            "success": True,
            "count": len(registros),
            "data": registros
        }

    except Exception as e:
        frappe.log_error(_("Error en obtener_mapeo"), f"Doctypes: {doctype_padre}/{doctype_hijo}\nError: {str(e)}")
        return {"success": False, "error": str(e)}


def mapping_blueprint(doctype, key_field_sap, key_field_erpnext):
    """Obtiene el mapeo de campos desde un Doctype personalizado, incluyendo URL y filtros opcionales."""
    resultado = obtener_mapeo(
        doctype_padre=doctype,
        doctype_hijo="Mapeo campos",
        campos_mapeo={
            "campo_erp": "campo_erpnext",
            "campo_externo": "campo_sap",
            "tipo": "tipo",          # puede ser 'map', 'url' o 'filter'
            "valor": "valor"         # usado para filtros y url
        }
    )

    if not resultado or not resultado.get('success') or not resultado.get('data'):
        frappe.throw("No se pudo obtener el mapeo de campos o la estructura es inválida.")

    mapeo = {
        "key_field": key_field_sap,
        "erp_key_field": key_field_erpnext,
        "sap_fields": {},
        "defaults": {},
        "url": None,
        "filters": []
    }

    for item in resultado["data"]:
        tipo = (item.get("tipo") or "").strip().lower()
        campo_erp = (item.get("campo_erpnext") or "").strip()
        campo_sap = (item.get("campo_sap") or "").strip()
        valor = (item.get("valor") or "").strip()

        if tipo == "map":
            if campo_erp and campo_sap:
                mapeo["sap_fields"][campo_erp] = campo_sap
            continue

        elif tipo == "url" and valor:
            mapeo["url"] = valor

        elif tipo == "filter" and campo_sap and valor:
            valores = [v.strip() for v in valor.split(",") if v.strip()]
            if len(valores) > 1:
                filtro = f"{campo_sap} in ({', '.join([f'\'{v}\'' for v in valores])})"
            else:
                filtro = f"{campo_sap} eq '{valores[0]}'"
            mapeo["filters"].append(filtro)

    # Si no hay campos mapeados pero sí hay URL, se permite continuar
    if not mapeo["sap_fields"] and not mapeo["url"]:
        frappe.throw("No se encontraron campos mapeados ni URL para consumir los datos.")

    return mapeo


def construir_filtro(lista_filtros):
    if not lista_filtros:
        return ""

    grupos = defaultdict(list)

    for filtro in lista_filtros:
        partes = filtro.split(" eq ")
        if len(partes) == 2:
            campo = partes[0].strip()
            valor = partes[1].strip()
            grupos[campo].append(f"{campo} eq {valor}")

    condiciones = []
    for grupo in grupos.values():
        if len(grupo) == 1:
            condiciones.append(grupo[0])
        else:
            condiciones.append(f"({' or '.join(grupo)})")

    return " and ".join(condiciones)


def construir_url_sap(mapeo_lista: dict, top: int = 20, skip: int = 0):
    """
    Construye la URL final a consumir desde SAP Service Layer usando el mapeo proporcionado.
    """
    if not mapeo_lista or "url" not in mapeo_lista:
        raise ValueError("El mapeo no contiene una URL válida.")

    try:
        base_url = mapeo_lista["url"]
        campos = mapeo_lista.get("sap_fields", {})
        filtros = mapeo_lista.get("filters", [])
        
        params = []

        if filtros:
            filtro_sap = construir_filtro(filtros)
            params.append(f"$filter={filtro_sap}")

        if campos:
            select_fields = ",".join(campos.values())
            params.append(f"$select={select_fields}")

        params.append(f"$top={top}")
        params.append(f"$skip={skip}")

        url_final = f"{base_url}?" + "&".join(params)
        return url_final

    except Exception as e:
        frappe.log_error("Error en construcción de URL SAP", traceback.format_exc())
        raise Exception(f"Error construyendo la URL SAP: {str(e)}")
    

def mapping_blueprint1(doctype, key_field_sap, key_field_erpnext):
    """Obtiene el mapeo de campos desde un Doctype personalizado, organizando por niveles: head, DocumentLines y BatchNumbers."""
    resultado = obtener_mapeo(
        doctype_padre=doctype,
        doctype_hijo="Mapeo campos",
        campos_mapeo={
            "campo_erp": "campo_erpnext",
            "campo_externo": "campo_sap",
            "tipo": "tipo",          # puede ser 'map', 'url' o 'filter'
            "valor": "valor",        # usado para filtros y url
            "nivel": "nivel"         # 'head', 'DocumentLines', 'BatchNumbers'
        }
    )

    if not resultado or not resultado.get('success') or not resultado.get('data'):
        frappe.throw("No se pudo obtener el mapeo de campos o la estructura es inválida.")

    mapeo = {
        "key_field": key_field_sap,
        "erp_key_field": key_field_erpnext,
        "sap_fields": {
            "head": {},
            "DocumentLines": {},
            "BatchNumbers": {}
        },
        "defaults": {},
        "url": None,
        "filters": []
    }

    for item in resultado["data"]:
        tipo = (item.get("tipo") or "").strip().lower()
        campo_erp = (item.get("campo_erpnext") or "").strip()
        campo_sap = (item.get("campo_sap") or "").strip()
        valor = (item.get("valor") or "").strip()
        nivel = (item.get("nivel") or "").strip()
        #print(f"línea con valores: {tipo} | {campo_erp} | {campo_sap} | {nivel}")
        if nivel not in ["head", "DocumentLines", "BatchNumbers"]:
            nivel = "DocumentLines"

        if tipo == "map":
            if campo_erp and campo_sap:
                if nivel not in mapeo["sap_fields"]:
                    mapeo["sap_fields"][nivel] = {}
                mapeo["sap_fields"][nivel][campo_erp] = campo_sap
            continue

        elif tipo == "url" and valor:
            mapeo["url"] = valor

        elif tipo == "filter" and campo_sap and valor:
            valores = [v.strip() for v in valor.split(",") if v.strip()]
            if len(valores) > 1:
                filtro = f"{campo_sap} in ({', '.join([f'\'{v}\'' for v in valores])})"
            else:
                filtro = f"{campo_sap} eq '{valores[0]}'"
            mapeo["filters"].append(filtro)

    if not any(mapeo["sap_fields"].values()) and not mapeo["url"]:
        frappe.throw("No se encontraron campos mapeados ni URL para consumir los datos.")

    return mapeo
