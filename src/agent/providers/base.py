"""Base abstract interface for AI exception investigation providers."""

import asyncio
from abc import ABC, abstractmethod
from src.agent.schemas import EvidenceBundle, AIInvestigationResult


class LLMProvider(ABC):
    """Abstract interface implemented by all LLM reasoning backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider implementation."""
        pass

    @abstractmethod
    async def investigate(self, bundle: EvidenceBundle) -> AIInvestigationResult:
        """Asynchronously investigate a financial anomaly evidence bundle."""
        pass

    def investigate_sync(self, bundle: EvidenceBundle) -> AIInvestigationResult:
        """Synchronous wrapper for investigation execution."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # In nested event loop scenarios, run in separate thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, self.investigate(bundle))
                    return future.result()
            else:
                return loop.run_until_complete(self.investigate(bundle))
        except RuntimeError:
            return asyncio.run(self.investigate(bundle))
