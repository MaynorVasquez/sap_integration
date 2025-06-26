def existe_stock_entry(item_code, warehouse, cantidad, batch_no, tipo):
    """
    Verifica si ya se ha realizado un Stock Entry (entrada o salida) para el ítem con lote y almacén,
    con la misma cantidad.
    """
    stock_entry_type = "Material Receipt" if tipo == "In" else "Material Issue"
    warehouse_field = "t_warehouse" if tipo == "In" else "s_warehouse"

    query = f"""
        SELECT SUM(sed.qty) AS total_qty
        FROM `tabStock Entry` se
        JOIN `tabStock Entry Detail` sed ON se.name = sed.parent
        WHERE se.stock_entry_type = %(stock_entry_type)s
        AND sed.item_code = %(item_code)s
        AND sed.batch_no = %(batch_no)s
        AND sed.{warehouse_field} = %(warehouse)s
        AND se.docstatus = 1
    """

    result = frappe.db.sql(query, {
        "stock_entry_type": stock_entry_type,
        "item_code": item_code,
        "batch_no": batch_no,
        "warehouse": warehouse
    }, as_dict=True)

    cantidad_existente = flt(result[0].get("total_qty") or 0)
    ya_ajustada = abs(cantidad_existente - cantidad) < 0.0001

    print(f"🔎 Verificación Stock Entry ({stock_entry_type}) → {item_code} / {batch_no} / {warehouse} | Ya ajustado: {cantidad_existente} | Esperado: {cantidad} | Coincide: {ya_ajustada}")

    return ya_ajustada