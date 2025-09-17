import frappe
from sap_integration.api import (
    sap_almacenes,
    sap_articulos_grupo,
    sap_categoria_uom,
    sap_clientes_grupos,
    sap_lista_precio,
    sap_vendedores

)

def job_secuenciales():
    # --- Jobs ligeros secuenciales ---
    ligeros = [
        ("Almacenes", sap_almacenes.sincronizar_lista_alamacenes),
        ("Grupo de articulos", sap_articulos_grupo.sincronizar_articulos_grupo),
        ("Categoria UOM", sap_categoria_uom.sincronizar_lista_categoria_uom),
        ("Lista UOM", sap_categoria_uom.sincronizar_lista_uom),
        ("Lista UOM Conversion", sap_categoria_uom.sincronizar_factores_conversion),
        ("Grupo cliente", sap_clientes_grupos.sincronizar_lista_clientes_grupos),
        ("Lista de precios", sap_lista_precio.sincronizar_lista_precio),
        ("Vendedores", sap_vendedores.sincronizar_lista_vendedores),
    ]

    for nombre, funcion in ligeros:
        try:
            frappe.logger().info(f"Iniciando job: {nombre}")
            funcion()
            frappe.logger().info(f"Job finalizado: {nombre}")
        except Exception as e:
            frappe.log_error(f"Error en job {nombre}: {e}", title="Error Job Maestro")

    # --- Jobs pesados en background usando enqueue ---
    # Primero Artículos (depende de Unidad de medida)
    try:
        frappe.enqueue(
            method="sap_integration.api.sap_articulos.sincronizar_lista_articulos",
            queue="long",
            timeout=6000,
            job_name="Artículos"
        )
        frappe.logger().info("Job 'Artículos' encolado correctamente")
    except Exception as e:
        frappe.log_error(f"Error en job Artículos: {e}", title="Error Job Maestro")

    # Después Clientes (puede depender de Artículos)
    try:
        frappe.enqueue(
            method="sap_integration.api.sap_clientes.sincronizar_clientes_desde_sap",
            queue="long",
            timeout=6000,
            job_name="Clientes"
        )
        frappe.logger().info("Job 'Clientes' encolado correctamente")
    except Exception as e:
        frappe.log_error(f"Error en job Clientes: {e}", title="Error Job Maestro")
    
    # Después stock puede llegar a ser el mas pesado
    try:
        frappe.enqueue(
            method="sap_integration.api.sap_stock.sincronizar_lista_stock",
            queue="long",
            timeout=6000,
            job_name="Inventario"
        )
        frappe.logger().info("Job 'Inventario encolado correctamete")
    except Exception as e:
        frappe.log_error(f"Error en job inventario: {e}", title="Error Job Maestro")
