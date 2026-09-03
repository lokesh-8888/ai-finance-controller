"""Financial domain schemas with strict integer-cents monetary precision."""

import datetime as dt
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class ScenarioType(str, Enum):
    """9-Scenario Taxonomy for financial reconciliation."""
    EXACT_MATCH = "EXACT_MATCH"
    FEE_DIFFERENCE = "FEE_DIFFERENCE"
    TAX_DIFFERENCE = "TAX_DIFFERENCE"
    REFUND = "REFUND"
    ADJUSTMENT = "ADJUSTMENT"
    TIMING_DIFFERENCE = "TIMING_DIFFERENCE"
    MISSING_SETTLEMENT = "MISSING_SETTLEMENT"
    DUPLICATE = "DUPLICATE"
    UNEXPLAINED_MISMATCH = "UNEXPLAINED_MISMATCH"


class RiskPriority(str, Enum):
    """Risk prioritization tiers for financial discrepancies."""
    P0_CRITICAL = "P0_CRITICAL"
    P1_HIGH = "P1_HIGH"
    P2_MEDIUM = "P2_MEDIUM"
    P4_NORMAL = "P4_NORMAL"


class BaseFinancialModel(BaseModel):
    """Base model enforcing strict types, serialization, and immutability."""
    model_config = ConfigDict(
        validate_assignment=True,
    )


class BankStatementLine(BaseFinancialModel):
    """Represents a single posted line item from a bank statement."""
    id: str = Field(..., description="Unique bank transaction identifier (e.g. BNK-001)")
    date: dt.date = Field(..., description="Date transaction posted to bank (YYYY-MM-DD)")
    amount_cents: StrictInt = Field(
        ...,
        description="Transaction amount in integer cents (+ for deposits/credits, - for debits/charges)"
    )
    raw_description: str = Field(..., description="Original memo/statement descriptor")
    reference_code: Optional[str] = Field(
        default=None,
        description="Wire, ACH, or check reference code if available"
    )
    account_id: str = Field(..., description="Bank account identifier (e.g. ACCT-OPERATING-01)")


class GatewayTransaction(BaseFinancialModel):
    """Represents a payment gateway (e.g. Stripe, Adyen) captured charge or payout."""
    id: str = Field(..., description="Unique gateway charge ID (e.g. ch_xxx or GTW-001)")
    order_id: str = Field(..., description="E-commerce or checkout order reference (e.g. ORD-1001)")
    gross_amount_cents: StrictInt = Field(..., description="Total charge amount charged to customer in cents")
    fee_cents: StrictInt = Field(default=0, description="Processing fee deducted by gateway in cents")
    tax_cents: StrictInt = Field(default=0, description="Sales tax collected or withheld in cents")
    net_amount_cents: StrictInt = Field(..., description="Net settlement amount (gross - fee - tax) in cents")
    payout_batch_id: Optional[str] = Field(default=None, description="Batch transfer identifier (e.g. po_xxx)")
    status: str = Field(default="succeeded", description="Transaction status (e.g. succeeded, refunded)")
    created_date: Optional[dt.date] = Field(default=None, description="Charge capture date")
    settled_date: Optional[dt.date] = Field(default=None, description="Estimated or confirmed payout settlement date")

    @model_validator(mode="after")
    def validate_net_equation(self) -> "GatewayTransaction":
        """Validate invariant: net_amount_cents == gross_amount_cents - fee_cents - tax_cents."""
        expected_net = self.gross_amount_cents - self.fee_cents - self.tax_cents
        if self.net_amount_cents != expected_net:
            raise ValueError(
                f"Gateway net amount invariant failed: "
                f"net_amount_cents ({self.net_amount_cents}) != "
                f"gross ({self.gross_amount_cents}) - fee ({self.fee_cents}) - tax ({self.tax_cents}) = {expected_net}"
            )
        return self


class ERPLedgerEntry(BaseFinancialModel):
    """Represents a journal entry or general ledger record in the ERP (NetSuite, SAP, etc.)."""
    id: str = Field(..., description="Unique GL entry identifier (e.g. GL-10001)")
    invoice_id: Optional[str] = Field(default=None, description="Associated invoice/order reference if any")
    gl_account_code: str = Field(..., description="Chart of accounts code (e.g. 1010-CASH, 4000-REV)")
    amount_cents: StrictInt = Field(..., description="Posted amount in integer cents (+ debit, - credit)")
    customer_vendor_name: str = Field(..., description="Associated counterparty/entity name")
    entry_date: dt.date = Field(..., description="Accounting period entry date (YYYY-MM-DD)")
    doc_type: str = Field(..., description="Document type (INVOICE, PAYMENT, JOURNAL_ENTRY, CREDIT_MEMO)")


class APInvoice(BaseFinancialModel):
    """Represents an Accounts Payable bill/invoice from a vendor."""
    id: str = Field(..., description="Vendor invoice number (e.g. INV-2026-001)")
    vendor_name: str = Field(..., description="Legal vendor entity name")
    amount_cents: StrictInt = Field(..., description="Total invoice liability amount in cents")
    due_date: dt.date = Field(..., description="Payment due date (YYYY-MM-DD)")
    currency: str = Field(default="USD", description="Billing currency code (ISO 4217)")
    fx_rate: float = Field(default=1.0, description="Foreign exchange conversion rate to base currency")
    status: str = Field(default="OPEN", description="Invoice payment status (OPEN, PAID, DISPUTED, VOID)")

    @field_validator("amount_cents")
    @classmethod
    def validate_positive_liability(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("APInvoice amount_cents must be a positive integer representing liability")
        return v


class GroundTruthRecord(BaseFinancialModel):
    """Evaluation record linking source entities with the verified ground-truth reconciliation outcome."""
    scenario_id: str = Field(..., description="Unique scenario benchmark key (e.g. SCEN-001)")
    scenario_type: ScenarioType = Field(..., description="Ground-truth category from 9-Scenario Taxonomy")
    risk_priority: RiskPriority = Field(..., description="Risk tier for triage")
    bank_line_id: Optional[str] = Field(default=None, description="Associated BankStatementLine ID(s)")
    gateway_tx_id: Optional[str] = Field(default=None, description="Associated GatewayTransaction ID(s)")
    erp_entry_id: Optional[str] = Field(default=None, description="Associated ERPLedgerEntry ID(s)")
    invoice_id: Optional[str] = Field(default=None, description="Associated APInvoice ID(s)")
    expected_status: str = Field(..., description="Expected engine outcome (e.g. MATCHED, EXPLAINED_VARIANCE)")
    variance_cents: StrictInt = Field(default=0, description="Amount variance in cents")
    explanation: str = Field(..., description="Human-auditable explanation of ground-truth variance")
