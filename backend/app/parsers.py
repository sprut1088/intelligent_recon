from __future__ import annotations
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional
import re
import xml.etree.ElementTree as ET
from .config import settings

logger = logging.getLogger(__name__)

PMT_REF_RE = re.compile(r"PMT-REF-\d+", re.IGNORECASE)
INVOICE_RE = re.compile(r"INV[-\s]?\d{4}[-\s]?\d+|INV[-\s]?\d+", re.IGNORECASE)

@dataclass
class PsrHeader:
    record_type: str
    raw_line: str
    currency: str
    processing_date: Optional[str] = None
    account_iban: Optional[str] = None

@dataclass
class PsrTransaction:
    id: str
    execution_date: str
    reference: str
    amount: float
    direction: str
    invoice: str
    counterparty: str
    currency: str
    source_line: int
    raw_line: str

@dataclass
class CamtTransaction:
    ntry_id: str
    camt_id: str
    end_to_end_id: str
    amount: float
    direction: str
    booking_date: str
    value_date: str
    currency: str
    remittance: str
    counterparty: str
    pmt_ref: str
    invoice: str
    raw: Dict[str, str]

def normalise_direction(value: str) -> str:
    value = (value or "").strip().upper()
    if value in {"CR", "CRDT", "CREDIT"}: return "CR"
    if value in {"DR", "DBIT", "DEBIT"}: return "DR"
    return value or "UNKNOWN"

def extract_pmt_ref(text: str) -> str:
    match = PMT_REF_RE.search(text or "")
    return match.group(0).upper() if match else ""

def extract_invoice(text: str) -> str:
    match = INVOICE_RE.search(text or "")
    return match.group(0).upper().replace(" ", "-") if match else ""

def invoice_suffix(invoice: str) -> str:
    tokens = re.findall(r"\d+", (invoice or "").upper())
    return tokens[-1] if tokens else ""

def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())

def parse_yyyymmdd(value: str) -> str:
    value = (value or "").strip()
    return f"{value[0:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 and value.isdigit() else value

def parse_psr_file(path: Path, amount_divisor: Optional[float] = None) -> tuple[Optional[PsrHeader], List[PsrTransaction]]:
    logger.info("Parsing PSR file: %s (divisor=%s)", path, amount_divisor)
    divisor = settings.psr_amount_divisor if amount_divisor is None else amount_divisor
    header: Optional[PsrHeader] = None
    transactions: List[PsrTransaction] = []
    currency = "EUR"
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.rstrip("\n")
            record_type = line[0:2]
            if record_type == "10":
                currency = line[-3:].strip() or "EUR"
                header = PsrHeader("10", line, currency, parse_yyyymmdd(line[11:19]) if len(line) >= 19 else None, line[19:-3].strip() if len(line) > 22 else None)
                continue
            if record_type in {"99", ""}: continue
            if record_type != "20": continue
            # The client brief provides a fixed-width layout, but the uploaded 10k
            # sample uses wider reference/invoice fields and variable-length IDs
            # once the sequence reaches TX-2026-10000. Prefer semantic parsing.
            semantic = re.match(r"^20(?P<tid>TX-\d{4}-\d+?)(?P<dt>\d{8})(?P<rest>PMT-.*)$", line)
            if semantic:
                txn_id = semantic.group("tid").strip()
                execution_date = parse_yyyymmdd(semantic.group("dt"))
                rest = semantic.group("rest")
                detail = re.match(r"(?P<ref>.*?)\s+(?P<amt>\d{12})(?P<direction>CR|DR)(?P<tail>.*)$", rest)
                if not detail:
                    continue
                reference = detail.group("ref").strip()
                amount_raw = detail.group("amt").strip() or "0"
                direction = normalise_direction(detail.group("direction"))
                tail = detail.group("tail")
                invoice = tail[:25].strip()
                counterparty = clean_text(tail[25:])
            else:
                # Fallback to the shorter positional specification from the brief.
                txn_id = line[2:14].strip()
                execution_date = parse_yyyymmdd(line[14:22])
                reference = line[22:42].strip()
                amount_raw = line[42:54].strip() or "0"
                direction = normalise_direction(line[54:56])
                invoice = line[56:76].strip()
                counterparty = clean_text(line[76:100])
            try: amount = int(amount_raw) / divisor
            except ValueError: amount = 0.0
            transactions.append(PsrTransaction(
                id=txn_id, execution_date=execution_date, reference=reference, amount=float(amount),
                direction=direction, invoice=invoice, counterparty=counterparty,
                currency=currency, source_line=line_no, raw_line=line))
    logger.info("PSR parse complete: %d transactions", len(transactions))
    return header, transactions



def _first_text_by_local_name(parent: ET.Element, local_name: str) -> str:
    for item in parent.iter():
        if item.tag.split("}")[-1] == local_name and item.text:
            return clean_text(item.text)
    return ""

def _first_element_by_local_name(parent: ET.Element, local_name: str) -> Optional[ET.Element]:
    for item in parent.iter():
        if item.tag.split("}")[-1] == local_name:
            return item
    return None

def _children_by_local_name(parent: ET.Element, local_name: str) -> Iterable[ET.Element]:
    for item in parent.iter():
        if item.tag.split("}")[-1] == local_name:
            yield item

def parse_camt_file(path: Path) -> List[CamtTransaction]:
    logger.info("Parsing CAMT file: %s", path)
    root = ET.parse(path).getroot()
    entries = [node for node in root.iter() if node.tag.split("}")[-1] == "Ntry"]
    transactions: List[CamtTransaction] = []
    for idx, entry in enumerate(entries, start=1):
        amt_el = next((child for child in entry if child.tag.split("}")[-1] == "Amt"), None)
        if amt_el is None:
            amt_el = _first_element_by_local_name(entry, "Amt")
        amount = float(clean_text(amt_el.text) or 0) if amt_el is not None else 0.0
        currency = amt_el.attrib.get("Ccy", "EUR") if amt_el is not None else "EUR"
        direction = normalise_direction(_first_text_by_local_name(entry, "CdtDbtInd"))
        booking_date = _first_text_by_local_name(entry, "Dt")
        e2e_raw = _first_text_by_local_name(entry, "EndToEndId")
        end_to_end_id = e2e_raw if e2e_raw and e2e_raw.upper() not in ("NOTFOUND", "NOT FOUND", "N/A", "NOTAVAILABLE") else ""
        counterparty = _first_text_by_local_name(entry, "Nm")
        remittance = " ".join(clean_text(item.text) for item in _children_by_local_name(entry, "Ustrd") if item.text)
        pmt_ref = extract_pmt_ref(remittance)
        invoice = extract_invoice(remittance)
        ntry_ref = _first_text_by_local_name(entry, "NtryRef")
        ntry_id = ntry_ref or f"NTRY-{idx}"
        camt_id = end_to_end_id or ntry_id
        transactions.append(CamtTransaction(ntry_id, camt_id, end_to_end_id, amount, direction, booking_date, booking_date, currency, remittance, counterparty, pmt_ref, invoice, {"ntry_id": ntry_id, "camt_id": camt_id, "end_to_end_id": end_to_end_id, "remittance": remittance, "counterparty": counterparty}))
    logger.info("CAMT parse complete: %d transactions", len(transactions))
    return transactions


# ── Trade reconciliation dataclasses ───────────────────────────────────────────

@dataclass
class FixTransaction:
    trade_id: str
    exec_id: str
    isin: str
    side: str          # "BUY" or "SELL"
    quantity: float
    price: float
    transact_time: str
    sender: str
    currency: str
    raw_line: str

@dataclass
class CcfTransaction:
    clearing_ref: str
    exec_id: str
    isin: str
    side: str          # "BUY" or "SELL"
    quantity: float
    price: float
    settlement_date: str
    raw_line: str


FIX_SIDE_MAP = {"1": "BUY", "2": "SELL", "3": "BUY_MINUS", "4": "SELL_PLUS", "5": "SELL_SHORT", "6": "SELL_SHORT_EXEMPT"}


def parse_fix_file(path: Path) -> List[FixTransaction]:
    """Parse a pipe-delimited FIX 4.x execution report file."""
    logger.info("Parsing FIX file: %s", path)
    transactions: List[FixTransaction] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n\r")
            if not line:
                continue
            tags: Dict[str, str] = {}
            for pair in line.split("|"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    tags[k] = v
            # Only process execution reports (MsgType 35=8)
            if tags.get("35") != "8":
                continue
            trade_id = tags.get("11", "")
            exec_id = tags.get("37", "")
            isin = tags.get("48", tags.get("55", ""))
            side = FIX_SIDE_MAP.get(tags.get("54", ""), "UNKNOWN")
            try:
                quantity = float(tags.get("38", "0"))
            except ValueError:
                quantity = 0.0
            try:
                price = float(tags.get("44", "0"))
            except ValueError:
                price = 0.0
            transact_time = tags.get("52", "")
            sender = tags.get("49", "")
            # FIX doesn't carry an explicit currency in tag 15 always; default USD
            currency = tags.get("15", "USD")
            transactions.append(FixTransaction(
                trade_id=trade_id, exec_id=exec_id, isin=isin, side=side,
                quantity=quantity, price=price, transact_time=transact_time,
                sender=sender, currency=currency, raw_line=line,
            ))
    logger.info("FIX parse complete: %d transactions", len(transactions))
    return transactions


CCF_SIDE_MAP = {"B": "BUY", "S": "SELL"}


def parse_ccf_file(path: Path) -> List[CcfTransaction]:
    """Parse a fixed-width custodian/clearing file (.ccf).

    Format (72 chars): record_type(0:10) seq(10:18) order_ref(18:30)
    exec_id(30:42) isin(42:54) side(54) qty(55:63) price(63:72)
    """
    logger.info("Parsing CCF file: %s", path)
    transactions: List[CcfTransaction] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n\r")
            if len(line) < 72:
                continue
            clearing_ref = line[18:30].strip()
            exec_id = line[30:42].strip()
            isin = line[42:54].strip()
            side = CCF_SIDE_MAP.get(line[54], "UNKNOWN")
            try:
                quantity = float(line[55:63])
            except ValueError:
                quantity = 0.0
            try:
                price = float(line[63:72])
            except ValueError:
                price = 0.0
            transactions.append(CcfTransaction(
                clearing_ref=clearing_ref, exec_id=exec_id, isin=isin,
                side=side, quantity=quantity, price=price,
                settlement_date="", raw_line=line,
            ))
    logger.info("CCF parse complete: %d transactions", len(transactions))
    return transactions


def dataclass_to_dict(item):
    return asdict(item)
