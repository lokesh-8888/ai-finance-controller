"""Liquidity waterfall bridge builder and Chart.js / Recharts visualization data exporter."""

import datetime as dt
from typing import Any, Dict, List

from src.forecasting.schemas import (
    DailyCashProjection,
    WaterfallBridge,
    WaterfallCategory,
    WaterfallItem,
)
from src.ingestion.normalizer import cents_to_display


class CashFlowWaterfallEngine:
    """Constructs structured liquidity waterfall representations and chart-ready payloads."""

    @classmethod
    def build_bridge(
        cls,
        start_date: dt.date,
        end_date: dt.date,
        opening_balance_cents: int,
        gateway_settlements_cents: int = 0,
        direct_wires_cents: int = 0,
        ap_disbursements_cents: int = 0,
        operating_expenses_cents: int = 0,
        remediated_variances_cents: int = 0,
    ) -> WaterfallBridge:
        """Construct a balanced liquidity waterfall from opening cash to closing balance."""
        items: List[WaterfallItem] = []
        running_balance = opening_balance_cents

        # 1. Opening Cash
        items.append(
            WaterfallItem(
                category=WaterfallCategory.OPENING,
                label="Opening Settled Cash",
                amount_cents=opening_balance_cents,
                running_balance_cents=running_balance,
            )
        )

        # 2. Gateway Settlements (+)
        if gateway_settlements_cents != 0:
            running_balance += gateway_settlements_cents
            items.append(
                WaterfallItem(
                    category=WaterfallCategory.GATEWAY_SETTLEMENT,
                    label="Gateway Card Settlements",
                    amount_cents=gateway_settlements_cents,
                    running_balance_cents=running_balance,
                )
            )

        # 3. Direct Wires (+)
        if direct_wires_cents != 0:
            running_balance += direct_wires_cents
            items.append(
                WaterfallItem(
                    category=WaterfallCategory.DIRECT_WIRE_INFLOW,
                    label="Direct Inward Wires",
                    amount_cents=direct_wires_cents,
                    running_balance_cents=running_balance,
                )
            )

        # 4. AP Vendor Disbursements (-)
        if ap_disbursements_cents != 0:
            amt = -abs(ap_disbursements_cents)
            running_balance += amt
            items.append(
                WaterfallItem(
                    category=WaterfallCategory.AP_DISBURSEMENT,
                    label="AP Vendor Disbursements",
                    amount_cents=amt,
                    running_balance_cents=running_balance,
                )
            )

        # 5. Operating Expenses (-)
        if operating_expenses_cents != 0:
            amt = -abs(operating_expenses_cents)
            running_balance += amt
            items.append(
                WaterfallItem(
                    category=WaterfallCategory.OPERATING_EXPENSE,
                    label="Operating Expenses & Payroll",
                    amount_cents=amt,
                    running_balance_cents=running_balance,
                )
            )

        # 6. Remediated Exceptions (+/-)
        if remediated_variances_cents != 0:
            running_balance += remediated_variances_cents
            items.append(
                WaterfallItem(
                    category=WaterfallCategory.REMEDIATED_VARIANCE,
                    label="Remediated Variances & Adjustments",
                    amount_cents=remediated_variances_cents,
                    running_balance_cents=running_balance,
                )
            )

        # 7. Closing Cash Balance
        items.append(
            WaterfallItem(
                category=WaterfallCategory.CLOSING,
                label="Closing Cash Balance",
                amount_cents=running_balance,
                running_balance_cents=running_balance,
            )
        )

        # Generate Chart.js / Recharts payload
        chart_payload = {
            "labels": [item.label for item in items],
            "categories": [item.category.value for item in items],
            "amounts_cents": [item.amount_cents for item in items],
            "running_balances_cents": [item.running_balance_cents for item in items],
            "display_amounts": [item.amount_display for item in items],
            "step_types": [
                "total" if item.category in [WaterfallCategory.OPENING, WaterfallCategory.CLOSING]
                else "increase" if item.amount_cents > 0
                else "decrease"
                for item in items
            ],
        }

        return WaterfallBridge(
            start_date=start_date,
            end_date=end_date,
            opening_balance_cents=opening_balance_cents,
            items=items,
            closing_balance_cents=running_balance,
            chart_payload=chart_payload,
        )

    @classmethod
    def build_trajectory_payload(
        cls,
        projections: List[DailyCashProjection],
    ) -> Dict[str, Any]:
        """Export daily forecast trajectory for timeseries charting."""
        return {
            "dates": [p.date.isoformat() for p in projections],
            "opening_balances_cents": [p.opening_balance_cents for p in projections],
            "closing_balances_cents": [p.closing_balance_cents for p in projections],
            "inflows_cents": [p.expected_inflows_cents for p in projections],
            "outflows_cents": [p.expected_outflows_cents for p in projections],
            "net_changes_cents": [p.net_change_cents for p in projections],
            "below_safety_flags": [p.below_safety_threshold for p in projections],
            "closing_displays": [p.closing_balance_display for p in projections],
        }
