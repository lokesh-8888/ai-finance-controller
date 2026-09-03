"""20-seed independent draw robustness evaluation suite proving zero cherry-picking."""

import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from src.domain.models import ScenarioType
from src.evaluation.evaluator import ReconciliationEvaluator
from src.generator.data_generator import SyntheticFinanceDataset
from src.reconciliation.engine import ReconciliationEngine


class SeedEvaluationRun(BaseModel):
    """Metrics achieved by a single independent seed benchmark run."""
    model_config = ConfigDict(validate_assignment=True)

    seed: int
    total_scenarios: int
    accuracy: float
    precision_macro: float
    recall_macro: float
    f1_macro: float
    fraud_fpr: float


class RobustnessBenchmarkReport(BaseModel):
    """Statistical distribution of performance across N independent random seeds."""
    model_config = ConfigDict(validate_assignment=True)

    total_runs: int
    seeds: List[int]
    runs: List[SeedEvaluationRun]

    mean_accuracy: float
    std_accuracy: float

    mean_precision: float
    std_precision: float

    mean_recall: float
    std_recall: float

    mean_f1: float
    std_f1: float

    mean_fraud_fpr: float
    max_fraud_fpr: float


class RobustnessBenchmark:
    """Executes multi-seed Monte Carlo robustness evaluation against synthetic draws."""

    @classmethod
    def run_benchmark(
        cls,
        seeds: Optional[List[int]] = None,
    ) -> RobustnessBenchmarkReport:
        """Run N independent random seeds and compute statistical distributions."""
        if seeds is None:
            seeds = list(range(101, 121))  # Default 20 seeds: 101 to 120

        evaluator = ReconciliationEvaluator()
        run_results: List[SeedEvaluationRun] = []

        for seed in seeds:
            # Generate independent synthetic universe for this seed
            dataset = SyntheticFinanceDataset(seed=seed).generate_all()

            # Execute reconciliation pipeline
            engine = ReconciliationEngine(date_tolerance_days=5)
            recon_output = engine.reconcile(
                bank_lines=dataset.bank_lines,
                gateway_txs=dataset.gateway_txs,
                erp_entries=dataset.erp_entries,
                ap_invoices=dataset.ap_invoices,
            )

            # Map matches
            matched_entities: Dict[str, ScenarioType] = {}
            for m in recon_output.matches:
                for bid in m.bank_line_ids:
                    matched_entities[bid] = m.scenario_type
                for gid in m.gateway_tx_ids:
                    matched_entities[gid] = m.scenario_type
                for eid in m.erp_entry_ids:
                    matched_entities[eid] = m.scenario_type
                for iid in m.invoice_ids:
                    matched_entities[iid] = m.scenario_type

            # Fast lookups for bundle creation
            bank_by_id = {b.id: b for b in dataset.bank_lines}
            gtw_by_id = {g.id: g for g in dataset.gateway_txs}
            erp_by_id = {e.id: e for e in dataset.erp_entries}
            inv_by_id = {i.id: i for i in dataset.ap_invoices}

            gt_records = dataset.ground_truth
            predicted: Dict[str, ScenarioType] = {}

            for gt in gt_records:
                anchor_id = evaluator._get_anchor_id(gt, matched_entities)
                det = matched_entities.get(anchor_id)
                if det is not None:
                    predicted[gt.scenario_id] = det
                else:
                    bundle = evaluator._build_bundle_for_scenario(
                        gt=gt,
                        bank_by_id=bank_by_id,
                        gtw_by_id=gtw_by_id,
                        erp_by_id=erp_by_id,
                        inv_by_id=inv_by_id,
                        entity_to_match_scenario=matched_entities,
                    )
                    res = evaluator.investigator.investigate_sync(bundle)
                    predicted[gt.scenario_id] = res.scenario_type

            # Evaluate metrics for this seed
            correct = sum(1 for gt in gt_records if predicted[gt.scenario_id] == gt.scenario_type)
            acc = correct / len(gt_records) if gt_records else 0.0

            # Fraud FPR check
            fraud_items = [gt for gt in gt_records if gt.scenario_type == ScenarioType.UNEXPLAINED_MISMATCH]
            fraud_fps = sum(
                1 for f in fraud_items
                if predicted[f.scenario_id] in [ScenarioType.EXACT_MATCH, ScenarioType.FEE_DIFFERENCE]
            )
            fraud_fpr = fraud_fps / len(fraud_items) if fraud_items else 0.0

            # Confusion matrix for macro scores
            cm: Dict[str, Dict[str, int]] = {
                s1.value: {s2.value: 0 for s2 in ScenarioType} for s1 in ScenarioType
            }
            for gt in gt_records:
                cm[gt.scenario_type.value][predicted[gt.scenario_id].value] += 1

            macro_p, macro_r, macro_f1 = evaluator._calculate_macro_scores(cm, gt_records)

            run_results.append(
                SeedEvaluationRun(
                    seed=seed,
                    total_scenarios=len(gt_records),
                    accuracy=round(acc, 4),
                    precision_macro=round(macro_p, 4),
                    recall_macro=round(macro_r, 4),
                    f1_macro=round(macro_f1, 4),
                    fraud_fpr=round(fraud_fpr, 4),
                )
            )

        # Statistical calculations
        n = len(run_results)
        mean_acc = sum(r.accuracy for r in run_results) / n
        std_acc = math.sqrt(sum((r.accuracy - mean_acc) ** 2 for r in run_results) / n)

        mean_p = sum(r.precision_macro for r in run_results) / n
        std_p = math.sqrt(sum((r.precision_macro - mean_p) ** 2 for r in run_results) / n)

        mean_r = sum(r.recall_macro for r in run_results) / n
        std_r = math.sqrt(sum((r.recall_macro - mean_r) ** 2 for r in run_results) / n)

        mean_f1 = sum(r.f1_macro for r in run_results) / n
        std_f1 = math.sqrt(sum((r.f1_macro - mean_f1) ** 2 for r in run_results) / n)

        mean_fraud = sum(r.fraud_fpr for r in run_results) / n
        max_fraud = max(r.fraud_fpr for r in run_results)

        return RobustnessBenchmarkReport(
            total_runs=n,
            seeds=seeds,
            runs=run_results,
            mean_accuracy=round(mean_acc, 4),
            std_accuracy=round(std_acc, 4),
            mean_precision=round(mean_p, 4),
            std_precision=round(std_p, 4),
            mean_recall=round(mean_r, 4),
            std_recall=round(std_r, 4),
            mean_f1=round(mean_f1, 4),
            std_f1=round(std_f1, 4),
            mean_fraud_fpr=round(mean_fraud, 4),
            max_fraud_fpr=round(max_fraud, 4),
        )
