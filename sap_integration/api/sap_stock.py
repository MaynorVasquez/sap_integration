import frappe
from frappe import _
import json
import traceback  # Importación añadida
from datetime import datetime
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual
from sap_integration.api.last_update import sync_tracker, sync_tracker_update

@frappe.whitelist()
def sincronizar_lista_stock(docname=None, doctype_logs=None, almacen=None):
    

    if not doctype_logs:
        doctype_logs = "Sincronizacion Inventario SAP"
    usa_paginacion = True
    doctype_target = "Stock Entry"
    doctype_mapeo = "Mapeo Inventario SAP"
    key_erpnext = "custom_itemcode"
    key_sap = "ItemCode"
    sap_whscode = None
    config = frappe.get_doc(doctype_mapeo, docname)
    resultados = []
    empresas_a_procesar = []

    # 🔹 Caso 1: viene almacen → solo una empresa
    if almacen:
        sap_whscode = frappe.db.get_value("Warehouse", almacen, "custom_warehousecode")
        company = frappe.db.get_value("Warehouse", almacen, "company")

        # buscar la empresa en el config
        for empresa in config.company_detalle:
            if empresa.company == company:
                empresas_a_procesar.append(empresa)
                break

    # 🔹 Caso 2: no viene almacen → todas las empresas
    else:
        empresas_a_procesar = config.company_detalle

    # 🔹 Ejecutar proceso
    for empresa in empresas_a_procesar:
        resultado = procesar_empresa_individual(
            config,
            empresa,
            docname,
            procesar_datos,
            doctype_logs,
            doctype_target,
            doctype_mapeo,
            key_sap,
            key_erpnext,
            usa_paginacion,
            sap_whscode
        )

        resultados.append({
            "company": empresa.company,
            "endpoint": empresa.endpoint,
            "resultado": resultado
        })

    return resultados

def procesar_datos(registro_sap, mapeo_lista, doctype, company,debug_messages):
    print(f"valores registros sap: {registro_sap}")