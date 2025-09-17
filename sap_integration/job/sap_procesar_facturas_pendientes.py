import frappe
from sap_integration.api.sap_facturas import factura_deudores

def procesar_facturas_pendientes():
    try:
        # Traer el documento de configuración de perfiles de facturación
        doc = frappe.get_doc("Perfiles de facturacion")

        # Obtener todos los perfiles autorizados desde la child table
        perfiles = [row.sales_invoice_profile for row in doc.get("perfiles_autorizados")]

        if not perfiles:
            frappe.logger().info("No hay perfiles autorizados configurados en Perfiles de facturación.")
            return

        # Buscar facturas pendientes (sin custom_docnum, en los perfiles autorizados)
        facturas = frappe.get_all("Sales Invoice",
            filters={
                "pos_profile": ["in", perfiles],
                "docstatus": 1,
                "is_return": 0, 
                "custom_docnum": ["in", ["", None]],  # vacío o null
            },
            fields=["name"]
        )

        #return facturas

        if not facturas:
            frappe.logger().info("No hay facturas pendientes para enviar a SAP.")
            return

        for f in facturas:
            try:
                factura_deudores(f["name"])
            except Exception as e:
                frappe.logger().error(f"Error al procesar factura {f['name']}: {str(e)}")

    except Exception as e:
        frappe.logger().error(f"Error en procesar_facturas_pendientes: {str(e)}")