import frappe
from frappe import _
import json
import traceback  # Importación añadida
from sap_integration.utils.procesar_empresa_individual import procesar_empresa_individual

@frappe.whitelist()

def sincronizar_uom_conversion(docname=None):
    doctype_logs = "Sincronizacion UOM"
    doctype_target =  "UOM Conversion Factor"
    doctype_mapeo = "Mapeo UOM factores conversion SAP"
    key_sap = "AbsEntry"
    key_erpnext = "custom_absentry"

    config = frappe.get_doc(doctype_mapeo, docname)

    resultados = []

    for empresa in config.company_detalle:
        print(f"empresa: {empresa.company}")
        resultado = procesar_empresa_individual(config, 
                                                empresa,
                                                docname,
                                                procesar_datos,
                                                doctype_logs,
                                                doctype_target,
                                                doctype_mapeo,
                                                key_sap,
                                                key_erpnext,
                                                usa_paginacion=False
                                                )
        resultados.append({
            "company": empresa.company,
            "endpoint": empresa.endpoint,
            "resultado": resultado
        })

    return resultados


def procesar_datos(datos_sap, mapeo_lista, doctype, company, debug_messages):
    try:
        resultados = []

        absentry_category = datos_sap.get("AbsEntry")
        baseuom = datos_sap.get("BaseUoM")
        colecciones = datos_sap.get("UoMGroupDefinitionCollection", [])
        campos = mapeo_lista.get("sap_fields", {}).get("DocumentLines", {})

        uom_category = frappe.get_value(
            "UOM Category",
            {"custom_absentry": absentry_category, "custom_company": company},
            "name"
        )

        to_uom = frappe.get_value(
            "UOM",
            {"custom_absentry": baseuom, "custom_company": company},
            "name"
        )

        for colection in colecciones:
            alt_uom_code = colection.get("AlternateUoM")
            uom_base = colection.get("BaseQuantity")

            from_uom_sap = frappe.get_value(
                "UOM",
                {"custom_absentry": alt_uom_code, "custom_company": company},
                "name"
            )

            dato_lista = {}

            for erp_field, sap_field in campos.items():
                valor = datos_sap.get(sap_field)

                if erp_field == "category":
                    valor = uom_category
                elif erp_field == "from_uom":
                    valor = from_uom_sap
                elif erp_field == "to_uom":
                    valor = to_uom
                elif erp_field == "value":
                    valor = uom_base

                dato_lista[erp_field] = valor

            # 🔍 Buscar si existe
            dato_existente = frappe.get_all(
                "UOM Conversion Factor",
                filters={
                    "category": uom_category,
                    "from_uom": from_uom_sap,
                    "to_uom": to_uom
                },
                fields=["name"],
                limit=1
            )

            if dato_existente:
                doc = frappe.get_doc(doctype, dato_existente[0]["name"])

                for campo, valor in dato_lista.items():
                    doc.set(campo, valor)

                print(f"Update --> {from_uom_sap} ---> {to_uom}")

                doc.flags.ignore_permissions = True
                doc.save()

                resultados.append("actualizado")

            else:
                doc_data = {
                    "doctype": doctype,
                    **dato_lista
                }

                print(f"Insert --> {from_uom_sap} ---> {to_uom}")

                doc = frappe.get_doc(doc_data)
                doc.flags.ignore_permissions = True
                doc.insert()

                resultados.append("creado")

        frappe.db.commit()

        return resultados, None

    except Exception as e:
        print(f"❌ Error procesando: {datos_sap.get('Code')}")
        print(e)
        return None, str(e)

