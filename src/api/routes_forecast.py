"""Real-time cash position, forward runway forecasting, and waterfall bridge endpoints."""

import datetime as dt
from typing import Any, Dict
from fastapi import APIRouter

from src.forecasting.cash_position import CashPositionCalculator
from src.forecasting.forecaster import MultiHorizonCashForecaster
from src.forecasting.waterfall import CashFlowWaterfallEngine

router = APIRouter(prefix="/api/v1/forecast", tags=["Cash & Forecasting"])


@router.get("/position")
def get_cash_position() -> Dict[str, Any]:
    """Retrieve real-time multi-tier treasury cash position."""
    as_of = dt.date(2026, 8, 31)
    pos = CashPositionCalculator.compute_position(
        as_of_date=as_of,
        opening_cash_cents=25_000_000,  # $250,000.00
    )
    return pos.model_dump()


@router.get("/projections")
def get_forward_projections() -> Dict[str, Any]:
    """Retrieve forward cash projections across 7-day, 14-day, and 30-day horizons."""
    as_of = dt.date(2026, 8, 31)
    pos = CashPositionCalculator.compute_position(as_of_date=as_of, opening_cash_cents=25_000_000)

    report = MultiHorizonCashForecaster.forecast(
        as_of_date=as_of,
        initial_position=pos,
        daily_recurring_inflow_cents=250_000,  # +$2,500/day
        scheduled_outflows=[
            (as_of + dt.timedelta(days=5), 800_000, "AWS & Cloud Infrastructure"),
            (as_of + dt.timedelta(days=15), 3_500_000, "Bi-Weekly Engineering Payroll"),
            (as_of + dt.timedelta(days=25), 1_200_000, "Commercial Lease"),
        ],
        safety_threshold_cents=5_000_000,  # $50,000.00
        horizon_days=30,
    )
    return report.model_dump()


@router.get("/waterfall")
def get_waterfall_bridge() -> Dict[str, Any]:
    """Retrieve liquidity waterfall bridge connecting opening cash to closing balance."""
    bridge = CashFlowWaterfallEngine.build_bridge(
        start_date=dt.date(2026, 8, 1),
        end_date=dt.date(2026, 8, 31),
        opening_balance_cents=20_000_000,  # $200,000.00
        gateway_settlements_cents=8_500_000,  # +$85,000.00
        direct_wires_cents=3_200_000,  # +$32,000.00
        ap_disbursements_cents=4_500_000,  # -$45,000.00
        operating_expenses_cents=2_324_550,  # -$23,245.50
        remediated_variances_cents=0,
    )
    return bridge.model_dump()


@router.get("/trajectory")
def get_chart_trajectory() -> Dict[str, Any]:
    """Retrieve time-series daily projection trajectory for Chart.js / Recharts."""
    as_of = dt.date(2026, 8, 31)
    pos = CashPositionCalculator.compute_position(as_of_date=as_of, opening_cash_cents=25_000_000)
    report = MultiHorizonCashForecaster.forecast(
        as_of_date=as_of,
        initial_position=pos,
        daily_recurring_inflow_cents=250_000,
        horizon_days=30,
    )
    return CashFlowWaterfallEngine.build_trajectory_payload(report.daily_projections)
