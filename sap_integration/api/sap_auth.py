import requests
import frappe
from frappe import _
from frappe.utils import cint

def get_credentials(company):
    """
    Obtiene las credenciales SAP según la compañía seleccionada
    """

    if not frappe.db.exists("SAP Credentials", "SAP Credentials"):
        frappe.throw("Por favor configura las credenciales SAP primero")

    creds = frappe.get_doc("SAP Credentials", "SAP Credentials")

    # Buscar en la tabla hija
    for row in creds.company_sap:
        if row.company == company:
            return {
                "CompanyDB": row.companydb,
                "UserName": row.username,
                "Password": row.password
            }, row.sap_url, row.endpoint

    frappe.throw(f"No se encontraron credenciales SAP para la compañía: {company}")


def login_sap(company):
    """
    Realiza login al SAP Service Layer y retorna un objeto requests.Session configurado.
    """
    session = None
    try:
        sap_credentials, sap_url, endpoint = get_credentials(company)
        login_url = f"{sap_url.rstrip('/')}/{endpoint.strip('/')}"

        # Crear una sesión persistente
        session = requests.Session()

        timeout = float(frappe.conf.get("sap_request_timeout") or 60)
        verify_ssl = bool(cint(frappe.conf.get("sap_verify_ssl") or 0))

        response = session.post(
            login_url,
            json=sap_credentials,
            verify=verify_ssl,
            timeout=(10, timeout),
        )
        response.raise_for_status()

        # Verificar si las cookies clave están presentes
        if 'B1SESSION' not in session.cookies or 'ROUTEID' not in session.cookies:
            frappe.throw("La autenticación con SAP fue exitosa pero faltan cookies necesarias")

        return session

    except requests.exceptions.RequestException as e:
        if session:
            session.close()
        frappe.throw(f"Error al autenticar con SAP: {str(e)}")
    except Exception:
        if session:
            session.close()
        raise


@frappe.whitelist()
def test_sap_connection(company):
    """Prueba la conexión con SAP y muestra el resultado al usuario"""
    frappe.only_for("System Manager")
    session = None
    try:
        session = login_sap(company)
        message = f"Se ha establecido conexión con SAP correctamente a la empresa: {company}"
        # Si llegamos aquí, el login fue exitoso
        frappe.msgprint(
            title=_("Conexión Exitosa"),
            msg=message,
            indicator="green"
        )
        
        return True
        
    except Exception as e:
        frappe.msgprint(
            title=_("Error de Conexión"),
            msg=_("No se pudo conectar a SAP: {0}").format(str(e)),
            indicator="red"
        )
        return False
    finally:
        if session:
            session.close()


