import frappe
from frappe import _
import json

def logs_transactional(doctype, docnum, status, request, response, doctype_mapeo,doctype_target):
    log_name = docnum  # Usamos el ID de la factura como nombre del log

    # Asegurar que el request sea un string JSON si viene como dict
    request_str = json.dumps(request, indent=4) if isinstance(request, (dict, list)) else request
    
    # Asegurar que la respuesta sea string
    response_str = json.dumps(response, indent=4) if isinstance(response, (dict, list)) else str(response)

    if frappe.db.exists(doctype, log_name):
        # Actualizar existente
        log_doc = frappe.get_doc(doctype, log_name)
        log_doc.status = status
        log_doc.request = request_str
        log_doc.response = response_str
        log_doc.doctype_mapeo = doctype_mapeo
        log_doc.doctype_target = doctype_target
        log_doc.save(ignore_permissions=True)
    else:
        # CREACIÓN CORREGIDA: frappe.new_doc en lugar de get_new_doc
        log_doc = frappe.new_doc(doctype)
        log_doc.name = log_name
        log_doc.docnum = docnum
        log_doc.status = status
        log_doc.request = request_str
        log_doc.response = response_str
        log_doc.doctype_mapeo = doctype_mapeo
        log_doc.doctype_target = doctype_target
        log_doc.insert(ignore_permissions=True)
    
    frappe.db.commit()
    return log_doc.name