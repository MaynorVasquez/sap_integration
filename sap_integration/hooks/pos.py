import frappe
from frappe.exceptions import ValidationError

def validate_stock_before_pos_submit(pos_doc, method=None):
    for item in pos_doc.items:
        item_code = item.item_code
        warehouse = pos_doc.set_warehouse or item.warehouse
        qty_needed = item.qty

        if not warehouse or not item_code:
            continue

        # Verifica si el artículo requiere lote
        has_batch = frappe.db.get_value("Item", item_code, "has_batch_no")

        if has_batch:
            if not item.batch_no:
                raise ValidationError(f"Debes seleccionar un lote para el artículo {item_code}.")

            # Verifica el stock del lote
            stock_lote = frappe.db.get_value("Stock SAP", {
                "itemcode": item_code,
                "whscode": warehouse,
                "batchnum": item.batch_no
            }, "quantity") or 0

            if stock_lote < qty_needed:
                raise ValidationError(
                    f"No hay suficiente stock del lote {item.batch_no} para el artículo {item_code} en {warehouse}. "
                    f"Stock disponible: {stock_lote}, requerido: {qty_needed}."
                )

        else:
            # Stock sin lote
            stock = frappe.db.get_value("Stock SAP", {
                "itemcode": item_code,
                "whscode": warehouse
            }, "quantity") or 0

            if stock < qty_needed:
                raise ValidationError(
                    f"No hay suficiente stock para el artículo {item_code} en {warehouse}. "
                    f"Stock disponible: {stock}, requerido: {qty_needed}."
                )
