"""Small, side-effect-free guards shared by SAP synchronization flows."""


SAP_CANCELLATION_STATUS = "csCancellation"
SAP_CANCELLED_STATUS = "csYes"


def calculate_stock_shortfall(requested_qty, available_qty):
    """Return only the quantity missing to satisfy an outgoing movement."""
    requested = float(requested_qty or 0)
    available = max(float(available_qty or 0), 0.0)
    return max(requested - available, 0.0)


def is_cancellation_document(cancel_status):
    return cancel_status == SAP_CANCELLATION_STATUS


def is_cancelled_source_document(cancel_status):
    return cancel_status == SAP_CANCELLED_STATUS
