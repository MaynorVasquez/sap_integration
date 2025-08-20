import frappe

def verificar_autorizacion(usuario, doctype_objetivo):
    """
    Verifica si el usuario tiene permiso en la child table 'Campos usuarios autorizados'
    dentro del Doctype single 'Usuarios Autorizados'.
    """
    # Obtener el documento Single
    doc = frappe.get_doc("Usuarios autorizados")

    # Recorrer la tabla secundaria
    for row in doc.get("usuarios_autorizados"):
        if row.usuario == usuario and row.doc_type == doctype_objetivo:
            return True

    return False