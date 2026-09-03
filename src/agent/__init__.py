"""AI Exception Investigation, ambiguity gating, and cognitive reasoning package."""

from src.agent.schemas import (
    RecommendedAction,
    CandidateScore,
    EvidenceBundle,
    AIInvestigationResult,
)
from src.agent.prompts import (
    FINANCIAL_COT_SYSTEM_PROMPT,
    sanitize_financial_text,
    build_investigation_prompt,
)
from src.agent.ambiguity_gate import AmbiguityGatingPolicy
from src.agent.investigator import AIExceptionInvestigator
from src.agent.providers import (
    LLMProvider,
    LocalHeuristicProvider,
    OpenAIProvider,
    GeminiProvider,
)

__all__ = [
    "RecommendedAction",
    "CandidateScore",
    "EvidenceBundle",
    "AIInvestigationResult",
    "FINANCIAL_COT_SYSTEM_PROMPT",
    "sanitize_financial_text",
    "build_investigation_prompt",
    "AmbiguityGatingPolicy",
    "AIExceptionInvestigator",
    "LLMProvider",
    "LocalHeuristicProvider",
    "OpenAIProvider",
    "GeminiProvider",
]
