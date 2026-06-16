from datetime import datetime

def extraer_fecha_maxima(lista_datos, campos_delta, marca_actual):
    """
    Recorre el payload de SAP y devuelve la fecha/hora más reciente encontrada.
    """
    if not campos_delta or not lista_datos:
        return marca_actual

    # Obtenemos los nombres de los campos en SAP
    c_date_field = campos_delta.get("create_date")
    c_time_field = campos_delta.get("create_time")
    u_date_field = campos_delta.get("update_date")
    u_time_field = campos_delta.get("update_time")

    max_dt = None
    
    # Si ya teníamos una fecha anterior, la usamos como base de comparación
    if marca_actual:
        try:
            max_dt = datetime.strptime(str(marca_actual), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    for fila in lista_datos:
        # 1. Evaluar Fecha de Creación
        c_date = fila.get(c_date_field)
        c_time = fila.get(c_time_field)
        
        if c_date and c_time:
            # Asumiendo que SAP devuelve 'YYYY-MM-DD' y 'HH:MM:SS'
            dt_str = f"{c_date} {c_time}" 
            try:
                dt_obj = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                if not max_dt or dt_obj > max_dt:
                    max_dt = dt_obj
            except ValueError:
                pass

        # 2. Evaluar Fecha de Actualización (suele ser mayor si el doc fue modificado)
        u_date = fila.get(u_date_field)
        u_time = fila.get(u_time_field)
        
        if u_date and u_time:
            dt_str = f"{u_date} {u_time}"
            try:
                dt_obj = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                if not max_dt or dt_obj > max_dt:
                    max_dt = dt_obj
            except ValueError:
                pass

    # Devolvemos la fecha formateada para ERPNext
    if max_dt:
        return max_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    return marca_actual