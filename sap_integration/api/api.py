@frappe.whitelist()
def obtener_stock_sap(item_code, warehouse):
    stock = frappe.db.get_value("Stock SAP", {
        "itemcode": item_code,
        "whscode": warehouse
    }, "quantity") or 0

    return {"quantity": stock}
