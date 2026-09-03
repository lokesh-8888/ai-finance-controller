"""Multi-horizon forward cash runway, burn-rate, and liquidity forecaster."""

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

from src.domain.models import APInvoice, GatewayTransaction
from src.forecasting.schemas import (
    CashPosition,
    DailyCashProjection,
    ForecastHorizon,
    MultiHorizonForecastReport,
)


class MultiHorizonCashForecaster:
    """Projects daily roll-forward treasury cash balances across 7-day, 14-day, and 30-day horizons."""

    GATEWAY_SETTLEMENT_LAG_DAYS = 2  # Standard T+2 settlement lag

    @classmethod
    def forecast(
        cls,
        as_of_date: dt.date,
        initial_position: CashPosition,
        gateway_pipeline: Optional[List[GatewayTransaction]] = None,
        ap_pipeline: Optional[List[APInvoice]] = None,
        daily_recurring_inflow_cents: int = 0,
        scheduled_outflows: Optional[List[Tuple[dt.date, int, str]]] = None,
        safety_threshold_cents: int = 5_000_000,  # $50,000.00
        horizon_days: int = 30,
    ) -> MultiHorizonForecastReport:
        """Construct multi-horizon roll-forward cash projections and runway analysis."""
        gateway_pipeline = gateway_pipeline or []
        ap_pipeline = ap_pipeline or []
        scheduled_outflows = scheduled_outflows or []

        daily_projections: List[DailyCashProjection] = []
        current_opening = initial_position.settled_cash_cents

        for day_offset in range(1, horizon_days + 1):
            curr_date = as_of_date + dt.timedelta(days=day_offset)
            inflow_map: Dict[str, int] = {}
            outflow_map: Dict[str, int] = {}

            # 1. Gateway Payout Inflows (T+2 settlement simulation)
            gateway_landing = 0
            for g in gateway_pipeline:
                g_created = getattr(g, "created_date", None)
                g_settled = getattr(g, "settled_date", None)
                if g_created is not None:
                    settlement_date = g_settled or (g_created + dt.timedelta(days=cls.GATEWAY_SETTLEMENT_LAG_DAYS))
                    if settlement_date == curr_date and g.status == "succeeded":
                        gateway_landing += g.net_amount_cents

            if gateway_landing > 0:
                inflow_map["Gateway T+2 Settlements"] = gateway_landing

            # 2. Baseline Recurring Inflows (Daily card processing / subscriptions)
            if daily_recurring_inflow_cents > 0:
                inflow_map["Recurring Customer Inflows"] = daily_recurring_inflow_cents

            # 3. AP Commitments Landing on Due Date
            ap_disbursements = 0
            for inv in ap_pipeline:
                if inv.due_date == curr_date:
                    ap_disbursements += inv.amount_cents

            if ap_disbursements > 0:
                outflow_map["AP Vendor Disbursements"] = ap_disbursements

            # 4. Scheduled Specific Outflows (Payroll, tax withholding, rent)
            for out_date, amt_cents, label in scheduled_outflows:
                if out_date == curr_date:
                    outflow_map[label] = outflow_map.get(label, 0) + amt_cents

            total_inflows = sum(inflow_map.values())
            total_outflows = sum(outflow_map.values())
            net_change = total_inflows - total_outflows
            closing_balance = current_opening + net_change
            below_safety = closing_balance < safety_threshold_cents

            daily_projections.append(
                DailyCashProjection(
                    date=curr_date,
                    opening_balance_cents=current_opening,
                    expected_inflows_cents=total_inflows,
                    expected_outflows_cents=total_outflows,
                    net_change_cents=net_change,
                    closing_balance_cents=closing_balance,
                    inflow_breakdown=inflow_map,
                    outflow_breakdown=outflow_map,
                    below_safety_threshold=below_safety,
                )
            )

            # Roll forward
            current_opening = closing_balance

        # Horizon Summaries
        def get_horizon_summary(days: int) -> Dict[str, Any]:
            slice_proj = daily_projections[:days]
            tot_in = sum(p.expected_inflows_cents for p in slice_proj)
            tot_out = sum(p.expected_outflows_cents for p in slice_proj)
            end_bal = slice_proj[-1].closing_balance_cents if slice_proj else initial_position.settled_cash_cents
            return {
                "horizon_days": days,
                "closing_date": slice_proj[-1].date.isoformat() if slice_proj else as_of_date.isoformat(),
                "total_inflows_cents": tot_in,
                "total_outflows_cents": tot_out,
                "net_change_cents": tot_in - tot_out,
                "closing_cash_cents": end_bal,
            }

        horizon_summaries = {
            ForecastHorizon.HORIZON_7_DAY.value: get_horizon_summary(min(7, len(daily_projections))),
            ForecastHorizon.HORIZON_14_DAY.value: get_horizon_summary(min(14, len(daily_projections))),
            ForecastHorizon.HORIZON_30_DAY.value: get_horizon_summary(min(30, len(daily_projections))),
        }

        # Burn-rate & Runway Calculations
        total_30d_inflows = sum(p.expected_inflows_cents for p in daily_projections)
        total_30d_outflows = sum(p.expected_outflows_cents for p in daily_projections)
        net_30d_change = total_30d_inflows - total_30d_outflows

        if net_30d_change < 0:
            # Company is burning net cash
            monthly_burn_rate_cents = abs(net_30d_change)
            daily_burn_rate_cents = monthly_burn_rate_cents // horizon_days
            runway_months = (
                round(initial_position.adjusted_net_cash_cents / monthly_burn_rate_cents, 2)
                if monthly_burn_rate_cents > 0 else None
            )
        else:
            # Cash flow positive
            monthly_burn_rate_cents = 0
            daily_burn_rate_cents = 0
            runway_months = None

        # Lowest Trough & Buffer Alert
        lowest_trough_balance = min(p.closing_balance_cents for p in daily_projections)
        lowest_trough_date = next(
            p.date for p in daily_projections if p.closing_balance_cents == lowest_trough_balance
        )
        trough_alert = lowest_trough_balance < safety_threshold_cents

        return MultiHorizonForecastReport(
            as_of_date=as_of_date,
            initial_position=initial_position,
            safety_threshold_cents=safety_threshold_cents,
            daily_projections=daily_projections,
            horizon_summaries=horizon_summaries,
            daily_burn_rate_cents=daily_burn_rate_cents,
            monthly_burn_rate_cents=monthly_burn_rate_cents,
            runway_months=runway_months,
            lowest_trough_date=lowest_trough_date,
            lowest_trough_balance_cents=lowest_trough_balance,
            trough_alert_triggered=trough_alert,
        )
