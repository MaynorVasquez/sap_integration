from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, unquote_plus
from frappe.utils import get_datetime
import frappe
from frappe import _

def construir_filtro_tiempo(ultima_sync, campos_delta):

    if not ultima_sync or not campos_delta:
        return None

    dt = get_datetime(ultima_sync)
    sap_date = dt.strftime("%Y-%m-%d")
    
    # NOTA: Según tu ejemplo asumo que SAP Service Layer espera la hora así: '13:14:00'
    # Si requiere un entero como 1314, cambiarías a: dt.strftime("%H%M") sin comillas simples en el string final.
    sap_time = dt.strftime("%H:%M:%S") 

    c_date = campos_delta.get("create_date")
    c_time = campos_delta.get("create_time")
    u_date = campos_delta.get("update_date")
    u_time = campos_delta.get("update_time")

    filtros_partes = []

    # Bloque de Creación
    if c_date and c_time:
        f_create = f"(({c_date} gt '{sap_date}') or ({c_date} eq '{sap_date}' and {c_time} ge '{sap_time}'))"
        filtros_partes.append(f_create)

    # Bloque de Actualización
    if u_date and u_time:
        f_update = f"(({u_date} gt '{sap_date}') or ({u_date} eq '{sap_date}' and {u_time} ge '{sap_time}'))"
        filtros_partes.append(f_update)

    if filtros_partes:
        # Unimos Creación y Actualización con un OR
        return f"({' or '.join(filtros_partes)})"
    
    return None

def inyectar_filtro_a_url(url_original, filtro_delta):
    """
    Descompone la URL, anexa el filtro delta al $filter existente (si hay) y la reconstruye con espacios.
    """
    if not filtro_delta:
        return url_original

    partes_url = urlparse(url_original)
    query_params = parse_qs(partes_url.query)

    if '$filter' in query_params:
        filtro_existente = query_params['$filter'][0]
        nuevo_filtro_completo = f"({filtro_existente}) and {filtro_delta}"
        query_params['$filter'] = [nuevo_filtro_completo]
    else:
        query_params['$filter'] = [filtro_delta]

    # Aquí Python mete los '+' en lugar de espacios
    nueva_query = urlencode(query_params, doseq=True)

    url_final_codificada = urlunparse((
        partes_url.scheme,
        partes_url.netloc,
        partes_url.path,
        partes_url.params,
        nueva_query,
        partes_url.fragment
    ))

    # 2. MAGIA: unquote_plus limpia la cadena y transforma los '+' en espacios literales
    url_final_limpia = unquote_plus(url_final_codificada)

    return url_final_limpia