import frappe
from frappe import _
import json
import traceback  # Importación añadida
from datetime import datetime
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual

@frappe.whitelist()

def sincronizar_lista_articulos(docname=None):
    doctype_logs = "Sincronizacion clientes SAP"
    doctype_target =  "Customer"
    doctype_mapeo = "Mapeo Articulo SAP"
    key_erpnext = "custom_itemcode"
    key_sap = "ItemCode"

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

def procesar_datos(registro_sap, mapeo_lista, doctype, company,debug_messages):
    return 1