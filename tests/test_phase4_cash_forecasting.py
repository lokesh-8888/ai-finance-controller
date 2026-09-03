"""Unit, financial invariant, and multi-horizon forecasting tests for Phase 4."""

import datetime as dt
import pytest

from src.domain.models import APInvoice, BankStatementLine, GatewayTransaction
from src.forecasting.cash_position import CashPositionCalculator
from src.forecasting.forecaster import MultiHorizonCashForecaster
from src.forecasting.schemas import (
    CashPosition,
    ForecastHorizon,
    WaterfallCategory,
)
from src.forecasting.waterfall import CashFlowWaterfallEngine


class TestRealTimeCashPositionCalculator:
    """Validate multi-tier corporate liquidity calculations and integer-cents accuracy."""

    def test_cash_position_tier_calculations(self):
        """Validates Settled Cash, In-Flight Gateway, Committed AP, and Adjusted Net Cash."""
        as_of = dt.date(2026, 8, 15)
        opening_cash = 10_000_000  # $100,000.00

        # Cleared bank movements
        bank_lines = [
            BankStatementLine(
                id="BNK-01",
                date=dt.date(2026, 8, 10),
                amount_cents=500_000,  # +$5,000.00
                raw_description="CUSTOMER WIRE DEPOSIT",
                account_id="ACCT-OPERATING-01",
            ),
            BankStatementLine(
                id="BNK-02",
                date=dt.date(2026, 8, 12),
                amount_cents=-200_000,  # -$2,000.00
                raw_description="OFFICE LEASE ACH",
                account_id="ACCT-OPERATING-01",
            ),
        ]

        # In-flight gateway charges awaiting T+2
        gateway_txs = [
            GatewayTransaction(
                id="GTW-01",
                order_id="ORD-01",
                gross_amount_cents=100_000,
                fee_cents=2_930,
                net_amount_cents=97_070,
                created_date=dt.date(2026, 8, 14),
                settled_date=dt.date(2026, 8, 16),  # Settles tomorrow
                status="succeeded",
            ),
        ]

        # Committed AP liabilities
        ap_invoices = [
            APInvoice(
                id="INV-01",
                vendor_name="AWS Cloud",
                amount_cents=150_000,  # $1,500.00
                due_date=dt.date(2026, 8, 20),
            )
        ]

        pos = CashPositionCalculator.compute_position(
            as_of_date=as_of,
            opening_cash_cents=opening_cash,
            bank_lines=bank_lines,
            gateway_txs=gateway_txs,
            ap_invoices=ap_invoices,
        )

        expected_settled = 10_000_000 + 500_000 - 200_000  # 10,300,000 cents ($103,000.00)
        expected_in_flight = 97_070  # $970.70
        expected_ap = 150_000  # $1,500.00
        expected_adjusted = expected_settled + expected_in_flight - expected_ap  # 10,247,070 cents

        assert pos.settled_cash_cents == expected_settled
        assert pos.in_flight_gateway_cents == expected_in_flight
        assert pos.committed_ap_cents == expected_ap
        assert pos.adjusted_net_cash_cents == expected_adjusted
        assert "$103,000.00" in pos.settled_cash_display
        assert "$102,470.70" in pos.adjusted_net_cash_display


class TestMultiHorizonCashForecasting:
    """Validate 7-day, 14-day, and 30-day roll-forward engine and financial invariants."""

    @pytest.fixture
    def sample_position(self):
        return CashPosition(
            as_of_date=dt.date(2026, 9, 1),
            settled_cash_cents=20_000_000,  # $200,000.00
            in_flight_gateway_cents=500_000,  # $5,000.00
            unsettled_ar_cents=1_000_000,
            committed_ap_cents=3_000_000,  # $30,000.00
            adjusted_net_cash_cents=17_500_000,  # $175,000.00
        )

    def test_monetary_conservation_and_continuous_roll_forward(self, sample_position):
        """Every day satisfies closing = opening + net, and opening[d+1] == closing[d]."""
        report = MultiHorizonCashForecaster.forecast(
            as_of_date=sample_position.as_of_date,
            initial_position=sample_position,
            daily_recurring_inflow_cents=100_000,  # +$1,000/day
            scheduled_outflows=[
                (dt.date(2026, 9, 5), 500_000, "Vendor Software"),
                (dt.date(2026, 9, 15), 4_000_000, "Payroll"),
            ],
            horizon_days=30,
        )

        assert len(report.daily_projections) == 30

        # Invariant 1: First day opens with settled cash
        assert report.daily_projections[0].opening_balance_cents == sample_position.settled_cash_cents

        # Invariant 2 & 3: Conservation of value & continuous chain across all 30 days
        for i, proj in enumerate(report.daily_projections):
            expected_net = proj.expected_inflows_cents - proj.expected_outflows_cents
            assert proj.net_change_cents == expected_net
            assert proj.closing_balance_cents == proj.opening_balance_cents + expected_net

            if i < len(report.daily_projections) - 1:
                next_proj = report.daily_projections[i + 1]
                assert next_proj.opening_balance_cents == proj.closing_balance_cents

    def test_gateway_t_plus_2_settlement_timing(self, sample_position):
        """Gateway charge captured on Sep 1 lands in bank inflows on Sep 3 (T+2)."""
        tx = GatewayTransaction(
            id="GTW-T2",
            order_id="ORD-T2",
            gross_amount_cents=200_000,
            fee_cents=6_100,
            net_amount_cents=193_900,
            created_date=dt.date(2026, 9, 1),
            settled_date=None,  # Simulates automatic T+2
            status="succeeded",
        )

        report = MultiHorizonCashForecaster.forecast(
            as_of_date=dt.date(2026, 9, 1),
            initial_position=sample_position,
            gateway_pipeline=[tx],
            horizon_days=7,
        )

        # Day 1 (Sep 2): Gateway has not landed
        assert report.daily_projections[0].date == dt.date(2026, 9, 2)
        assert report.daily_projections[0].expected_inflows_cents == 0

        # Day 2 (Sep 3): Gateway net amount lands exactly on T+2
        assert report.daily_projections[1].date == dt.date(2026, 9, 3)
        assert report.daily_projections[1].expected_inflows_cents == 193_900
        assert report.daily_projections[1].inflow_breakdown["Gateway T+2 Settlements"] == 193_900

    def test_multi_horizon_milestone_summaries(self, sample_position):
        """Milestones for 7-day, 14-day, and 30-day match respective daily slices."""
        report = MultiHorizonCashForecaster.forecast(
            as_of_date=sample_position.as_of_date,
            initial_position=sample_position,
            daily_recurring_inflow_cents=200_000,
            horizon_days=30,
        )

        h7 = report.horizon_summaries[ForecastHorizon.HORIZON_7_DAY.value]
        h14 = report.horizon_summaries[ForecastHorizon.HORIZON_14_DAY.value]
        h30 = report.horizon_summaries[ForecastHorizon.HORIZON_30_DAY.value]

        assert h7["horizon_days"] == 7
        assert h7["total_inflows_cents"] == 7 * 200_000
        assert h7["closing_cash_cents"] == report.daily_projections[6].closing_balance_cents

        assert h14["horizon_days"] == 14
        assert h14["total_inflows_cents"] == 14 * 200_000
        assert h14["closing_cash_cents"] == report.daily_projections[13].closing_balance_cents

        assert h30["horizon_days"] == 30
        assert h30["total_inflows_cents"] == 30 * 200_000
        assert h30["closing_cash_cents"] == report.daily_projections[29].closing_balance_cents

    def test_cash_runway_under_net_burn_scenario(self, sample_position):
        """Under net burn, monthly burn rate and runway in months are accurately computed."""
        # Burning $30,000/month net ($1,000/day net outflow)
        report = MultiHorizonCashForecaster.forecast(
            as_of_date=sample_position.as_of_date,
            initial_position=sample_position,
            daily_recurring_inflow_cents=50_000,  # $500 in
            scheduled_outflows=[
                (sample_position.as_of_date + dt.timedelta(days=i), 150_000, "Daily Outflow")
                for i in range(1, 31)  # $1,500 out -> Net -$1,000/day
            ],
            horizon_days=30,
        )

        assert report.monthly_burn_rate_cents == 3_000_000  # $30,000.00/month
        assert report.daily_burn_rate_cents == 100_000  # $1,000.00/day

        # Runway = Adjusted Net Cash ($175,000) / Monthly Burn ($30,000) = 5.83 months
        expected_runway = round(17_500_000 / 3_000_000, 2)
        assert report.runway_months == expected_runway

    def test_cash_runway_under_positive_cashflow(self, sample_position):
        """Under positive cash flow, burn rate is 0 and runway is None (infinite)."""
        report = MultiHorizonCashForecaster.forecast(
            as_of_date=sample_position.as_of_date,
            initial_position=sample_position,
            daily_recurring_inflow_cents=500_000,  # $5,000/day in
            horizon_days=30,
        )

        assert report.monthly_burn_rate_cents == 0
        assert report.daily_burn_rate_cents == 0
        assert report.runway_months is None

    def test_liquidity_trough_alert_trigger(self, sample_position):
        """When projected cash dips below safety threshold, trough alert is triggered."""
        # Safety threshold = $180,000 (18,000,000 cents). Initial cash = $200,000.
        # Massive vendor bill of $50,000 on Day 10 brings cash to $150,000 (< $180k).
        report = MultiHorizonCashForecaster.forecast(
            as_of_date=sample_position.as_of_date,
            initial_position=sample_position,
            scheduled_outflows=[
                (sample_position.as_of_date + dt.timedelta(days=10), 5_000_000, "Enterprise Server Bill")
            ],
            safety_threshold_cents=18_000_000,
            horizon_days=15,
        )

        assert report.trough_alert_triggered is True
        assert report.lowest_trough_balance_cents == 15_000_000  # $150,000.00
        assert report.lowest_trough_date == sample_position.as_of_date + dt.timedelta(days=10)
        assert report.daily_projections[9].below_safety_threshold is True


class TestCashFlowWaterfallEngine:
    """Validate liquidity waterfall bridge construction, conservation, and chart export."""

    def test_waterfall_bridge_closure(self):
        """Waterfall opening + inflows - outflows strictly reconciles to closing balance."""
        opening = 50_000_000  # $500,000.00
        gateways = 15_000_000  # +$150,000.00
        wires = 5_000_000  # +$50,000.00
        ap = 12_000_000  # -$120,000.00
        opex = 8_000_000  # -$80,000.00
        remediation = 50_000  # +$500.00

        bridge = CashFlowWaterfallEngine.build_bridge(
            start_date=dt.date(2026, 8, 1),
            end_date=dt.date(2026, 8, 31),
            opening_balance_cents=opening,
            gateway_settlements_cents=gateways,
            direct_wires_cents=wires,
            ap_disbursements_cents=ap,
            operating_expenses_cents=opex,
            remediated_variances_cents=remediation,
        )

        expected_closing = opening + gateways + wires - ap - opex + remediation
        assert bridge.closing_balance_cents == expected_closing
        assert bridge.items[0].category == WaterfallCategory.OPENING
        assert bridge.items[-1].category == WaterfallCategory.CLOSING
        assert bridge.items[-1].running_balance_cents == expected_closing

        # Chart payload format
        payload = bridge.chart_payload
        assert len(payload["labels"]) == len(bridge.items)
        assert payload["step_types"][0] == "total"
        assert payload["step_types"][-1] == "total"
        assert "increase" in payload["step_types"]
        assert "decrease" in payload["step_types"]

    def test_trajectory_payload_export(self):
        """Validates daily forecast trajectory serialization for frontend charts."""
        pos = CashPosition(
            as_of_date=dt.date(2026, 9, 1),
            settled_cash_cents=10_000_000,
            in_flight_gateway_cents=0,
            unsettled_ar_cents=0,
            committed_ap_cents=0,
            adjusted_net_cash_cents=10_000_000,
        )
        report = MultiHorizonCashForecaster.forecast(
            as_of_date=dt.date(2026, 9, 1),
            initial_position=pos,
            daily_recurring_inflow_cents=50_000,
            horizon_days=5,
        )

        trajectory = CashFlowWaterfallEngine.build_trajectory_payload(report.daily_projections)
        assert len(trajectory["dates"]) == 5
        assert len(trajectory["closing_balances_cents"]) == 5
        assert trajectory["closing_balances_cents"][-1] == 10_000_000 + (5 * 50_000)
