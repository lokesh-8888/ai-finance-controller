"""Multi-source financial data ingestion, token normalizer, and integer-cents converters."""

import csv
import json
import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.domain.models import (
    BankStatementLine,
    GatewayTransaction,
    ERPLedgerEntry,
    APInvoice,
)

# Known enterprise vendor alias registry for normalization
VENDOR_ALIASES: Dict[str, str] = {
    "AWS": "AMAZON WEB SERVICES",
    "AMZN": "AMAZON WEB SERVICES",
    "AMAZON": "AMAZON WEB SERVICES",
    "AWS CLOUD DUBLIN": "AMAZON WEB SERVICES",
    "AWS EMEA SARL": "AMAZON WEB SERVICES",
    "AMAZON WEB SERVICES INC": "AMAZON WEB SERVICES",
    "AMAZON WEB SERVICES INC.": "AMAZON WEB SERVICES",
    "STRIPE PAYMENTS": "STRIPE",
    "STRIPE INC": "STRIPE",
    "STRIPE PAYOUT": "STRIPE",
    "STRIPE TRANSFER": "STRIPE",
    "GOOGLE CLOUD": "GOOGLE CLOUD PLATFORM",
    "GOOGLE IRELAND": "GOOGLE CLOUD PLATFORM",
    "GOOG CLOUD": "GOOGLE CLOUD PLATFORM",
    "GCP": "GOOGLE CLOUD PLATFORM",
    "MICROSOFT AZURE": "MICROSOFT AZURE",
    "MSFT AZURE": "MICROSOFT AZURE",
    "MSFT IRELAND": "MICROSOFT AZURE",
    "MICROSOFT CORP": "MICROSOFT CORP",
    "DATADOG INC": "DATADOG",
    "DATADOG US": "DATADOG",
    "SNOWFLAKE COMPUTING": "SNOWFLAKE",
    "SNOWFLAKE INC": "SNOWFLAKE",
}


def to_cents(value: Any, from_dollars: bool = True) -> int:
    """Safely convert any currency representation (string, float, int, Decimal) to integer cents.

    Guarantees ZERO floating-point rounding drift by utilizing exact Decimal quantization.

    Args:
        value: Input amount (e.g. "$1,250.50", "($45.20)", -25.50, Decimal("100.00"), 10000).
        from_dollars: If True, treats numbers with decimals as dollars (e.g. 10.50 -> 1050).
                      If False, treats input already as integer cents.

    Returns:
        int: Total value in exact integer cents.

    Raises:
        ValueError: If value cannot be parsed or represents an invalid monetary format.
    """
    if value is None:
        raise ValueError("Cannot convert None to cents")

    # If already an int and not converting from dollars, return as-is
    if isinstance(value, int) and not from_dollars:
        return value

    # If already an int and from_dollars is True, convert whole dollar int to cents
    if isinstance(value, int) and from_dollars:
        return value * 100

    # Clean string representation
    val_str = str(value).strip()
    if not val_str:
        raise ValueError("Empty string cannot be converted to cents")

    # Check for accounting parentheses notation: (123.45) -> -123.45
    is_negative = False
    if val_str.startswith("(") and val_str.endswith(")"):
        is_negative = True
        val_str = val_str[1:-1].strip()

    # Remove currency symbols, commas, and whitespace
    clean_str = re.sub(r"[$\u20ac\u00a3\u00a5,\s]", "", val_str)

    if clean_str.startswith("-"):
        is_negative = True
        clean_str = clean_str[1:].strip()
    elif clean_str.startswith("+"):
        clean_str = clean_str[1:].strip()

    if "-" in clean_str or "+" in clean_str:
        raise ValueError(f"Invalid monetary numeric string with multiple signs: '{value}'")

    if not clean_str:
        raise ValueError(f"Unparsable monetary string: '{value}'")

    try:
        dec = Decimal(clean_str)
    except InvalidOperation as e:
        raise ValueError(f"Invalid monetary numeric string: '{value}'") from e

    if from_dollars:
        # Quantize to 2 decimal places using standard financial round-half-up
        cents_dec = (dec * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        result = int(cents_dec)
    else:
        result = int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    return -result if is_negative else result


def cents_to_display(cents: int, currency_symbol: str = "$") -> str:
    """Format integer cents into standard financial display format (e.g. $1,250.50)."""
    is_neg = cents < 0
    abs_cents = abs(cents)
    dollars = abs_cents // 100
    remainder = abs_cents % 100
    formatted = f"{currency_symbol}{dollars:,}.{remainder:02d}"
    return f"-{formatted}" if is_neg else formatted


def normalize_text(text: Optional[str]) -> str:
    """Sanitize and normalize textual descriptors.

    - Strips surrounding whitespace
    - Replaces non-alphanumeric separators with spaces
    - Collapses repeated spaces
    - Converts to UPPERCASE
    - Resolves common vendor aliases
    """
    if not text:
        return ""

    # Replace special separator characters with space
    cleaned = re.sub(r"[\t\r\n_\-\*#/\\|]+", " ", str(text))
    # Remove leading/trailing non-alphanumeric punctuation except common business characters
    cleaned = re.sub(r"[^\w\s\.\,\&]", "", cleaned)
    # Collapse multiple whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip().upper()

    return resolve_vendor_alias(cleaned)


def resolve_vendor_alias(normalized_name: str) -> str:
    """Resolve known vendor variations to canonical corporate names."""
    if normalized_name in VENDOR_ALIASES:
        return VENDOR_ALIASES[normalized_name]

    # Check for prefix / partial matches in aliases
    for alias_key, canonical in VENDOR_ALIASES.items():
        if normalized_name.startswith(alias_key + " ") or normalized_name.endswith(" " + alias_key):
            return canonical

    return normalized_name


def normalize_date(date_val: Any) -> date:
    """Parse various date formats into a standard datetime.date object.

    Supports:
    - date / datetime objects
    - ISO 8601 strings (YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS)
    - US format (MM/DD/YYYY, M/D/YYYY)
    - European format (DD/MM/YYYY, DD-MM-YYYY)
    """
    if isinstance(date_val, datetime):
        return date_val.date()
    if isinstance(date_val, date):
        return date_val

    raw_str = str(date_val).strip()
    if not raw_str:
        raise ValueError("Cannot normalize empty date string")

    # If ISO string with time component
    if "T" in raw_str:
        raw_str = raw_str.split("T")[0]

    # Attempt fast ISO parse
    try:
        return date.fromisoformat(raw_str)
    except ValueError:
        pass

    # Common financial statement date formats
    candidate_formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ]

    for fmt in candidate_formats:
        try:
            return datetime.strptime(raw_str, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Unrecognized date format: '{date_val}'")


def parse_bank_statement_line(row: Dict[str, Any]) -> BankStatementLine:
    """Normalize and construct BankStatementLine from a raw data dict."""
    amount_raw = row.get("amount_cents")
    if amount_raw is None:
        amount_raw = row.get("amount")
        amount_cents = to_cents(amount_raw, from_dollars=True)
    else:
        amount_cents = int(amount_raw)

    return BankStatementLine(
        id=str(row["id"]).strip(),
        date=normalize_date(row["date"]),
        amount_cents=amount_cents,
        raw_description=str(row.get("raw_description", "")).strip(),
        reference_code=str(row["reference_code"]).strip() if row.get("reference_code") else None,
        account_id=str(row.get("account_id", "OPERATING-01")).strip(),
    )


def parse_gateway_transaction(row: Dict[str, Any]) -> GatewayTransaction:
    """Normalize and construct GatewayTransaction from a raw data dict."""
    # Check if inputs are given in cents or dollars
    if "gross_amount_cents" in row:
        gross_cents = int(row["gross_amount_cents"])
        fee_cents = int(row.get("fee_cents", 0))
        tax_cents = int(row.get("tax_cents", 0))
        net_cents = int(row.get("net_amount_cents", gross_cents - fee_cents - tax_cents))
    else:
        gross_cents = to_cents(row["gross_amount"])
        fee_cents = to_cents(row.get("fee", 0))
        tax_cents = to_cents(row.get("tax", 0))
        net_cents = to_cents(row.get("net_amount", gross_cents - fee_cents - tax_cents), from_dollars=False)

    return GatewayTransaction(
        id=str(row["id"]).strip(),
        order_id=str(row["order_id"]).strip(),
        gross_amount_cents=gross_cents,
        fee_cents=fee_cents,
        tax_cents=tax_cents,
        net_amount_cents=net_cents,
        payout_batch_id=str(row["payout_batch_id"]).strip() if row.get("payout_batch_id") else None,
        status=str(row.get("status", "succeeded")).strip().lower(),
    )


def parse_erp_ledger_entry(row: Dict[str, Any]) -> ERPLedgerEntry:
    """Normalize and construct ERPLedgerEntry from a raw data dict."""
    amount_raw = row.get("amount_cents")
    if amount_raw is None:
        amount_raw = row.get("amount")
        amount_cents = to_cents(amount_raw, from_dollars=True)
    else:
        amount_cents = int(amount_raw)

    return ERPLedgerEntry(
        id=str(row["id"]).strip(),
        invoice_id=str(row["invoice_id"]).strip() if row.get("invoice_id") else None,
        gl_account_code=str(row["gl_account_code"]).strip(),
        amount_cents=amount_cents,
        customer_vendor_name=normalize_text(row.get("customer_vendor_name", "")),
        entry_date=normalize_date(row.get("entry_date", row.get("date"))),
        doc_type=str(row.get("doc_type", "INVOICE")).strip().upper(),
    )


def parse_ap_invoice(row: Dict[str, Any]) -> APInvoice:
    """Normalize and construct APInvoice from a raw data dict."""
    amount_raw = row.get("amount_cents")
    if amount_raw is None:
        amount_raw = row.get("amount")
        amount_cents = to_cents(amount_raw, from_dollars=True)
    else:
        amount_cents = int(amount_raw)

    return APInvoice(
        id=str(row["id"]).strip(),
        vendor_name=normalize_text(row.get("vendor_name", "")),
        amount_cents=amount_cents,
        due_date=normalize_date(row.get("due_date")),
        currency=str(row.get("currency", "USD")).strip().upper(),
        fx_rate=float(row.get("fx_rate", 1.0)),
        status=str(row.get("status", "OPEN")).strip().upper(),
    )


def load_csv_as_dicts(file_path: Union[str, Path]) -> List[Dict[str, Any]]:
    """Read a CSV file and return a list of row dicts."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with open(path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_json_as_dicts(file_path: Union[str, Path]) -> List[Dict[str, Any]]:
    """Read a JSON file and return a list of dicts."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with open(path, mode="r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return [data]
        raise ValueError(f"Unexpected JSON root structure in {path}")
