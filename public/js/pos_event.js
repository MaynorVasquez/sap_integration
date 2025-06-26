frappe.pos_hooks.after_submit_sales_invoice = async function (doc) {
    try {
        const response = await frappe.call({
            method: "sap_integration.utils.send_sales_invoice_to_sap",
            args: {
                invoice_name: doc.name
            }
        });

        console.log("Factura enviada a SAP:", response.message);
    } catch (e) {
        console.warn("No se pudo enviar la factura a SAP. Continuando flujo normal.");
        console.error(e);
    }
};
