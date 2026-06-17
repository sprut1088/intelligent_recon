from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List

from .matcher import MatchingEngine
from .models import (
    CamtTransaction,
    Dataset,
    DatasetSample,
    FlatLine,
    PairComponentEvidence,
)


class DatasetBuilder:
    """
    Builds a JSON-serializable dataset of high-confidence CAMT↔flat-line pairs
    suitable for LLM-based flat-file reverse engineering.
    """

    def __init__(self, engine: MatchingEngine | None = None) -> None:
        self.engine = engine or MatchingEngine()

    def build_dataset(
        self,
        transactions: Iterable[CamtTransaction],
        flat_lines: Iterable[FlatLine],
        min_confidence: float = 0.7,
        top_n_per_tx: int = 3,
    ) -> Dataset:
        matches_by_tx = self.engine.match_all(
            transactions=transactions,
            flat_lines=flat_lines,
            top_n_per_tx=top_n_per_tx,
        )

        samples: List[DatasetSample] = []
        for tx_id, pair_scores in matches_by_tx.items():
            for ps in pair_scores:
                if ps.pair_confidence < min_confidence:
                    continue
                camt_dict: Dict[str, object] = {
                    "transaction_id": tx_id,
                    "booking_date": ps.transaction.booking_date.isoformat()
                    if ps.transaction.booking_date
                    else None,
                    "value_date": ps.transaction.value_date.isoformat()
                    if ps.transaction.value_date
                    else None,
                    "amount": ps.transaction.amount,
                    "currency": ps.transaction.currency,
                    "references": asdict(ps.transaction.references),
                    "remittance": asdict(ps.transaction.remittance),
                    "counterparties": asdict(ps.transaction.counterparties),
                }

                # Per-pair explainability for LLM / UI
                comps: List[PairComponentEvidence] = getattr(ps, "components", [])
                strong_comps = [c for c in comps if c.passed and c.weight > 0]
                weak_comps = [c for c in comps if (not c.passed) and c.weight > 0]

                summary_parts: List[str] = []
                if strong_comps:
                    strong_names = ", ".join(sorted({c.component for c in strong_comps}))
                    summary_parts.append(f"Strong evidence from: {strong_names}.")
                if weak_comps:
                    weak_names = ", ".join(sorted({c.component for c in weak_comps}))
                    summary_parts.append(f"Limited or failing evidence on: {weak_names}.")
                pair_explanation = " ".join(summary_parts) or None

                samples.append(
                    DatasetSample(
                        camt=camt_dict,
                        flat_raw_line=ps.flat_line.raw,
                        pair_confidence=ps.pair_confidence,
                        pair_components=comps,
                        pair_explanation=pair_explanation,
                    )
                )

        return Dataset(samples=samples)

    @staticmethod
    def save_dataset(dataset: Dataset, path: Path) -> None:
        path.write_text(json.dumps(dataset.to_dict(), indent=2), encoding="utf-8")
