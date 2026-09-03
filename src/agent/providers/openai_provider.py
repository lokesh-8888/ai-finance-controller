"""OpenAI GPT-4o / GPT-4o-mini integration for AI exception investigation."""

import json
import os
import time
from typing import Optional
import httpx

from src.agent.prompts import FINANCIAL_COT_SYSTEM_PROMPT, build_investigation_prompt
from src.agent.providers.base import LLMProvider
from src.agent.schemas import (
    AIInvestigationResult,
    CandidateScore,
    EvidenceBundle,
    RecommendedAction,
)
from src.domain.models import ScenarioType


class OpenAIProvider(LLMProvider):
    """Integrates OpenAI GPT models with structured JSON output and temperature=0.0."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 15.0,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return f"OpenAI({self.model})"

    async def investigate(self, bundle: EvidenceBundle) -> AIInvestigationResult:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not configured")

        start_time = time.perf_counter()
        user_prompt = build_investigation_prompt(bundle)

        payload = {
            "model": self.model,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": FINANCIAL_COT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        raw_result = json.loads(content)

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        candidates = [
            CandidateScore(
                scenario_type=ScenarioType(c["scenario_type"]),
                confidence=float(c["confidence"]),
                rationale=str(c.get("rationale", "")),
            )
            for c in raw_result.get("top_candidates", [])
        ]

        ambiguity_gap = None
        if len(candidates) >= 2:
            ambiguity_gap = round(candidates[0].confidence - candidates[1].confidence, 4)

        return AIInvestigationResult(
            investigation_id=raw_result.get("investigation_id", f"INV-OAI-{bundle.target_record_id}"),
            record_id=bundle.target_record_id,
            scenario_type=ScenarioType(raw_result["scenario_type"]),
            suspected_cause=str(raw_result["suspected_cause"]),
            supporting_evidence=[str(e) for e in raw_result.get("supporting_evidence", [])],
            recommended_action=RecommendedAction(raw_result["recommended_action"]),
            confidence_score=float(raw_result["confidence_score"]),
            top_candidates=candidates,
            ambiguity_gap=ambiguity_gap,
            reasoning_trace=str(raw_result.get("reasoning_trace", "")),
            provider_name=self.name,
            latency_ms=round(latency_ms, 2),
        )
