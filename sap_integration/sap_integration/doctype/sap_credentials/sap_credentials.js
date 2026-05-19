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
<<<<<<< HEAD
=======

         frm.add_custom_button(__('Conexión SAP'), function() {

            if (!frm.doc.company) {
                frappe.msgprint({
                    title: __('Campo requerido'),
                    indicator: 'red',
                    message: __('Debes de seleccionar una empresa para probar la conexión')
                });
                return;
            }

            frappe.call({
                method: "sap_integration.api.sap_auth.test_sap_connection",
                args: {
                    company: frm.doc.company
                },
                freeze: true,
                freeze_message: __('Probando conexión con SAP...'),
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint({
                            title: __('Resultado'),
                            indicator: 'green',
                            message: r.message
                        });
                    }
                },
                error: function(err) {
                    frappe.msgprint({
                        title: __('Error'),
                        indicator: 'red',
                        message: __('Error al conectar con SAP')
                    });
                    console.error(err);
                }
            });

        });

>>>>>>> origin/develop
    }
});