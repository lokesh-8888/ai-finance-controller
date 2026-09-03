"""Independent evaluation harness benchmarking the reconciliation pipeline against Ground Truth."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.agent.investigator import AIExceptionInvestigator
from src.agent.schemas import EvidenceBundle, RecommendedAction
from src.domain.models import (
    BankStatementLine,
    GatewayTransaction,
    ERPLedgerEntry,
    APInvoice,
    GroundTruthRecord,
    ScenarioType,
)
from src.evaluation.metrics import EvaluationReport
from src.ingestion.normalizer import load_json_as_dicts
from src.reconciliation.engine import ReconciliationEngine


class ReconciliationEvaluator:
    """Evaluates the end-to-end reconciliation and AI exception pipeline against Ground Truth."""

    def __init__(
        self,
        project_root: Optional[Path] = None,
        investigator: Optional[AIExceptionInvestigator] = None,
    ):
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent.parent
        self.project_root = project_root
        self.investigator = investigator or AIExceptionInvestigator()

    def run_benchmark(self) -> EvaluationReport:
        """Execute full benchmark evaluation against canonical data and ground-truth matrix."""
        canonical_dir = self.project_root / "data" / "canonical"
        ground_truth_dir = self.project_root / "data" / "ground_truth"

        # 1. Load ground truth
        gt_dicts = load_json_as_dicts(ground_truth_dir / "ground_truth.json")
        ground_truth_records = [GroundTruthRecord(**r) for r in gt_dicts]

        # 2. Load canonical source datasets
        bank_lines = [BankStatementLine(**b) for b in load_json_as_dicts(canonical_dir / "bank_statement_lines.json")]
        gateway_txs = [GatewayTransaction(**g) for g in load_json_as_dicts(canonical_dir / "gateway_transactions.json")]
        erp_entries = [ERPLedgerEntry(**e) for e in load_json_as_dicts(canonical_dir / "erp_ledger_entries.json")]
        ap_invoices = [APInvoice(**a) for a in load_json_as_dicts(canonical_dir / "ap_invoices.json")]

        # 3. Execute Phase 1: Deterministic Engine
        engine = ReconciliationEngine(date_tolerance_days=5)
        recon_output = engine.reconcile(
            bank_lines=bank_lines,
            gateway_txs=gateway_txs,
            erp_entries=erp_entries,
            ap_invoices=ap_invoices,
        )

        # Build lookup of matched entity IDs to their deterministic matched scenario
        entity_to_match_scenario: Dict[str, ScenarioType] = {}
        for match in recon_output.matches:
            for bid in match.bank_line_ids:
                entity_to_match_scenario[bid] = match.scenario_type
            for gid in match.gateway_tx_ids:
                entity_to_match_scenario[gid] = match.scenario_type
            for eid in match.erp_entry_ids:
                entity_to_match_scenario[eid] = match.scenario_type
            for iid in match.invoice_ids:
                entity_to_match_scenario[iid] = match.scenario_type

        # 4. Map and evaluate each Ground-Truth Scenario
        # Fast entity lookups for evidence bundle creation
        bank_by_id = {b.id: b for b in bank_lines}
        gtw_by_id = {g.id: g for g in gateway_txs}
        erp_by_id = {e.id: e for e in erp_entries}
        inv_by_id = {i.id: i for i in ap_invoices}

        predicted_scenarios: Dict[str, ScenarioType] = {}
        ai_latencies: List[float] = []
        action_counts: Dict[str, int] = {
            "AUTO_RESOLVE": 0,
            "REVIEW_REQUIRED": 0,
            "ESCALATE_FRAUD": 0,
        }

        deterministic_correct = 0
        total_scenarios = len(ground_truth_records)

        for gt in ground_truth_records:
            # Check if this scenario was resolved by the deterministic engine
            anchor_id = self._get_anchor_id(gt, entity_to_match_scenario)
            det_scenario = entity_to_match_scenario.get(anchor_id)

            if det_scenario is not None:
                predicted_scenarios[gt.scenario_id] = det_scenario
                action_counts["AUTO_RESOLVE"] += 1
                if det_scenario == gt.scenario_type:
                    deterministic_correct += 1
            else:
                # Stage 3: AI Exception Investigation
                bundle = self._build_bundle_for_scenario(
                    gt=gt,
                    bank_by_id=bank_by_id,
                    gtw_by_id=gtw_by_id,
                    erp_by_id=erp_by_id,
                    inv_by_id=inv_by_id,
                    entity_to_match_scenario=entity_to_match_scenario,
                )
                ai_result = self.investigator.investigate_sync(bundle)
                predicted_scenarios[gt.scenario_id] = ai_result.scenario_type
                ai_latencies.append(ai_result.latency_ms)

                action_counts[ai_result.recommended_action.value] = (
                    action_counts.get(ai_result.recommended_action.value, 0) + 1
                )

        # 5. Compute Classification Metrics & Confusion Matrix
        confusion_matrix: Dict[str, Dict[str, int]] = {}
        all_scenario_types = [s.value for s in ScenarioType]
        for s1 in all_scenario_types:
            confusion_matrix[s1] = {s2: 0 for s2 in all_scenario_types}

        correct_count = 0
        fraud_anomalies_total = 0
        fraud_false_positives = 0

        for gt in ground_truth_records:
            expected = gt.scenario_type.value
            predicted = predicted_scenarios[gt.scenario_id].value
            confusion_matrix[expected][predicted] += 1

            if expected == predicted:
                correct_count += 1

            # Fraud anomaly verification:
            # If scenario is UNEXPLAINED_MISMATCH (fraud/unbooked wire),
            # verifying that it was NEVER erroneously auto-resolved as an exact match or fee difference
            if gt.scenario_type == ScenarioType.UNEXPLAINED_MISMATCH:
                fraud_anomalies_total += 1
                if predicted in [ScenarioType.EXACT_MATCH.value, ScenarioType.FEE_DIFFERENCE.value]:
                    fraud_false_positives += 1

        overall_accuracy = correct_count / total_scenarios if total_scenarios > 0 else 0.0
        baseline_acc_pct = (deterministic_correct / total_scenarios * 100.0) if total_scenarios > 0 else 0.0
        post_ai_acc_pct = (correct_count / total_scenarios * 100.0) if total_scenarios > 0 else 0.0
        accuracy_lift = post_ai_acc_pct - baseline_acc_pct

        fraud_fpr = (fraud_false_positives / fraud_anomalies_total) if fraud_anomalies_total > 0 else 0.0

        # Calculate macro precision, recall, and F1
        macro_prec, macro_rec, macro_f1 = self._calculate_macro_scores(
            confusion_matrix=confusion_matrix,
            ground_truth_records=ground_truth_records,
        )

        total_ai_latency = sum(ai_latencies)
        avg_ai_latency = (total_ai_latency / len(ai_latencies)) if ai_latencies else 0.0

        return EvaluationReport(
            total_scenarios=total_scenarios,
            deterministic_matches_count=deterministic_correct,
            ai_investigated_count=len(ai_latencies),
            classification_accuracy=round(overall_accuracy, 4),
            precision_macro=round(macro_prec, 4),
            recall_macro=round(macro_rec, 4),
            f1_score_macro=round(macro_f1, 4),
            false_positive_rate_fraud=round(fraud_fpr, 4),
            baseline_deterministic_accuracy_pct=round(baseline_acc_pct, 2),
            post_ai_final_accuracy_pct=round(post_ai_acc_pct, 2),
            accuracy_lift_pct=round(accuracy_lift, 2),
            average_ai_latency_ms=round(avg_ai_latency, 2),
            total_ai_latency_ms=round(total_ai_latency, 2),
            confusion_matrix=confusion_matrix,
            action_breakdown=action_counts,
        )

    def _get_anchor_id(
        self,
        gt: GroundTruthRecord,
        entity_to_match_scenario: Optional[Dict[str, ScenarioType]] = None,
    ) -> str:
        """Extract a primary anchor entity ID for ground truth record correlation."""
        if gt.scenario_type == ScenarioType.DUPLICATE and entity_to_match_scenario:
            # Pick the duplicate entity that remained un-reconciled
            if gt.bank_line_id and "," in gt.bank_line_id:
                parts = [p.strip() for p in gt.bank_line_id.split(",")]
                unmatched_parts = [p for p in parts if p not in entity_to_match_scenario]
                if unmatched_parts:
                    return unmatched_parts[0]
            if gt.erp_entry_id and "," in gt.erp_entry_id:
                parts = [p.strip() for p in gt.erp_entry_id.split(",")]
                unmatched_parts = [p for p in parts if p not in entity_to_match_scenario]
                if unmatched_parts:
                    return unmatched_parts[0]

        if gt.bank_line_id:
            return gt.bank_line_id.split(",")[0].strip()
        if gt.gateway_tx_id:
            return gt.gateway_tx_id.split(",")[0].strip()
        if gt.invoice_id:
            return gt.invoice_id.split(",")[0].strip()
        if gt.erp_entry_id:
            return gt.erp_entry_id.split(",")[0].strip()
        return ""

    def _build_bundle_for_scenario(
        self,
        gt: GroundTruthRecord,
        bank_by_id: Dict[str, BankStatementLine],
        gtw_by_id: Dict[str, GatewayTransaction],
        erp_by_id: Dict[str, ERPLedgerEntry],
        inv_by_id: Dict[str, APInvoice],
        entity_to_match_scenario: Optional[Dict[str, ScenarioType]] = None,
    ) -> EvidenceBundle:
        """Construct an EvidenceBundle from scenario references."""
        record_id = self._get_anchor_id(gt, entity_to_match_scenario)
        rec_type = "Unknown"
        amount_cents = 0
        date_str = None
        desc = ""
        ref_code = None
        candidates: List[Dict[str, Any]] = []
        notes = [f"Scenario: {gt.scenario_id}", gt.explanation]

        if record_id in bank_by_id:
            b = bank_by_id[record_id]
            rec_type = "BankStatementLine"
            amount_cents = b.amount_cents
            date_str = b.date.isoformat()
            desc = b.raw_description
            ref_code = b.reference_code
        elif record_id in gtw_by_id:
            g = gtw_by_id[record_id]
            rec_type = "GatewayTransaction"
            amount_cents = g.gross_amount_cents
            ref_code = g.order_id
            desc = f"Gateway charge {g.id} order {g.order_id}"
        elif record_id in inv_by_id:
            inv = inv_by_id[record_id]
            rec_type = "APInvoice"
            amount_cents = inv.amount_cents
            date_str = inv.due_date.isoformat()
            desc = f"AP Invoice {inv.id} {inv.vendor_name}"
        elif record_id in erp_by_id:
            e = erp_by_id[record_id]
            rec_type = "ERPLedgerEntry"
            amount_cents = e.amount_cents
            date_str = e.entry_date.isoformat()
            desc = f"GL Entry {e.id} {e.customer_vendor_name}"

        # Add candidate information if available in other references
        if gt.gateway_tx_id and gt.gateway_tx_id in gtw_by_id:
            g = gtw_by_id[gt.gateway_tx_id]
            candidates.append({"id": g.id, "type": "Gateway", "amount_cents": g.net_amount_cents, "gross": g.gross_amount_cents})
        if gt.erp_entry_id and gt.erp_entry_id in erp_by_id:
            e = erp_by_id[gt.erp_entry_id]
            candidates.append({"id": e.id, "type": "ERP", "amount_cents": e.amount_cents})
        if gt.invoice_id and gt.invoice_id in inv_by_id:
            i = inv_by_id[gt.invoice_id]
            candidates.append({"id": i.id, "type": "APInvoice", "amount_cents": i.amount_cents})

        return EvidenceBundle(
            target_record_id=record_id,
            target_record_type=rec_type,
            amount_cents=amount_cents,
            date=date_str,
            description=desc,
            reference_code=ref_code,
            candidate_matches=candidates,
            context_notes=notes,
        )

    def _calculate_macro_scores(
        self,
        confusion_matrix: Dict[str, Dict[str, int]],
        ground_truth_records: List[GroundTruthRecord],
    ) -> Tuple[float, float, float]:
        """Compute macro-averaged Precision, Recall, and F1 across scenario classes."""
        active_classes = {gt.scenario_type.value for gt in ground_truth_records}

        precisions: List[float] = []
        recalls: List[float] = []
        f1s: List[float] = []

        for cls_name in active_classes:
            tp = confusion_matrix[cls_name][cls_name]
            fp = sum(confusion_matrix[other][cls_name] for other in active_classes if other != cls_name)
            fn = sum(confusion_matrix[cls_name][other] for other in active_classes if other != cls_name)

            prec = tp / (tp + fp) if (tp + fp) > 0 else 1.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 1.0
            f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0

            precisions.append(prec)
            recalls.append(rec)
            f1s.append(f1)

        macro_prec = sum(precisions) / len(precisions) if precisions else 0.0
        macro_rec = sum(recalls) / len(recalls) if recalls else 0.0
        macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0

        return macro_prec, macro_rec, macro_f1
