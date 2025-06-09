import frappe
from frappe import _

@frappe.whitelist()
def obtener_lotes_disponibles(itemcode, whscode):
    try:
        lotes = frappe.get_all(
            "Stock SAP",
            filters={
                "itemcode": itemcode,
                "whscode": whscode,
                "quantity": [">", 0]
            },
            fields=["batchnum", "quantity", "expdate"],
            order_by="expdate asc"
        )

        # Opcional: convertir fechas si es necesario
        for lote in lotes:
            if isinstance(lote["expdate"], str):
                continue
            lote["expdate"] = lote["expdate"].strftime("%Y-%m-%d")

        return lotes

    except Exception as e:
        frappe.log_error(f"Error obteniendo lotes: {frappe.get_traceback()}", "Lotes SAP")
        frappe.throw(_("Hubo un problema obteniendo los lotes disponibles"))

import frappe
from frappe import _

import frappe

@frappe.whitelist()
def validar_stock_disponible(itemcode, whscode, cantidad_solicitada):
    try:
        cantidad_solicitada = float(cantidad_solicitada or 0)

        stock_doc = frappe.get_all(
            "Stock SAP",
            filters={
                "itemcode": itemcode,
                "whscode": whscode
            },
            fields=["quantity"]
        )

        stock_disponible = sum([d["quantity"] for d in stock_doc]) if stock_doc else 0

        if stock_disponible >= cantidad_solicitada:
            return {
                "disponible": True,
                "mensaje": "",
                "stock": stock_disponible
            }
        else:
            return {
                "disponible": False,
                "mensaje": f"No hay stock suficiente. Disponible: {stock_disponible}, solicitado: {cantidad_solicitada}",
                "stock": stock_disponible
            }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en validar_stock_disponible")
        return {
            "disponible": False,
            "mensaje": "Ocurrió un error al validar el stock.",
            "stock": 0
        }

