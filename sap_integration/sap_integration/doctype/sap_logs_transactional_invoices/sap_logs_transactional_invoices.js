// sap_logs_transactional_invoices.js

frappe.ui.form.on('SAP Logs Transactional Invoices', {
    refresh: function(frm) {
        // Mostramos el botón solo si el registro ya existe y falló
        if (!frm.is_new() && frm.doc.status === 'Error') {
            
            frm.add_custom_button(__('Reenviar a SAP'), function() {
                frappe.confirm(
                    __('¿Deseas reenviar este registro usando el JSON actual? (Puedes editarlo antes de enviar)'), 
                    () => {
                        ejecutar_reenvio(frm);
                    }
                );
            }).addClass('btn-primary');
        }
    }
});

function ejecutar_reenvio(frm) {
    frappe.call({
        method: "sap_integration.utils.procesar_log_request.procesar_log_request",
        args: {
            // Enviamos el Doctype actual (ej. SAP Logs Transactional Invoices)
            "doctype": frm.doc.doctype,
            // Enviamos el Name del registro (que es el ID del log)
            "docname": frm.doc.name
        },
        freeze: true,
        freeze_message: __("Procesando reintento en SAP..."),
        callback: function(r) {
            if (r.message) {
                // Si la función retorna el DocNum de SAP o data, recargamos
                frm.reload_doc();
            }
        }
    });
}