import frappe
from sap_integration.sap_auth import login_sap

def test_sap_token():
    """
    Ejecuta esta función desde la consola de bench para probar la conexión
    """
    try:
        print("⏳ Probando conexión con SAP...")
        result = login_sap()
        
        if result.get("session_id"):
            print("✅ Conexión exitosa!")
            print(f"Token (B1SESSION): {result['session_id']}")
            print(f"Route ID: {result['route_id']}")
            return True
        else:
            print("❌ No se pudo obtener el token")
            return False
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    frappe.init(site="your_site_name")
    frappe.connect()
    test_sap_token()
    frappe.destroy()