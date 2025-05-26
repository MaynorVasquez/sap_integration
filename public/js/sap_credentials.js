frappe.ui.form.on('SAP Credentials', {
    refresh: function(frm) {
        // Mover el botón a la sección correcta
        frm.add_custom_button(__('Probar Conexión'), function() {
            frm.call({
                method: 'test_sap_connection',
                doc: frm.doc,
                freeze: true,
                freeze_message: __('Probando conexión con SAP...'),
                callback: function(r) {
                    if (!r.exc) {
                        frm.reload_doc();
                    }
                }
            });
        }, __("Pruebas de Conexión")).addClass('btn-primary');
    }
});