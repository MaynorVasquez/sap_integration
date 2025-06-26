import requests
import frappe
from frappe import _
from frappe.utils import cint

@frappe.whitelist()
def get_sap_credentials():
    """
    Obtiene las credenciales SAP desde el Doctype
    """
    if not frappe.db.exists("SAP Credentials", "SAP Credentials"):
        frappe.throw("Por favor configura las credenciales SAP primero")
    
    creds = frappe.get_doc("SAP Credentials", "SAP Credentials")
    return {
        "CompanyDB": creds.companydb,
        "UserName": creds.username,
        "Password": creds.password
    }, creds.sap_url
@frappe.whitelist()

def login_sap():
    """
    Realiza login al SAP Service Layer y retorna un objeto requests.Session configurado.
    """
    try:
        sap_credentials, sap_url = get_sap_credentials()

        # Crear una sesión persistente
        session = requests.Session()

        response = session.post(
            f"{sap_url}/Login",
            json=sap_credentials,
            verify=False  # ⚠️ solo para pruebas
        )
        response.raise_for_status()

        # Verificar si las cookies clave están presentes
        if 'B1SESSION' not in session.cookies or 'ROUTEID' not in session.cookies:
            frappe.throw("La autenticación con SAP fue exitosa pero faltan cookies necesarias")

        return session

    except requests.exceptions.RequestException as e:
        frappe.throw(f"Error al autenticar con SAP: {str(e)}")


@frappe.whitelist()
def test_sap_connection():
    """Prueba la conexión con SAP y muestra el resultado al usuario"""
    try:
        result = login_sap()
        
        # Si llegamos aquí, el login fue exitoso
        frappe.msgprint(
            title=_("Conexión Exitosa"),
            msg=_("Se ha establecido conexión con SAP correctamente"),
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


