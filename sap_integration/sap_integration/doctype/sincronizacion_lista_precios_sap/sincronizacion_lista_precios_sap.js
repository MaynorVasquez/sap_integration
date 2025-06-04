// Copyright (c) 2025, maynor and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Sincronizacion Lista Precios SAP", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on('Sincronizacion Lista Precios SAP', {
    refresh: function(frm) {
        frm.add_custom_button('Sincronizar lista de precios', function() {

            // 🟢 Mostrar barra de carga animada con spinner y botón de cancelar
            let $dialog = frappe.msgprint({
                title: "Sincronizando lista de precios...",
                message: `
                    <div class="d-flex align-items-center gap-2 mb-2">
                        <span class="spinner-border text-success" role="status" aria-hidden="true"></span>
                        <strong>Conectando con SAP y sincronizando...</strong>
                    </div>
                    <div class="progress mb-2" style="height: 20px;">
                        <div class="progress-bar progress-bar-striped progress-bar-animated bg-success"
                             role="progressbar" style="width: 100%">
                        </div>
                    </div>
                    <div class="text-end">
                        <button class="btn btn-sm btn-outline-danger btn-cancel-sync">Cancelar (visual)</button>
                    </div>
                `,
                indicator: 'green',
                keep_open: true
            });

            // ❌ Cierra el diálogo si el usuario presiona "Cancelar"
            setTimeout(() => {
                $('.btn-cancel-sync').on('click', () => {
                    if ($dialog) $dialog.hide();
                    frappe.msgprint("⛔ Cancelado visualmente. La sincronización puede seguir ejecutándose en el backend.");
                });
            }, 100);

            // 🔄 Ejecutar llamada backend
            frappe.call({
                method: "sap_integration.api.lista_precio.sincronizar_lista_precio",
                args: {
                    docname: frm.doc.name
                },
                callback: function(r) {
                    if ($dialog) $dialog.hide();

                    if (r.message) {
                        frappe.msgprint(`✓ Sincronización finalizada. Total: ${r.message.total}`);
                        frm.reload_doc();
                    } else {
                        frappe.msgprint("No se recibió respuesta del servidor.");
                    }
                },
                error: function(err) {
                    if ($dialog) $dialog.hide();
                    frappe.msgprint("❌ Error al sincronizar. Revisa los logs.");
                }
            });
        });
    }
});
