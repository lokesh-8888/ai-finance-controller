"""Grounded natural language financial Q&A copilot query endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

from src.copilot.assistant import CopilotResponse, GroundedFinancialCopilot

router = APIRouter(prefix="/api/v1/copilot", tags=["Financial Copilot"])
copilot = GroundedFinancialCopilot()


class CopilotQueryRequest(BaseModel):
    query: str


@router.post("/query", response_model=CopilotResponse)
def query_copilot(req: CopilotQueryRequest):
    """Process natural language financial query grounded in deterministic application state."""
    return copilot.query(req.query)
