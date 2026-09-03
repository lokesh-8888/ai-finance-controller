"""Main AI Exception Investigator service with zero-failure fallback guarantee."""

import logging
from typing import List, Optional

from src.agent.ambiguity_gate import AmbiguityGatingPolicy
from src.agent.prompts import sanitize_financial_text
from src.agent.providers.base import LLMProvider
from src.agent.providers.local_heuristic import LocalHeuristicProvider
from src.agent.schemas import (
    AIInvestigationResult,
    EvidenceBundle,
)

logger = logging.getLogger(__name__)


class AIExceptionInvestigator:
    """Orchestrates forensic AI exception investigations across pluggable LLM backends.

    Features:
    - Zero-Failure Guarantee: Seamless fallback to LocalHeuristicProvider if external LLM fails.
    - Prompt Injection Defense: Automatic token and memo sanitization.
    - Strict Ambiguity Gating: Policy enforcement (< 8% margin gap, confidence thresholds).
    """

    def __init__(
        self,
        primary_provider: Optional[LLMProvider] = None,
        fallback_provider: Optional[LLMProvider] = None,
    ):
        self.fallback_provider = fallback_provider or LocalHeuristicProvider()
        self.primary_provider = primary_provider or self.fallback_provider

    async def investigate(self, bundle: EvidenceBundle) -> AIInvestigationResult:
        """Investigate an exception evidence bundle with automatic fallback resilience."""
        # 1. Sanitize text fields against prompt injection attacks
        sanitized_bundle = self._sanitize_bundle(bundle)

        # 2. Attempt investigation with primary provider
        result: Optional[AIInvestigationResult] = None
        fallback_used = False
        fallback_reason = ""

        if self.primary_provider != self.fallback_provider:
            try:
                result = await self.primary_provider.investigate(sanitized_bundle)
            except Exception as e:
                logger.warning(
                    f"Primary provider '{self.primary_provider.name}' failed for "
                    f"record '{bundle.target_record_id}': {e}. Falling back to {self.fallback_provider.name}."
                )
                fallback_used = True
                fallback_reason = f"Primary provider ({self.primary_provider.name}) failed: {type(e).__name__} - {e}"

        # 3. Fallback execution if needed or primary was fallback
        if result is None:
            result = await self.fallback_provider.investigate(sanitized_bundle)
            if fallback_used:
                result.supporting_evidence.append(f"[FALLBACK NOTICE] {fallback_reason}")

        # 4. Enforce strict ambiguity gating and risk policy
        final_result = AmbiguityGatingPolicy.apply_policy(result)
        return final_result

    def investigate_sync(self, bundle: EvidenceBundle) -> AIInvestigationResult:
        """Synchronous wrapper for investigation execution."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, self.investigate(bundle))
                return future.result()
        else:
            return asyncio.run(self.investigate(bundle))

    async def investigate_batch(self, bundles: List[EvidenceBundle]) -> List[AIInvestigationResult]:
        """Investigate a collection of evidence bundles sequentially or concurrently."""
        results = []
        for bundle in bundles:
            res = await self.investigate(bundle)
            results.append(res)
        return results

    def investigate_batch_sync(self, bundles: List[EvidenceBundle]) -> List[AIInvestigationResult]:
        """Synchronous batch investigation execution."""
        return [self.investigate_sync(b) for b in bundles]

    def _sanitize_bundle(self, bundle: EvidenceBundle) -> EvidenceBundle:
        """Create a safe copy of the evidence bundle with disarmed text fields."""
        data = bundle.model_dump()
        if data.get("description"):
            data["description"] = sanitize_financial_text(data["description"])
        if data.get("reference_code"):
            data["reference_code"] = sanitize_financial_text(data["reference_code"])
        if data.get("context_notes"):
            data["context_notes"] = [sanitize_financial_text(n) for n in data["context_notes"]]
        return EvidenceBundle(**data)
