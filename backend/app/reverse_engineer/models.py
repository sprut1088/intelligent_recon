from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)


@dataclass
class CamtReferenceSet:
    """
    Normalized set of all CAMT reference-like identifiers for a transaction.

    This is used as the "signal space" for matching against flat-file lines.
    """
    end_to_end_id: Optional[str] = None
    instr_id: Optional[str] = None
    tx_id: Optional[str] = None
    acct_svcr_ref: Optional[str] = None
    uetr: Optional[str] = None
    pmt_inf_id: Optional[str] = None
    mndt_id: Optional[str] = None
    other_refs: List[str] = field(default_factory=list)


@dataclass
class CamtRemittanceInfo:
    """
    Unstructured / structured remittance data from CAMT.
    """
    ustrd_list: List[str] = field(default_factory=list)
    structured_refs: List[str] = field(default_factory=list)


@dataclass
class CamtCounterparties:
    debtor_name: Optional[str] = None
    creditor_name: Optional[str] = None


@dataclass
class CamtTransaction:
    """
    Normalized CAMT.053 transaction.

    This aggregates all signals that might be useful when matching
    to an unknown flat-file record.
    """
    booking_date: Optional[date]
    value_date: Optional[date]
    amount: float
    currency: str

    references: CamtReferenceSet
    remittance: CamtRemittanceInfo
    counterparties: CamtCounterparties

    raw_xml_path: str
    entry_index: int

    def primary_id(self) -> str:
        """Return a canonical transaction id used in outputs."""
        for ref in (
            self.references.end_to_end_id,
            self.references.tx_id,
            self.references.instr_id,
            self.references.acct_svcr_ref,
        ):
            if ref:
                return ref
        return f"ENTRY-{self.entry_index}"


@dataclass
class FlatLine:
    """
    Representation of a single flat-file line.
    """
    line_number: int  # 1-based
    raw: str


@dataclass
class AmountMatchResult:
    """
    Result of attempting to match a CAMT amount to a value discovered
    inside a flat-file line under different plausible scaling factors.
    """
    matched: bool
    best_factor: float
    confidence: float
    matched_amount_in_line: Optional[float] = None


@dataclass
class DateMatchResult:
    """
    Result of attempting to match CAMT booking/value dates to date-like
    tokens in the flat-file line.
    """
    matched: bool
    matched_dates_in_line: List[date] = field(default_factory=list)


@dataclass
class MatchingSignals:
    """
    Fine-grained explanation of what matched between CAMT and a flat line.
    """
    exact_reference_matches: List[str] = field(default_factory=list)
    end_to_end_match: bool = False
    acct_svcr_ref_match: bool = False
    uetr_match: bool = False
    invoice_ref_matches: List[str] = field(default_factory=list)
    amount_match: Optional[AmountMatchResult] = None
    date_match: Optional[DateMatchResult] = None
    counterparty_match_score: float = 0.0
    ustrd_token_overlap: float = 0.0


@dataclass
class PairComponentEvidence:
    """
    Per-component evidence contributing to a pair_confidence score.
    Slim version of the Results Workbench breakdown for LLM samples.
    """
    component: str
    weight: float
    passed: bool
    evidence: str
    raw_value_psr: str | None = None
    raw_value_camt: str | None = None


@dataclass
class PairScore:
    """
    Final score for a candidate CAMT↔flat-line pair.
    """
    transaction: CamtTransaction
    flat_line: FlatLine
    pair_confidence: float
    matched_signals: MatchingSignals
    # Optional per-component breakdown for explainability
    components: List[PairComponentEvidence] = field(default_factory=list)


@dataclass
class ScoringWeights:
    """
    Configurable weights for each signal. All are relative; the final
    confidence is normalized into [0, 1].
    """
    w_exact_reference: float = 3.0
    w_end_to_end: float = 2.0
    w_acct_svcr_ref: float = 2.0
    w_uetr: float = 2.0
    w_invoice_ref: float = 2.5
    w_amount: float = 3.0
    w_date: float = 2.0
    w_counterparty: float = 2.0
    w_ustrd_overlap: float = 1.5

    def as_dict(self) -> Dict[str, float]:
        return self.__dict__.copy()


@dataclass
class DatasetSample:
    """
    Single training / evaluation sample for later LLM reverse engineering.
    """
    camt: Dict[str, Any]
    flat_raw_line: str
    pair_confidence: float
    # Optional per-pair explainability for UI
    pair_components: List[PairComponentEvidence] = field(default_factory=list)
    pair_explanation: str | None = None


@dataclass
class Dataset:
    """
    Container for LLM-ready dataset.
    """
    samples: List[DatasetSample] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"samples": [s.__dict__ for s in self.samples]}
