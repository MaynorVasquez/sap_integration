import frappe
from frappe import _
import requests
import json
import traceback  # Importación añadida
from collections import defaultdict


def construir_payload_sap(doc, mapeo):
    """
    Construye el payload para SAP desde un documento ERPNext, usando un mapeo con niveles head, DocumentLines y BatchNumbers.
    """
    payload = {
        "DocEntry": "0",
        "DocumentLines": []
    }

    # HEAD
    for campo_erp, campo_sap in mapeo["sap_fields"].get("head", {}).items():
        valor = doc.get(campo_erp)
        if valor is not None:
            payload[campo_sap] = valor

    # DETALLE
    for idx, item in enumerate(doc.get("items", [])):
        linea = {
            "LineNum": str(idx)  # Puede venir mapeado, pero por defecto se incluye
        }

        # Campos del detalle
        for campo_erp, campo_sap in mapeo["sap_fields"].get("DocumentLines", {}).items():
            valor = item.get(campo_erp)
            if valor is not None:
                linea[campo_sap] = valor

        # LOTES
        if mapeo["sap_fields"].get("BatchNumbers"):
            lotes = []
            batch_list = item.get("batches", [])

            # fallback si solo tiene batch_no y qty (estructura simple)
            if not batch_list and item.get("batch_no"):
                batch_list = [{
                    "BatchNumber": item.get("batch_no"),
                    "Quantity": item.get("qty"),
                    "ItemCode": item.get("item_code"),
                    "BaseLineNumber": str(idx)
                }]

            for lote in batch_list:
                lote_payload = {
                    "BaseLineNumber": str(idx)
                }
                for campo_erp, campo_sap in mapeo["sap_fields"]["BatchNumbers"].items():
                    valor = lote.get(campo_erp)
                    if valor is not None:
                        lote_payload[campo_sap] = valor
                if lote_payload:
                    lotes.append(lote_payload)

            if lotes:
                linea["BatchNumbers"] = lotes

        payload["DocumentLines"].append(linea)

    return payload
