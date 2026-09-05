"""Month-End Reconciliation Audit Memo and report generation endpoints."""

from typing import Any, Dict
from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from src.reporting.audit_report import MonthEndAuditReportGenerator

router = APIRouter(prefix="/api/v1/reports", tags=["Executive Reports"])
report_gen = MonthEndAuditReportGenerator()


@router.get("/audit-memo")
def get_audit_memo(format: str = Query("csv", description="Format: csv, markdown, or json")):
    """Retrieve Month-End Reconciliation Audit artifacts in CSV, Markdown, or JSON format."""
    files = report_gen.generate()
    fmt = format.lower().strip()
    if fmt == "json":
        import json
        with open(files["json"], "r", encoding="utf-8") as f:
            data = json.load(f)
        with open(files["markdown"], "r", encoding="utf-8") as f:
            data["markdown_memo"] = f.read()
        return data

    if fmt in ("md", "markdown"):
        with open(files["markdown"], "r", encoding="utf-8") as f:
            return PlainTextResponse(
                f.read(),
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": "attachment; filename=reconciliation_audit_memo.md"},
            )

    # Default to CSV workpaper export (preferred by financial controllers and accountants)
    with open(files["csv"], "r", encoding="utf-8") as f:
        return PlainTextResponse(
            f.read(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=reconciliation_audit_workpapers.csv"},
        )


@router.post("/export")
def export_reports() -> Dict[str, Any]:
    """Generate and persist all audit memo files (Markdown, JSON, CSV) to disk."""
    files = report_gen.generate()
    return {
        "status": "success",
        "exported_files": {k: str(v) for k, v in files.items()},
    }
