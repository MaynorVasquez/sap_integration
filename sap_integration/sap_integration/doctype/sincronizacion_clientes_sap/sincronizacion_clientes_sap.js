// Copyright (c) 2025, maynor and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Sincronizacion clientes SAP", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on('Sincronizacion clientes SAP', {
    refresh: function(frm) {
        frm.add_custom_button('Sincronizar Clientes SAP', function() {
            frappe.call({
                method: "sap_integration.api.sap_clientes.sincronizar_clientes_desde_sap",
                args: {
                    docname: frm.doc.name  // 👈 esto es CLAVE
                },
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint(`✓ Sincronización finalizada. Total: ${r.message.total}`);
                        frm.reload_doc();  // Refresca para ver los campos actualizados
                    }
                }
            });
        });
    }
});
