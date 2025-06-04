import frappe
from frappe import _
import requests
import json
import traceback  # Importación añadida
from .sap_auth import login_sap 
from .logs import log_sincronizacion

def sincronizar_factores_conversion(docname=None):
    debug_messages = []
    total_procesados = 0
    session = None
    detalles = []
    doctype_logs = "Sincronizacion UOM"

    try:
        debug_messages.append("Iniciando autenticación con SAP...")
        session = login_sap()

        if not session or not isinstance(session, requests.Session):
            raise Exception("La sesión SAP no se creó correctamente")
        debug_messages.append("✔ Autenticación exitosa")

        base_url = "https://apisap.yaesta.com.gt/b1s/v1/UnitOfMeasurementGroups"
        debug_messages.append(f"✔ Consultando SAP: {base_url}")
        response = session.get(base_url, timeout=30)
        response.raise_for_status()
        data = response.json()

        grupos = data.get('value', [])
        if not grupos:
            debug_messages.append("✗ No se recibieron grupos de UOM desde SAP.")
        else:
            debug_messages.append(f"✔ {len(grupos)} grupos de UOM obtenidos")

            for grupo in grupos:
                categoria_id = grupo.get("AbsEntry")
                categoria = frappe.get_value("UOM Category", {"custom_absentry": categoria_id}, "name")
                if not categoria:
                    debug_messages.append(f"✗ Categoría ID {categoria_id} no encontrada en ERPNext")
                    continue

                base_uom_code = grupo.get("BaseUoM")
                if base_uom_code == -1:
                    continue

                base_uom = frappe.get_value("UOM", {"custom_absentry": base_uom_code}, "name")
                if not base_uom:
                    debug_messages.append(f"✗ Base UOM ID {base_uom_code} no encontrado en ERPNext")
                    continue

                for definicion in grupo.get("UoMGroupDefinitionCollection", []):
                    if definicion.get("AlternateUoM") == -1 or definicion.get("Active") != "tYES":
                        continue

                    alt_uom_code = definicion.get("AlternateUoM")
                    alt_uom = frappe.get_value("UOM", {"custom_absentry": alt_uom_code}, "name")
                    if not alt_uom:
                        debug_messages.append(f"✗ UOM alternativo ID {alt_uom_code} no encontrado en ERPNext")
                        continue

                    factor = definicion.get("BaseQuantity", 1)
                    if factor == 0:
                        debug_messages.append(f"✗ Factor no válido (0) para {alt_uom} ➜ {base_uom}")
                        continue

                    try:
                        conversion = frappe.get_all("UOM Conversion Factor", filters={
                            "category": categoria,
                            "from_uom": alt_uom,
                            "to_uom": base_uom
                        })

                        if conversion:
                            doc = frappe.get_doc("UOM Conversion Factor", conversion[0].name)
                            doc.conversion_factor = factor
                            doc.value = factor
                            doc.save(ignore_permissions=True)
                            debug_messages.append(f"✓ Factor actualizado: {alt_uom} ➜ {base_uom} ({factor})")
                        else:
                            doc = frappe.get_doc({
                                "doctype": "UOM Conversion Factor",
                                "category": categoria,
                                "from_uom": alt_uom,
                                "to_uom": base_uom,
                                "conversion_factor": factor,
                                "value": factor
                            })
                            doc.insert(ignore_permissions=True)
                            debug_messages.append(f"✓ Factor creado: {alt_uom} ➜ {base_uom} ({factor})")

                        total_procesados += 1
                        detalles.append({
                            "from": alt_uom,
                            "to": base_uom,
                            "factor": factor
                        })

                    except Exception as ex:
                        frappe.log_error(f"Error al insertar factor:\n{frappe.as_json(doc)}", "Error en UOM Conversion Factor")
                        debug_messages.append(f"✗ Error al crear factor: {alt_uom} ➜ {base_uom}: {str(ex)}")

            frappe.db.commit()

    except Exception as e:
        error_msg = f"Error durante sincronización: {str(e)}\n{traceback.format_exc()}"
        debug_messages.append(f"✗ {error_msg}")
        frappe.log_error(title="Error al sincronizar factores UOM desde SAP", message=error_msg)

        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Error",
                total=total_procesados,
                detalles={},
                errores=error_msg
            )

        return {
            "status": "error",
            "message": "Ocurrió un error durante la sincronización",
            "debug": debug_messages,
            "total": total_procesados
        }

    finally:
        if session and isinstance(session, requests.Session):
            session.close()
            debug_messages.append("✓ Sesión SAP cerrada correctamente")

        if docname:
            log_sincronizacion(
                doctype=doctype_logs,
                docname=docname,
                status="Exitoso" if total_procesados > 0 else "Sin cambios",
                total=total_procesados,
                detalles=detalles,
                errores=""
            )

    return {
        "status": "success" if total_procesados > 0 else "warning",
        "total": total_procesados,
        "debug": debug_messages
    }
