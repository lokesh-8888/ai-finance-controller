"""Pydantic schemas and domain DTOs for treasury cash positioning, forecasting, and waterfall bridges."""

import datetime as dt
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from src.ingestion.normalizer import cents_to_display


class ForecastHorizon(str, Enum):
    """Supported forecasting horizons."""
    HORIZON_7_DAY = "7_DAY"
    HORIZON_14_DAY = "14_DAY"
    HORIZON_30_DAY = "30_DAY"


class CashPosition(BaseModel):
    """Real-time multi-tier treasury cash position in integer cents."""
    model_config = ConfigDict(validate_assignment=True)

    as_of_date: dt.date = Field(..., description="Valuation snapshot date")
    settled_cash_cents: StrictInt = Field(..., description="Confirmed cleared bank cash balance")
    in_flight_gateway_cents: StrictInt = Field(..., ge=0, description="Captured gateway receivables awaiting T+2 settlement")
    unsettled_ar_cents: StrictInt = Field(..., ge=0, description="Open customer AR subledger invoices")
    committed_ap_cents: StrictInt = Field(..., ge=0, description="Approved AP invoices due for payment")
    adjusted_net_cash_cents: StrictInt = Field(
        ...,
        description="Settled cash + in-flight gateway - committed AP obligations"
    )

    @property
    def settled_cash_display(self) -> str:
        return cents_to_display(self.settled_cash_cents)

    @property
    def adjusted_net_cash_display(self) -> str:
        return cents_to_display(self.adjusted_net_cash_cents)

    @property
    def in_flight_gateway_display(self) -> str:
        return cents_to_display(self.in_flight_gateway_cents)

    @property
    def committed_ap_display(self) -> str:
        return cents_to_display(self.committed_ap_cents)


class DailyCashProjection(BaseModel):
    """Single-day cash trajectory projection with breakdown and invariant validation."""
    model_config = ConfigDict(validate_assignment=True)

    date: dt.date
    opening_balance_cents: StrictInt
    expected_inflows_cents: StrictInt = Field(..., ge=0)
    expected_outflows_cents: StrictInt = Field(..., ge=0)
    net_change_cents: StrictInt
    closing_balance_cents: StrictInt
    inflow_breakdown: Dict[str, int] = Field(default_factory=dict)
    outflow_breakdown: Dict[str, int] = Field(default_factory=dict)
    below_safety_threshold: bool = False

    @property
    def closing_balance_display(self) -> str:
        return cents_to_display(self.closing_balance_cents)


class MultiHorizonForecastReport(BaseModel):
    """Complete forward cash runway and burn-rate report across 7-day, 14-day, and 30-day horizons."""
    model_config = ConfigDict(validate_assignment=True)

    as_of_date: dt.date
    initial_position: CashPosition
    safety_threshold_cents: StrictInt = Field(..., ge=0)
    daily_projections: List[DailyCashProjection]
    horizon_summaries: Dict[str, Dict[str, Any]]
    daily_burn_rate_cents: StrictInt
    monthly_burn_rate_cents: StrictInt
    runway_months: Optional[float] = None
    lowest_trough_date: Optional[dt.date] = None
    lowest_trough_balance_cents: StrictInt
    trough_alert_triggered: bool = False


class WaterfallCategory(str, Enum):
    """Classification of liquidity movements in the cash-flow waterfall."""
    OPENING = "OPENING"
    GATEWAY_SETTLEMENT = "GATEWAY_SETTLEMENT"
    DIRECT_WIRE_INFLOW = "DIRECT_WIRE_INFLOW"
    AP_DISBURSEMENT = "AP_DISBURSEMENT"
    OPERATING_EXPENSE = "OPERATING_EXPENSE"
    REMEDIATED_VARIANCE = "REMEDIATED_VARIANCE"
    CLOSING = "CLOSING"


class WaterfallItem(BaseModel):
    """Individual line item in the liquidity waterfall bridge."""
    model_config = ConfigDict(validate_assignment=True)

    category: WaterfallCategory
    label: str
    amount_cents: StrictInt
    running_balance_cents: StrictInt

    @property
    def amount_display(self) -> str:
        return cents_to_display(self.amount_cents)

    @property
    def running_balance_display(self) -> str:
        return cents_to_display(self.running_balance_cents)


class WaterfallBridge(BaseModel):
    """Structured liquidity waterfall from opening settled cash to closing balance."""
    model_config = ConfigDict(validate_assignment=True)

    start_date: dt.date
    end_date: dt.date
    opening_balance_cents: StrictInt
    items: List[WaterfallItem]
    closing_balance_cents: StrictInt
    chart_payload: Dict[str, Any] = Field(default_factory=dict)
