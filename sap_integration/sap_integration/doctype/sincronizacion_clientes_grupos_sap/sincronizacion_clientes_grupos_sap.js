// Copyright (c) 2025, maynor and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Sincronizacion Clientes Grupos SAP", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on('Sincronizacion Clientes Grupos SAP', {
    refresh: function(frm) {
        frm.add_custom_button('Sincronizar Clientes Grupos SAP', function() {

            // Crear diálogo manual para mantener control total
            let dialog = new frappe.ui.Dialog({
                title: 'Sincronizando clientes grupos desde SAP',
                size: 'small',
                primary_action_label: 'Cerrar',
                primary_action: () => {
                    dialog.hide();
                }
            });

            // HTML inicial con spinner y barra animada
            dialog.$body.html(`
                <div class="d-flex align-items-center gap-2 mb-3">
                    <span class="spinner-border text-primary" role="status" aria-hidden="true"></span>
                    <strong>Conectando con SAP y sincronizando...</strong>
                </div>
                <div class="progress mb-2" style="height: 20px;">
                    <div class="progress-bar progress-bar-striped progress-bar-animated bg-primary"
                         role="progressbar" style="width: 100%">
                    </div>
                </div>
                <div class="resultado-sync mt-2 text-muted"></div>
            `);

            dialog.show();

            // Llamada al backend
            frappe.call({
                method: "sap_integration.api.sap_clientes_grupos.sincronizar_lista_clientes_grupos",
                args: {
                    docname: frm.doc.name
                },
                callback: function(r) {
                    if (r.message) {
                        // Actualiza el contenido del diálogo con el resultado
                        dialog.$body.find(".spinner-border").remove();
                        dialog.$body.find(".progress").remove();
                        dialog.$body.find(".resultado-sync").html(
                            `<div class="alert alert-success mb-0">
                                ✓ Sincronización finalizada. Total sincronizados: <strong>${r.message.total}</strong>
                            </div>`
                        );
                        frm.reload_doc();
                    } else {
                        dialog.$body.find(".resultado-sync").html(
                            `<div class="alert alert-warning">⚠ No se recibió respuesta del servidor.</div>`
                        );
                    }
                },
                error: function(err) {
                    dialog.$body.find(".spinner-border").remove();
                    dialog.$body.find(".progress").remove();
                    dialog.$body.find(".resultado-sync").html(
                        `<div class="alert alert-danger">❌ Error al sincronizar. Revisa los logs.</div>`
                    );
                }
            });
        });
    }
});
