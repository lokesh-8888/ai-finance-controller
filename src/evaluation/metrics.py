"""Evaluation report models and metric aggregation schemas."""

from typing import Dict
from pydantic import BaseModel, ConfigDict, Field


class EvaluationReport(BaseModel):
    """Structured report produced by benchmarking the reconciliation pipeline against Ground Truth."""
    model_config = ConfigDict(validate_assignment=True)

    total_scenarios: int = Field(..., description="Total ground-truth benchmark scenarios")
    deterministic_matches_count: int = Field(..., description="Scenarios resolved by Stage 1 & Stage 2")
    ai_investigated_count: int = Field(..., description="Residual scenarios investigated by Stage 3 AI")

    classification_accuracy: float = Field(..., ge=0.0, le=1.0, description="Overall classification accuracy")
    precision_macro: float = Field(..., ge=0.0, le=1.0, description="Macro-averaged precision")
    recall_macro: float = Field(..., ge=0.0, le=1.0, description="Macro-averaged recall")
    f1_score_macro: float = Field(..., ge=0.0, le=1.0, description="Macro-averaged F1 score")

    false_positive_rate_fraud: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="False positive rate on unbooked cash and fraud anomalies (must be 0.0%)"
    )

    baseline_deterministic_accuracy_pct: float = Field(
        ...,
        description="Accuracy % achieved by Stage 1 & 2 alone before AI"
    )
    post_ai_final_accuracy_pct: float = Field(
        ...,
        description="Final end-to-end accuracy % after AI exception investigation"
    )
    accuracy_lift_pct: float = Field(
        ...,
        description="Improvement delta: post_ai_final_accuracy - baseline_deterministic_accuracy"
    )

    average_ai_latency_ms: float = Field(..., description="Mean AI latency per investigated exception in ms")
    total_ai_latency_ms: float = Field(..., description="Total cumulative AI compute latency in ms")

    confusion_matrix: Dict[str, Dict[str, int]] = Field(
        default_factory=dict,
        description="Matrix mapping ground truth expected scenario -> predicted scenario -> count"
    )
    action_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="Counts of recommended actions (AUTO_RESOLVE, REVIEW_REQUIRED, ESCALATE_FRAUD)"
    )
