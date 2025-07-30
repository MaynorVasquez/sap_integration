import requests

# ⚙️ CONFIGURA TUS DATOS AQUÍ
SAP_BASE_URL = "https://apisap.yaesta.com.gt/b1s/v1"
SAP_USER = "manager"
SAP_PASSWORD = "123456"
SAP_COMPANY = "PruebasYAESTA"

def prueba_login_y_get_cliente():
    try:
        session = requests.Session()

        # 1. LOGIN
        login_payload = {
            "UserName": SAP_USER,
            "Password": SAP_PASSWORD,
            "CompanyDB": SAP_COMPANY
        }

        print("Iniciando login...")
        login_response = session.post(f"{SAP_BASE_URL}/Login", json=login_payload)
        login_response.raise_for_status()
        print("✔ Login exitoso")
        print("Cookies obtenidas:", session.cookies.get_dict())

        # 2. CONSULTAR UN CLIENTE (GET)
        url_clientes = f"{SAP_BASE_URL}/BusinessPartners?$top=1"
        print("Consultando primer cliente...")
        response = session.get(url_clientes)
        print("Código de respuesta:", response.status_code)

        if response.status_code == 200:
            datos = response.json().get("value", [])
            if datos:
                print("✔ Cliente recibido:")
                print(datos[0])
            else:
                print("⚠ No se recibió ningún cliente.")
        else:
            print("✗ Error al obtener cliente:", response.text)

    except Exception as e:
        print("✗ Excepción durante la prueba:", str(e))

# Ejecutar la función
prueba_login_y_get_cliente()
