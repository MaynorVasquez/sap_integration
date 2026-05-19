import frappe
from frappe import _
from sap_integration.api.sap_auth import login_sap, get_credentials

def url_endpoint_post(doctype_mapeo, company, docname=None):

    config = frappe.get_doc(doctype_mapeo, docname)

    endpoint = None

    for empresa in config.company_detalle:
        if empresa.company == company:
            endpoint = empresa.endpoint
            break

    if not endpoint:
        frappe.log_error(f"No se encontró endpoint para la empresa {company}")
        return None

    creds, url, endpoint_login = get_credentials(company)

    full_url = f"{url.rstrip('/')}/{endpoint.lstrip('/')}"

    return full_url