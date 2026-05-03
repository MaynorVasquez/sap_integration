import frappe
from frappe import _
import json
import requests
from sap_integration.api.sap_auth import login_sap
from sap_integration.utils.url_endpoint_post import url_endpoint_post

@frappe.whitelist()
def procesar_log_request(doctype, docname):
    try:
        doc = frappe.get_doc(doctype, docname)
        company = doc.company
        doctype_mapeo = doc.doctype_mapeo
        doctype_target = doc.doctype_target
        
        # Validar Payload
        payload = doc.request
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                frappe.throw(_("El JSON del Request es inválido. Verifique comas o llaves."))

        session = login_sap(company)
        url = url_endpoint_post(doctype_mapeo, company)

        try:
            response = session.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
            try:
                data = response.json()
            except (ValueError, json.JSONDecodeError):
                data = {}

            if response.status_code in (200, 201):
                # Usamos .get() solo si data es un diccionario
                sap_docnum = data.get("DocNum") if isinstance(data, dict) else None
                
                doc.db_set({
                    "status": "Success",
                    "response": f"Documento enviado con exito, referencia SAP: {sap_docnum}" #json.dumps(data, indent=4) if data else response.text
                })

                if sap_docnum:
                    frappe.db.set_value(doctype_target, docname, "custom_docnum", sap_docnum)
                    frappe.msgprint(_(f"Éxito: Documento {sap_docnum} creado en SAP"), indicator='green')
                
                frappe.db.commit()
                return data
            else:
                error_final = response.text
                # 3. Actualizar el log
                doc.db_set({
                    "status": "Error",
                    "response": error_final
                })
                frappe.msgprint(f"Error: {error_final}")
                frappe.db.commit()

        except requests.exceptions.RequestException as e:
            frappe.throw(_(f"Error de red/conexión: {str(e)}"))

    except Exception as e:
        # Esto captura errores de lógica del script
        frappe.log_error(frappe.get_traceback(), _("Error en procesar_log_request"))
        frappe.throw(_(f"Error interno en el script: {str(e)}"))