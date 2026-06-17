from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from lxml import etree

from .models import (
    CamtCounterparties,
    CamtReferenceSet,
    CamtRemittanceInfo,
    CamtTransaction,
)

logger = logging.getLogger(__name__)


class Camt053Parser:
    """
    CAMT.053 XML parser that extracts all useful matching signals.

    Uses lxml for robust namespace handling.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._doc: Optional[etree._ElementTree] = None

    def load(self) -> None:
        logger.info("Loading CAMT.053 XML from %s", self.path)
        self._doc = etree.parse(str(self.path))

    @staticmethod
    def _ns_strip(tag: object) -> str:
        """
        Safely strip XML namespace from an lxml tag.

        lxml element tags are normally strings like '{ns}Ntry'. However, if a
        non-string object is passed here (e.g. a cython function/method due to
        some misuse), we defensively return an empty string instead of raising.
        """
        if not isinstance(tag, str):
            return ""
        return tag.split("}")[-1]

    @staticmethod
    def _parse_date_or_none(text: Optional[str]) -> Optional[datetime.date]:
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    def iter_entries(self) -> Iterable[etree._Element]:
        assert self._doc is not None, "Call load() first"
        root = self._doc.getroot()
        for el in root.iter():
            tag = self._ns_strip(getattr(el, "tag", ""))
            if tag == "Ntry":
                yield el

    def _extract_references(self, ntry: etree._Element) -> CamtReferenceSet:
        refs = CamtReferenceSet()
        other_refs: List[str] = []

        for el in ntry.iter():
            tag = self._ns_strip(el.tag)
            text = (el.text or "").strip()
            if not text:
                continue

            if tag == "EndToEndId" and not refs.end_to_end_id:
                refs.end_to_end_id = text
            elif tag == "InstrId" and not refs.instr_id:
                refs.instr_id = text
            elif tag == "TxId" and not refs.tx_id:
                refs.tx_id = text
            elif tag == "AcctSvcrRef" and not refs.acct_svcr_ref:
                refs.acct_svcr_ref = text
            elif tag == "UETR" and not refs.uetr:
                refs.uetr = text
            elif tag == "PmtInfId" and not refs.pmt_inf_id:
                refs.pmt_inf_id = text
            elif tag == "MndtId" and not refs.mndt_id:
                refs.mndt_id = text
            elif tag.lower().endswith("ref") or "Ref" in tag:
                # Generic reference-like field
                other_refs.append(text)

        refs.other_refs = list(sorted(set(other_refs)))
        return refs

    def _extract_remittance(self, ntry: etree._Element) -> CamtRemittanceInfo:
        ustrd_list: List[str] = []
        structured: List[str] = []

        for el in ntry.iter():
            tag = self._ns_strip(el.tag)
            text = (el.text or "").strip()
            if not text:
                continue

            if tag == "Ustrd":
                ustrd_list.append(text)
            elif tag.endswith("Ref") or "Ref" in tag:
                structured.append(text)

        return CamtRemittanceInfo(
            ustrd_list=list(sorted(set(ustrd_list))),
            structured_refs=list(sorted(set(structured))),
        )

    def _extract_counterparties(self, ntry: etree._Element) -> CamtCounterparties:
        debtor_name: Optional[str] = None
        creditor_name: Optional[str] = None

        for el in ntry.iter():
            tag = self._ns_strip(el.tag)
            text = (el.text or "").strip()
            if not text:
                continue

            if tag == "Dbtr" and debtor_name is None:
                for child in el:
                    if self._ns_strip(child.tag) == "Nm":
                        debtor_name = (child.text or "").strip()
                        break
            elif tag == "Cdtr" and creditor_name is None:
                for child in el:
                    if self._ns_strip(child.tag) == "Nm":
                        creditor_name = (child.text or "").strip()
                        break

        return CamtCounterparties(
            debtor_name=debtor_name,
            creditor_name=creditor_name,
        )

    def _extract_dates_amount_currency(
        self, ntry: etree._Element
    ) -> Tuple[Optional[datetime.date], Optional[datetime.date], float, str]:
        booking_date: Optional[datetime.date] = None
        value_date: Optional[datetime.date] = None
        amount = 0.0
        currency = ""

        for el in ntry.iter():
            tag = self._ns_strip(el.tag)

            if tag in ("BookgDt", "Dt") and booking_date is None:
                for child in el:
                    txt = (child.text or "").strip()
                    if txt:
                        booking_date = self._parse_date_or_none(txt)
                        break

            if tag in ("ValDt",) and value_date is None:
                for child in el:
                    txt = (child.text or "").strip()
                    if txt:
                        value_date = self._parse_date_or_none(txt)
                        break

            if tag == "Amt" and amount == 0.0:
                raw = (el.text or "").strip().replace(",", "")
                try:
                    amount = float(raw)
                except ValueError:
                    amount = 0.0
                ccy = el.get("Ccy") or ""
                currency = ccy.strip()

        return booking_date, value_date, amount, currency

    def parse_transactions(self) -> List[CamtTransaction]:
        """
        Parse all CAMT.053 Ntry elements into normalized CamtTransaction objects.
        """
        if self._doc is None:
            self.load()

        transactions: List[CamtTransaction] = []
        for idx, ntry in enumerate(self.iter_entries()):
            booking_date, value_date, amount, currency = self._extract_dates_amount_currency(ntry)
            refs = self._extract_references(ntry)
            remittance = self._extract_remittance(ntry)
            counterparties = self._extract_counterparties(ntry)

            tx = CamtTransaction(
                booking_date=booking_date,
                value_date=value_date,
                amount=amount,
                currency=currency,
                references=refs,
                remittance=remittance,
                counterparties=counterparties,
                raw_xml_path=str(self.path),
                entry_index=idx,
            )
            transactions.append(tx)

        logger.info("Parsed %d CAMT transactions from %s", len(transactions), self.path)
        return transactions
