import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sap_integration.api import (
    sap_auth,
    sap_facturas_erpnext,
    sap_notas_entregas_erpnext,
    sap_stock,
)
from sap_integration.utils import procesar_empresa_individual as company_processor
from sap_integration.utils.validate_expired_date import CustomSalesInvoice
from sap_integration.utils.sync_safety import (
    calculate_stock_shortfall,
    is_cancelled_source_document,
    is_cancellation_document,
)


class TestSyncSafety(unittest.TestCase):
    def test_stock_shortfall_uses_only_missing_quantity(self):
        self.assertEqual(calculate_stock_shortfall(10, 6), 4)

    def test_stock_shortfall_is_zero_when_stock_is_sufficient(self):
        self.assertEqual(calculate_stock_shortfall(5, 8), 0)

    def test_negative_available_stock_is_treated_as_zero(self):
        self.assertEqual(calculate_stock_shortfall(5, -2), 5)

    def test_cancellation_statuses_are_distinct(self):
        self.assertTrue(is_cancellation_document("csCancellation"))
        self.assertFalse(is_cancellation_document("csYes"))
        self.assertTrue(is_cancelled_source_document("csYes"))
        self.assertFalse(is_cancelled_source_document("csNo"))

    def test_stock_read_error_is_not_converted_to_zero(self):
        database = Mock()
        database.sql.side_effect = RuntimeError("database unavailable")

        with (
            patch.object(sap_stock.frappe, "db", database),
            patch.object(sap_stock.frappe, "log_error"),
            self.assertRaises(RuntimeError),
        ):
            sap_stock.get_stock_qty("ITEM-1", "WAREHOUSE-1", "BATCH-1")

    def test_failed_sap_login_closes_session(self):
        session = Mock()
        session.post.side_effect = sap_auth.requests.exceptions.Timeout("timeout")

        with (
            patch.object(
                sap_auth,
                "get_credentials",
                return_value=(
                    {"CompanyDB": "TEST", "UserName": "user", "Password": "secret"},
                    "https://sap.example",
                    "Login",
                ),
            ),
            patch.object(sap_auth.requests, "Session", return_value=session),
            patch.object(sap_auth.frappe, "conf", {}),
            patch.object(sap_auth.frappe, "throw", side_effect=RuntimeError("login failed")),
            self.assertRaises(RuntimeError),
        ):
            sap_auth.login_sap("TEST COMPANY")

        session.close.assert_called_once_with()

    def test_document_stock_receipts_do_not_commit_parent_transaction(self):
        for module in (sap_facturas_erpnext, sap_notas_entregas_erpnext):
            with self.subTest(module=module.__name__):
                stock_entry = Mock()
                stock_entry.name = "STE-TEST"
                database = Mock()

                with (
                    patch.object(module.frappe, "new_doc", return_value=stock_entry),
                    patch.object(module.frappe, "db", database),
                    patch("builtins.print"),
                ):
                    result = module.crear_stock_entry_entrada(
                        "ITEM-1", 2, "BATCH-1", "WAREHOUSE-1"
                    )

                self.assertEqual(result, "STE-TEST")
                database.commit.assert_not_called()
                stock_entry.insert.assert_called_once_with(ignore_permissions=True)
                stock_entry.submit.assert_called_once_with()

    def test_stock_entry_helper_leaves_commit_to_full_reconciliation(self):
        stock_entry = Mock()
        stock_entry.name = "STE-STOCK-TEST"
        stock_entry.items = [Mock()]
        database = Mock()

        with (
            patch.object(sap_stock.frappe, "new_doc", return_value=stock_entry),
            patch.object(sap_stock.frappe, "get_value", return_value=True),
            patch.object(sap_stock.frappe, "db", database),
            patch("builtins.print"),
        ):
            sap_stock.crear_stock_entry_multiple(
                [
                    {
                        "item_code": "ITEM-1",
                        "qty": 2,
                        "batch_no": "BATCH-1",
                        "warehouse": "WAREHOUSE-1",
                        "valuation_rate": 1,
                    }
                ],
                tipo="In",
            )

        database.commit.assert_not_called()
        stock_entry.insert.assert_called_once_with(ignore_permissions=True)
        stock_entry.submit.assert_called_once_with()

    def test_due_date_override_keeps_standard_validation_for_manual_invoice(self):
        invoice = object.__new__(CustomSalesInvoice)
        invoice.flags = {}
        invoice.name = "SINV-TEST"
        invoice.posting_date = "2026-10-30"
        invoice.due_date = "2026-10-29"

        with patch(
            "erpnext.controllers.accounts_controller.AccountsController.validate_due_date",
            return_value="standard-validation",
        ) as standard_validation:
            result = invoice.validate_due_date()

        self.assertEqual(result, "standard-validation")
        standard_validation.assert_called_once_with()

    def test_due_date_override_is_scoped_to_flagged_sap_invoice(self):
        invoice = object.__new__(CustomSalesInvoice)
        invoice.flags = {"sap_sales_invoice": True}
        invoice.name = "SINV-SAP-TEST"
        invoice.posting_date = "2026-10-30"
        invoice.due_date = "2026-10-29"

        with (
            patch(
                "erpnext.controllers.accounts_controller.AccountsController.validate_due_date"
            ) as standard_validation,
            patch("sap_integration.utils.validate_expired_date.frappe.logger", return_value=Mock()),
        ):
            result = invoice.validate_due_date()

        self.assertIsNone(result)
        standard_validation.assert_not_called()

    def test_incomplete_processing_does_not_advance_delta(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {"value": [{"DocNum": 1}]}
        session.get.return_value = response
        database = Mock()
        database.get_value.return_value = SimpleNamespace(
            date_time="2026-10-29 00:00:00",
            name="DELTA-ROW-1",
        )
        company = SimpleNamespace(company="TEST COMPANY", endpoint="Orders")

        with (
            patch.object(company_processor.frappe, "db", database),
            patch.object(company_processor.frappe, "conf", {}),
            patch.object(company_processor.frappe, "log_error"),
            patch("builtins.print"),
            patch.object(
                company_processor,
                "now_datetime",
                return_value=datetime(2026, 10, 30, 12, 0, 0),
            ),
            patch.object(company_processor, "login_sap", return_value=session),
            patch.object(
                company_processor,
                "mapping_blueprint1",
                return_value={"sap_fields": {"head": {}}, "url": "Orders"},
            ),
            patch.object(company_processor, "construir_url_sap", return_value="https://sap/Orders"),
            patch.object(company_processor, "construir_filtro_tiempo", return_value=None),
            patch.object(company_processor, "log_sincronizacion"),
        ):
            result = company_processor.procesar_empresa_individual(
                config=object(),
                empresa=company,
                docname=None,
                procesar_datos=lambda *_args: {
                    "processed": 0,
                    "failed": 1,
                    "complete": False,
                },
                doctype_logs="Sync Log",
                doctype_target="Sales Order",
                doctype_mapeo="Mapping",
                key_sap="DocNum",
                key_erpnext="custom_docnum",
                usa_paginacion=False,
            )

        self.assertEqual(result["status"], "error")
        database.set_value.assert_not_called()
        session.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
