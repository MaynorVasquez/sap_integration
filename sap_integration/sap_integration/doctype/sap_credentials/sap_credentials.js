// Copyright (c) 2025, maynor and contributors
// For license information, please see license.txt

// frappe.ui.form.on("SAP Credentials", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on('SAP Credentials', {
    refresh: function(frm) {
        frm.add_custom_button(__('Probar Conexión SAP'), function() {
            frappe.call({
                method: "sap_integration.api.sap_auth.test_sap_connection",
                args: {
                    "doc": frm.doc  // Pasamos el documento completo como argumento
                },
                freeze: true,
                freeze_message: __("Probando conexión con SAP..."),
                callback: function(r) {
                    // Los mensajes ya se manejan desde Python
                    // Puedes agregar lógica adicional aquí si necesitas
                }
            });
        }).addClass("btn-primary");
    }
});