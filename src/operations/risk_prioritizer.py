"""Operational risk prioritization engine categorizing financial exceptions into P0-P4 tiers."""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from src.agent.schemas import RecommendedAction
from src.domain.models import RiskPriority, ScenarioType
from src.ingestion.normalizer import cents_to_display

UNBOOKED_WIRE_P0_THRESHOLD_CENTS = 1_000_000  # $10,000.00


class PrioritizedException(BaseModel):
    """Financial exception enriched with operational risk tier and exposure metrics."""
    model_config = ConfigDict(validate_assignment=True)

    exception_id: str
    record_id: str
    scenario_type: ScenarioType
    priority: RiskPriority
    amount_cents: StrictInt
    financial_exposure_cents: StrictInt = Field(..., ge=0)
    rationale: str
    recommended_action: Optional[RecommendedAction] = None
    age_days: int = 0


class RiskExposureSummary(BaseModel):
    """Aggregate report of financial risk exposure across all operational tiers."""
    model_config = ConfigDict(validate_assignment=True)

    total_exceptions: int
    total_exposure_cents: StrictInt
    p0_critical_count: int
    p0_critical_exposure_cents: StrictInt
    p1_high_count: int
    p1_high_exposure_cents: StrictInt
    p2_medium_count: int
    p2_medium_exposure_cents: StrictInt
    p4_normal_count: int
    p4_normal_exposure_cents: StrictInt

    @property
    def total_exposure_display(self) -> str:
        return cents_to_display(self.total_exposure_cents)

    @property
    def p0_exposure_display(self) -> str:
        return cents_to_display(self.p0_critical_exposure_cents)


class OperationalRiskPrioritizer:
    """Classifies un-reconciled financial discrepancies into operational risk tiers (P0-P4)."""

    @classmethod
    def prioritize(
        cls,
        exception_id: str,
        record_id: str,
        scenario_type: ScenarioType,
        amount_cents: int,
        memo: Optional[str] = None,
        confidence_score: float = 1.0,
        age_days: int = 0,
        recommended_action: Optional[RecommendedAction] = None,
    ) -> PrioritizedException:
        """Evaluate financial and contextual attributes to assign an operational risk tier."""
        exposure_cents = abs(amount_cents)
        memo_upper = (memo or "").upper()

        # Rule 1: P0_CRITICAL (Unbooked wires > $10,000, suspected fraud, unauthorized debits)
        if (
            scenario_type == ScenarioType.UNEXPLAINED_MISMATCH
            and (
                exposure_cents >= UNBOOKED_WIRE_P0_THRESHOLD_CENTS
                or any(w in memo_upper for w in ["UNIDENTIFIED", "UNAUTHORIZED", "FRAUD"])
            )
        ) or recommended_action == RecommendedAction.ESCALATE_FRAUD:
            priority = RiskPriority.P0_CRITICAL
            rationale = (
                f"P0 Critical Hazard: High-value unbooked cash ({cents_to_display(exposure_cents)}) "
                f"or unexplained discrepancy requiring immediate forensic controller investigation."
            )

        # Rule 2: P1_HIGH (Unexplained variances, missing settlements > T+5, duplicate disbursements)
        elif (
            scenario_type == ScenarioType.UNEXPLAINED_MISMATCH
            or scenario_type == ScenarioType.DUPLICATE
            or (scenario_type == ScenarioType.MISSING_SETTLEMENT and age_days >= 5)
        ):
            priority = RiskPriority.P1_HIGH
            rationale = (
                f"P1 High Risk: Unexplained variance, duplicate disbursement risk, "
                f"or missing settlement aged {age_days} days (>= T+5)."
            )

        # Rule 3: P2_MEDIUM (Tax withholding differences, refunds, low confidence matches)
        elif (
            scenario_type in [ScenarioType.TAX_DIFFERENCE, ScenarioType.REFUND]
            or scenario_type == ScenarioType.MISSING_SETTLEMENT
            or confidence_score < 0.70
            or recommended_action == RecommendedAction.REVIEW_REQUIRED
        ):
            priority = RiskPriority.P2_MEDIUM
            rationale = (
                f"P2 Medium Priority: Documented tax variance, chargeback/refund flow, "
                f"or ambiguous match (confidence: {confidence_score:.1%})."
            )

        # Rule 4: P4_NORMAL (Routine timing delays, fee schedule differences, exact parity)
        else:
            priority = RiskPriority.P4_NORMAL
            rationale = (
                f"P4 Normal: Routine timing difference (T+2 cutoff), interchange fee variance, "
                f"or standard batch adjustment."
            )

        return PrioritizedException(
            exception_id=exception_id,
            record_id=record_id,
            scenario_type=scenario_type,
            priority=priority,
            amount_cents=amount_cents,
            financial_exposure_cents=exposure_cents,
            rationale=rationale,
            recommended_action=recommended_action,
            age_days=age_days,
        )

    @classmethod
    def compute_exposure_summary(
        cls,
        exceptions: List[PrioritizedException],
    ) -> RiskExposureSummary:
        """Aggregate total financial exposure and count breakdown per operational risk tier."""
        total_exposure = sum(e.financial_exposure_cents for e in exceptions)

        p0_list = [e for e in exceptions if e.priority == RiskPriority.P0_CRITICAL]
        p1_list = [e for e in exceptions if e.priority == RiskPriority.P1_HIGH]
        p2_list = [e for e in exceptions if e.priority == RiskPriority.P2_MEDIUM]
        p4_list = [e for e in exceptions if e.priority == RiskPriority.P4_NORMAL]

        return RiskExposureSummary(
            total_exceptions=len(exceptions),
            total_exposure_cents=total_exposure,
            p0_critical_count=len(p0_list),
            p0_critical_exposure_cents=sum(e.financial_exposure_cents for e in p0_list),
            p1_high_count=len(p1_list),
            p1_high_exposure_cents=sum(e.financial_exposure_cents for e in p1_list),
            p2_medium_count=len(p2_list),
            p2_medium_exposure_cents=sum(e.financial_exposure_cents for e in p2_list),
            p4_normal_count=len(p4_list),
            p4_normal_exposure_cents=sum(e.financial_exposure_cents for e in p4_list),
        )
