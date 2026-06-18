from __future__ import annotations

import logging
import math
import re
from datetime import date
from typing import Dict, Iterable, List, Tuple

from rapidfuzz import fuzz

from .models import (
    AmountMatchResult,
    CamtTransaction,
    DateMatchResult,
    FlatLine,
    MatchingSignals,
    PairScore,
    PairComponentEvidence,
    ScoringWeights,
)
from .tokenizer import CamtTokenizer, TokenizedTransaction

logger = logging.getLogger(__name__)

AMOUNT_FACTOR_CANDIDATES = [1, 0.1, 0.01, 0.001, 10, 100, 1000]

DATE_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    # YYYYMMDD anywhere in the line (even if embedded in other text, e.g. 20TX-...20260610PMT-...)
    (re.compile(r"(\d{8})(?!\d)"), "%Y%m%d"),
    (re.compile(r"\b(\d{6})\b"), "%y%m%d"),      # YYMMDD
    (re.compile(r"\b(\d{2})(\d{2})(\d{4})\b"), "DDMMYYYY"),  # DDMMYYYY
    (re.compile(r"\b(\d{2})(\d{2})(\d{2})\b"), "DDMMYY"),    # DDMMYY
    (re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"), "%Y-%m-%d"),    # YYYY-MM-DD
    (re.compile(r"\b(\d{2}-\d{2}-\d{4})\b"), "DD-MM-YYYY"),  # DD-MM-YYYY
]


def _extract_amount_candidates(line: str) -> List[float]:
    """
    Extract raw numeric sequences that look like amounts (before scaling).
    """
    candidates: List[float] = []
    for m in re.finditer(r"\d+(?:\.\d+)?", line):
        try:
            candidates.append(float(m.group(0)))
        except ValueError:
            continue
    return candidates


def _match_amount(amount: float, line: str) -> AmountMatchResult:
    """
    Try to match a CAMT amount against all numbers found in the line,
    under possible scaling factors.
    """
    raw_numbers = _extract_amount_candidates(line)
    if not raw_numbers:
        return AmountMatchResult(False, best_factor=1.0, confidence=0.0)

    best_factor = 1.0
    best_conf = 0.0
    best_in_line: float | None = None

    for factor in AMOUNT_FACTOR_CANDIDATES:
        for n in raw_numbers:
            scaled = n * factor
            diff = abs(scaled - amount)
            if diff <= 0.01:
                # Confidence: smaller diff, higher confidence; prefer factors closer to 1
                conf = 1.0 - min(diff, 1.0)
                if factor != 1.0:
                    conf *= 0.9
                if conf > best_conf:
                    best_conf = conf
                    best_factor = factor
                    best_in_line = n

    matched = best_conf > 0.0
    return AmountMatchResult(
        matched=matched,
        best_factor=best_factor,
        confidence=best_conf,
        matched_amount_in_line=best_in_line,
    )


def _parse_date_token(token: str, fmt: str) -> date | None:
    from datetime import datetime

    try:
        if fmt == "DDMMYYYY":
            return datetime.strptime(token, "%d%m%Y").date()
        if fmt == "DDMMYY":
            return datetime.strptime(token, "%d%m%y").date()
        if fmt == "DD-MM-YYYY":
            return datetime.strptime(token, "%d-%m-%Y").date()
        return datetime.strptime(token, fmt).date()
    except ValueError:
        return None


def _match_dates(camt_dates: List[date | None], line: str) -> DateMatchResult:
    """
    Look for date-like tokens in the line and see if any match CAMT dates.
    """

    camt_dates_clean = [d for d in camt_dates if d is not None]
    if not camt_dates_clean:
        return DateMatchResult(matched=False, matched_dates_in_line=[])

    candidates: List[date] = []
    for pattern, fmt in DATE_PATTERNS:
        for m in pattern.finditer(line):
            token = m.group(1)
            dt = _parse_date_token(token, fmt)
            if dt:
                candidates.append(dt)

    if not candidates:
        return DateMatchResult(False, [])

    matched_dates: List[date] = []
    for cd in camt_dates_clean:
        for cand in candidates:
            if cand == cd:
                matched_dates.append(cand)
                break

    return DateMatchResult(
        matched=bool(matched_dates),
        matched_dates_in_line=matched_dates,
    )


def _string_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return fuzz.token_set_ratio(a, b) / 100.0


def _token_overlap_score(tokens: Dict[str, float], line: str) -> float:
    """
    Compute a weighted token overlap between CAMT tokens and words in
    the flat-file line.
    """
    words = {w.lower() for w in re.findall(r"\w+", line)}
    if not words:
        return 0.0

    score = 0.0
    max_score = sum(tokens.values()) or 1.0
    for token, weight in tokens.items():
        if token.lower() in words:
            score += weight
    return min(score / max_score, 1.0)


class MatchingEngine:
    """
    Core matching engine that scores each CAMT transaction against each
    flat-file line to produce high-confidence pairs.
    """

    def __init__(
        self,
        scoring_weights: ScoringWeights | None = None,
    ) -> None:
        self.weights = scoring_weights or ScoringWeights()
        self.tokenizer = CamtTokenizer()

    def _line_exact_reference_hits(
        self, tx: CamtTransaction, line: str
    ) -> List[Tuple[str, str]]:
        """
        Return (field_name, value) pairs for all CAMT reference fields whose value
        appears exactly in the PSR line.

        We keep substring semantics here to avoid dropping true matches and apply
        a narrow guard on EndToEndId in the specific-flag logic instead.
        """
        hits: List[Tuple[str, str]] = []

        ref_fields: List[Tuple[str, str | None]] = [
            ("EndToEndId", tx.references.end_to_end_id),
            ("InstrId", tx.references.instr_id),
            ("TxId", tx.references.tx_id),
            ("AcctSvcrRef", tx.references.acct_svcr_ref),
            ("UETR", tx.references.uetr),
            ("PmtInfId", tx.references.pmt_inf_id),
            ("MndtId", tx.references.mndt_id),
        ]

        # Preserve any additional reference-like values as synthetic fields.
        for idx, val in enumerate(tx.references.other_refs or []):
            ref_fields.append((f"OtherRef{idx + 1}", val))

        for field_name, ref in ref_fields:
            if not ref:
                continue
            if ref in line:
                hits.append((field_name, ref))
        return hits

    def _build_matching_signals(
        self,
        tokenized_tx: TokenizedTransaction,
        line_obj: FlatLine,
    ) -> MatchingSignals:
        tx = tokenized_tx.tx
        line = line_obj.raw

        sig = MatchingSignals()

        # 1) Exact reference matches
        exact_hits = self._line_exact_reference_hits(tx, line)
        # Flat list of values (for existing scoring behaviour)
        sig.exact_reference_matches = [v for (_field, v) in exact_hits]

        # Dynamic map: reference field name -> list of matched values
        field_map: Dict[str, List[str]] = {}
        for field_name, ref in exact_hits:
            field_map.setdefault(field_name, []).append(ref)
        sig.exact_ref_matches_by_field = field_map

        # 2) Specific refs
        # EndToEndId: avoid obvious noisy "end to end id etc" style descriptions
        if tx.references.end_to_end_id:
            e2e = tx.references.end_to_end_id
            if e2e in line:
                lower_line = line.lower()
                lower_e2e = e2e.lower()
                idx = lower_line.find(lower_e2e)
                trailing = lower_line[idx + len(lower_e2e) : idx + len(lower_e2e) + 16]
                # Heuristic list of noisy suffixes directly following the phrase
                noisy_suffixes = [" id", " id ", " id:", " id-", " etc", " etc ", " etc.", " ref"]
                sig.end_to_end_match = not any(s in trailing for s in noisy_suffixes)
            else:
                sig.end_to_end_match = False

        if tx.references.acct_svcr_ref and tx.references.acct_svcr_ref in line:
            sig.acct_svcr_ref_match = True
        if tx.references.uetr and tx.references.uetr in line:
            sig.uetr_match = True

        # 3) Invoice-like ref matches (simple heuristic)
        invoice_matches = []
        for part in re.findall(r"[A-Z0-9-]+", line, flags=re.IGNORECASE):
            if re.search(r"INV|INVOICE|BILL", part, re.IGNORECASE):
                invoice_matches.append(part)
        sig.invoice_ref_matches = invoice_matches

        # 4) Amount match
        sig.amount_match = _match_amount(tx.amount, line)

        # 5) Date match (booking & value)
        camt_dates = [tx.booking_date, tx.value_date]
        sig.date_match = _match_dates(camt_dates, line)

        # 6) Counterparty name match (fuzzy)
        best_cp = 0.0
        for name in (
            tx.counterparties.debtor_name,
            tx.counterparties.creditor_name,
        ):
            if not name:
                continue
            best_cp = max(best_cp, _string_similarity(name, line))
        sig.counterparty_match_score = best_cp

        # 7) Ustrd token overlap (using tokenizer)
        sig.ustrd_token_overlap = _token_overlap_score(tokenized_tx.ustrdtokens, line)

        return sig

    def _score_signals(self, sig: MatchingSignals) -> float:
        """
        Compute an unnormalized score from matching signals.
        """
        w = self.weights
        score = 0.0

        score += w.w_exact_reference * len(sig.exact_reference_matches)

        if sig.end_to_end_match:
            score += w.w_end_to_end
        if sig.acct_svcr_ref_match:
            score += w.w_acct_svcr_ref
        if sig.uetr_match:
            score += w.w_uetr

        score += w.w_invoice_ref * len(sig.invoice_ref_matches)

        if sig.amount_match and sig.amount_match.matched:
            score += w.w_amount * sig.amount_match.confidence

        if sig.date_match and sig.date_match.matched:
            score += w.w_date * min(len(sig.date_match.matched_dates_in_line), 2)

        score += w.w_counterparty * sig.counterparty_match_score
        score += w.w_ustrd_overlap * sig.ustrd_token_overlap

        return max(score, 0.0)

    def _normalize_score(self, raw_score: float) -> float:
        """
        Normalize into [0,1]. For simplicity, use a logistic compression.
        """
        scale = 10.0
        x = raw_score / scale
        return 1.0 / (1.0 + math.exp(-x))

    def score_pair(
        self,
        tokenized_tx: TokenizedTransaction,
        line: FlatLine,
    ) -> PairScore:
        sig = self._build_matching_signals(tokenized_tx, line)
        raw_score = self._score_signals(sig)
        conf = self._normalize_score(raw_score)

        tx = tokenized_tx.tx
        line_str = line.raw

        components: List[PairComponentEvidence] = []

        # Exact references (grouped)
        if sig.exact_reference_matches:
            components.append(
                PairComponentEvidence(
                    component="exact_reference",
                    weight=self.weights.w_exact_reference * len(sig.exact_reference_matches),
                    passed=True,
                    evidence=f"{len(sig.exact_reference_matches)} exact reference(s) found in line.",
                    raw_value_psr=", ".join(sig.exact_reference_matches),
                    raw_value_camt=line_str,
                )
            )

        # EndToEnd ID
        if tx.references.end_to_end_id:
            components.append(
                PairComponentEvidence(
                    component="end_to_end_id",
                    weight=self.weights.w_end_to_end,
                    passed=sig.end_to_end_match,
                    evidence=(
                        "EndToEnd ID present in line."
                        if sig.end_to_end_match
                        else "EndToEnd ID not found in line."
                    ),
                    raw_value_psr=tx.references.end_to_end_id,
                    raw_value_camt=line_str,
                )
            )

        # Account servicer reference
        if tx.references.acct_svcr_ref:
            components.append(
                PairComponentEvidence(
                    component="acct_svcr_ref",
                    weight=self.weights.w_acct_svcr_ref,
                    passed=sig.acct_svcr_ref_match,
                    evidence=(
                        "Account servicer reference present in line."
                        if sig.acct_svcr_ref_match
                        else "Account servicer reference not found in line."
                    ),
                    raw_value_psr=tx.references.acct_svcr_ref,
                    raw_value_camt=line_str,
                )
            )

        # UETR
        if tx.references.uetr:
            components.append(
                PairComponentEvidence(
                    component="uetr",
                    weight=self.weights.w_uetr,
                    passed=sig.uetr_match,
                    evidence=(
                        "UETR present in line."
                        if sig.uetr_match
                        else "UETR not found in line."
                    ),
                    raw_value_psr=tx.references.uetr,
                    raw_value_camt=line_str,
                )
            )

        # Invoice-like tokens
        if sig.invoice_ref_matches:
            components.append(
                PairComponentEvidence(
                    component="invoice_ref",
                    weight=self.weights.w_invoice_ref * len(sig.invoice_ref_matches),
                    passed=True,
                    evidence=f"{len(sig.invoice_ref_matches)} invoice-like token(s) found in line.",
                    raw_value_psr=", ".join(sig.invoice_ref_matches),
                    raw_value_camt=line_str,
                )
            )

        # Amount
        if sig.amount_match:
            am = sig.amount_match
            components.append(
                PairComponentEvidence(
                    component="amount",
                    weight=self.weights.w_amount * am.confidence,
                    passed=am.matched,
                    evidence=(
                        f"Amount matched with factor {am.best_factor}."
                        if am.matched
                        else "No acceptable amount match found."
                    ),
                    raw_value_psr=str(tx.amount),
                    raw_value_camt=(
                        str(am.matched_amount_in_line)
                        if am.matched_amount_in_line is not None
                        else None
                    ),
                )
            )

        # Dates (booking/value)
        if sig.date_match:
            dm = sig.date_match
            components.append(
                PairComponentEvidence(
                    component="date",
                    weight=self.weights.w_date
                    * min(len(dm.matched_dates_in_line), 2),
                    passed=dm.matched,
                    evidence=(
                        f"{len(dm.matched_dates_in_line)} date(s) matched."
                        if dm.matched
                        else "No booking/value date match found."
                    ),
                    raw_value_psr=" / ".join(
                        [
                            d.isoformat()
                            for d in [tx.booking_date, tx.value_date]
                            if d is not None
                        ]
                    )
                    or None,
                    raw_value_camt=", ".join(
                        [d.isoformat() for d in dm.matched_dates_in_line]
                    )
                    or None,
                )
            )

        # Counterparty name similarity
        if tx.counterparties.debtor_name or tx.counterparties.creditor_name:
            components.append(
                PairComponentEvidence(
                    component="counterparty",
                    weight=self.weights.w_counterparty * sig.counterparty_match_score,
                    passed=sig.counterparty_match_score >= 0.6,
                    evidence=f"Name similarity {sig.counterparty_match_score:.2f}.",
                    raw_value_psr=tx.counterparties.debtor_name
                    or tx.counterparties.creditor_name,
                    raw_value_camt=line_str,
                )
            )

        components.append(
            PairComponentEvidence(
                component="ustrd_tokens",
                weight=self.weights.w_ustrd_overlap * sig.ustrd_token_overlap,
                passed=sig.ustrd_token_overlap >= 0.5,
                evidence=(
                    f"Token overlap score {sig.ustrd_token_overlap:.2f}."
                    if sig.ustrd_token_overlap > 0
                    else "No significant remittance token overlap."
                ),
                raw_value_psr="; ".join(tokenized_tx.ustrdtokens.keys()),
                raw_value_camt=line_str,
            )
        ) 

        return PairScore(
            transaction=tx,
            flat_line=line,
            pair_confidence=conf,
            matched_signals=sig,
            components=components,
        )

    def match_all(
        self,
        transactions: Iterable[CamtTransaction],
        flat_lines: Iterable[FlatLine],
        top_n_per_tx: int = 3,
    ) -> Dict[str, List[PairScore]]:
        """
        For each CAMT transaction, evaluate flat-file lines, rank
        candidates, and keep top N.

        IMPORTANT:
        - We enforce an "exact reference first" strategy:
          * If any PSR line contains an exact structured reference for a CAMT tx
            (EndToEndId, InstrId, TxId, AcctSvcrRef, UETR, PmtInfId, MndtId, or other_refs),
            we restrict candidates for that tx to ONLY those exact-hit lines.
          * Only if there are no exact-reference hits at all do we fall back
            to the full composite / fuzzy scoring across all lines.
        """
        tokenized = self.tokenizer.tokenize_many(transactions)
        line_list = list(flat_lines)

        results: Dict[str, List[PairScore]] = {}
        for t in tokenized:
            tx = t.tx
            tx_id = tx.primary_id()
            scores: List[PairScore] = []

            # 1) First pass: find lines with any exact-reference hit for this tx
            exact_hit_lines: List[FlatLine] = []
            for line in line_list:
                if self._line_exact_reference_hits(tx, line.raw):
                    exact_hit_lines.append(line)

            # 2) Decide candidate set:
            #    - If we have exact hits, only score those lines.
            #    - Otherwise, score all lines (composite/fuzzy fallback).
            candidate_lines = exact_hit_lines if exact_hit_lines else line_list

            for line in candidate_lines:
                ps = self.score_pair(t, line)
                scores.append(ps)

            scores.sort(key=lambda s: s.pair_confidence, reverse=True)
            results[tx_id] = scores[:top_n_per_tx]

        return results
