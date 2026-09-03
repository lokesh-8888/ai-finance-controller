"""Strict ambiguity gating and confidence policy engine for financial decisions."""

from typing import Optional
from src.agent.schemas import (
    AIInvestigationResult,
    RecommendedAction,
)


class AmbiguityGatingPolicy:
    """Enforces strict risk and ambiguity policies on AI investigation outputs.

    Rules:
    1. Auto-Resolve: confidence >= 0.85 AND ambiguity_gap >= 0.08 -> AUTO_RESOLVE.
    2. Ambiguity Margin Gap: if gap between top 2 candidates < 0.08 (8%) -> REVIEW_REQUIRED.
    3. Quarantine / Fraud Cutoff: confidence < 0.40 -> ESCALATE_FRAUD.
    4. Review Default: 0.40 <= confidence < 0.85 -> REVIEW_REQUIRED.
    """

    AUTO_RESOLVE_THRESHOLD = 0.85
    AMBIGUITY_GAP_THRESHOLD = 0.08  # 8% delta
    FRAUD_QUARANTINE_CUTOFF = 0.40

    @classmethod
    def apply_policy(cls, result: AIInvestigationResult) -> AIInvestigationResult:
        """Evaluate an AI investigation result and enforce strict policy gating."""
        candidates = result.top_candidates
        gap: Optional[float] = None

        if len(candidates) >= 2:
            gap = round(abs(candidates[0].confidence - candidates[1].confidence), 4)
            result.ambiguity_gap = gap

        score = result.confidence_score

        # Rule 1: Fraud / Unexplained Quarantine Cutoff
        if score < cls.FRAUD_QUARANTINE_CUTOFF:
            result.recommended_action = RecommendedAction.ESCALATE_FRAUD
            result.supporting_evidence.append(
                f"[POLICY ALERT] Confidence {score:.1%} is below the 40.0% threshold; "
                f"escalated to forensic fraud / audit queue."
            )
            return result

        # Rule 2: Ambiguity Margin Gap Check (< 8% delta)
        if gap is not None and gap < cls.AMBIGUITY_GAP_THRESHOLD:
            result.recommended_action = RecommendedAction.REVIEW_REQUIRED
            c1_name = candidates[0].scenario_type.value
            c2_name = candidates[1].scenario_type.value
            result.supporting_evidence.append(
                f"[AMBIGUITY GATE] Margin gap between '{c1_name}' ({candidates[0].confidence:.1%}) "
                f"and '{c2_name}' ({candidates[1].confidence:.1%}) is {gap:.1%} (< 8.0%); "
                f"flagged for mandatory controller review to prevent speculative guessing."
            )
            return result

        # Rule 3: High-Confidence Auto-Resolve
        if score >= cls.AUTO_RESOLVE_THRESHOLD and (gap is None or gap >= cls.AMBIGUITY_GAP_THRESHOLD):
            result.recommended_action = RecommendedAction.AUTO_RESOLVE
            return result

        # Rule 4: Intermediate Confidence (0.40 <= score < 0.85)
        result.recommended_action = RecommendedAction.REVIEW_REQUIRED
        result.supporting_evidence.append(
            f"[POLICY NOTICE] Confidence {score:.1%} requires standard controller sign-off."
        )
        return result
