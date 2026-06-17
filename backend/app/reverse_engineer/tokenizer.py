from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from .models import CamtTransaction

INVOICE_PATTERN = re.compile(r"\b(?:INV|INVOICE|BILL)[-_]?\d+[A-Z0-9-]*", re.IGNORECASE)
ALNUM_ID_PATTERN = re.compile(r"\b[A-Z0-9]{6,}\b")
WORD_PATTERN = re.compile(r"\b\w+\b")


@dataclass
class TokenWeights:
    """
    Configurable tokenization weights; higher = more important token.
    """
    invoice_ref: float = 2.0
    payment_ref: float = 1.5
    alnum_id: float = 1.0
    company_name: float = 1.0
    generic: float = 0.5


@dataclass
class TokenizedTransaction:
    """
    Token view of a CAMT transaction for matching.
    """
    tx: CamtTransaction
    tokens: Dict[str, float] = field(default_factory=dict)  # token -> weight

    def add_token(self, token: str, weight: float) -> None:
        token_norm = token.strip()
        if not token_norm:
            return
        self.tokens[token_norm] = self.tokens.get(token_norm, 0.0) + weight


class CamtTokenizer:
    """
    Extracts reference and remittance tokens from CAMT transactions.
    """

    def __init__(self, weights: TokenWeights | None = None) -> None:
        self.weights = weights or TokenWeights()

    @staticmethod
    def _split_company_name(name: str) -> List[str]:
        return WORD_PATTERN.findall(name)

    def tokenize(self, tx: CamtTransaction) -> TokenizedTransaction:
        t = TokenizedTransaction(tx=tx)

        # Exact references as strong tokens
        refs = [
            tx.references.end_to_end_id,
            tx.references.instr_id,
            tx.references.tx_id,
            tx.references.acct_svcr_ref,
            tx.references.uetr,
            tx.references.pmt_inf_id,
            tx.references.mndt_id,
        ] + tx.references.other_refs

        for ref in refs:
            if not ref:
                continue
            t.add_token(ref, self.weights.payment_ref)
            # Also search for invoice-like patterns inside references
            for m in INVOICE_PATTERN.finditer(ref):
                t.add_token(m.group(0), self.weights.invoice_ref)

        # Ustrd and structured remittance
        all_remit_texts: List[str] = []
        all_remit_texts.extend(tx.remittance.ustrd_list)
        all_remit_texts.extend(tx.remittance.structured_refs)

        for text in all_remit_texts:
            # Direct invoice-like refs
            for m in INVOICE_PATTERN.finditer(text):
                t.add_token(m.group(0), self.weights.invoice_ref)

            # Generic alphanumeric identifiers
            for m in ALNUM_ID_PATTERN.finditer(text):
                t.add_token(m.group(0), self.weights.alnum_id)

            # Individual words
            for w in WORD_PATTERN.findall(text):
                t.add_token(w, self.weights.generic)

        # Company / counterparty names
        for name in (tx.counterparties.debtor_name, tx.counterparties.creditor_name):
            if not name:
                continue
            t.add_token(name, self.weights.company_name)
            for w in self._split_company_name(name):
                t.add_token(w, self.weights.company_name)

        return t

    def tokenize_many(self, txs: Iterable[CamtTransaction]) -> List[TokenizedTransaction]:
        return [self.tokenize(tx) for tx in txs]
