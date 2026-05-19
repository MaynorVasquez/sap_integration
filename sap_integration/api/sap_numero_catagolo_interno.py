import frappe
from frappe import _
import json
import traceback  # Importación añadida
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual

@frappe.whitelist()
def sincronizar_numero_catalogo_interno(docname=None):
    doctype_logs = "Sincronizacion Numero de Catalogo"
    doctype_target =  "Item"
    doctype_mapeo = "Mapeo Numero de Catalogo Interno"
    key_sap = "ItemCode"
    key_erpnext = "custom_itemcode"
    

    config = frappe.get_doc(doctype_mapeo, docname)

    resultados = []

    for empresa in config.company_detalle:
        resultado = procesar_empresa_individual(config, 
                                                empresa,
                                                docname,
                                                procesar_datos,
                                                doctype_logs,
                                                doctype_target,
                                                doctype_mapeo,
                                                key_sap,
                                                key_erpnext
                                                )

        resultados.append({
            "company": empresa.company,
            "endpoint": empresa.endpoint,
            "resultado": resultado
        })

    return resultados


def procesar_datos(registros_sap, mapeo_lista, doctype, company,debug_messages):
    sap_key_field = mapeo_lista["key_field"]
    erp_key_field = mapeo_lista["erp_key_field"]
    for lista_mapeo in registros_sap:
        try:
            sap_id = lista_mapeo.get(sap_key_field)
            dato_existente = frappe.db.sql("""
                SELECT T0.name
                FROM `tabItem` T0
                INNER JOIN `tabItem Default` T1
                    ON T0.name = T1.parent
                WHERE T0.{erp_key_field} = %s
                AND T1.company = %s
                LIMIT 1
            """.format(erp_key_field=erp_key_field), (sap_id, company), as_dict=True)

            CardCode = lista_mapeo.get("CardCode")
            dato_cliente = frappe.get_all(
                "Customer",
                filters={
                    "custom_cardcode": CardCode,
                    "custom_company": company
                },
                limit=1
            )

            if dato_cliente and dato_existente:

                customer_name = dato_cliente[0].name
                item_name = dato_existente[0].name

                item_doc = frappe.get_doc("Item", item_name)

                # Buscar si ya existe registro
                fila_existente = None

                for row in item_doc.customer_items:
                    if row.customer_name == customer_name:
                        fila_existente = row
                        break

                # Si existe -> actualizar
                if fila_existente:

                    fila_existente.ref_code = lista_mapeo.get("Substitute")

                    # otros campos
                    # fila_existente.customer_item_name = ...

                    debug_messages.append(
                        f"Actualizado código cliente {customer_name} para item {item_name}"
                    )

                # Si NO existe -> insertar
                else:

                    item_doc.append("customer_items", {
                        "customer_name": customer_name,
                        "ref_code": lista_mapeo.get("Substitute")
                    })

                    debug_messages.append(
                        f"Insertado código cliente {customer_name} para item {item_name}"
                    )
                item_doc.save(ignore_permissions=True)
                frappe.db.commit()

        except Exception as e:
            frappe.log_error(
                f"Error al procesar datos {sap_id}: {str(e)}\n{traceback.format_exc()}"
            )
            return None, None
    return None, None