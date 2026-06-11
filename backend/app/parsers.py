from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional
import re
import xml.etree.ElementTree as ET
from .config import settings

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
        end_to_end_id = _first_text_by_local_name(entry, "EndToEndId")
        counterparty = _first_text_by_local_name(entry, "Nm")
        remittance = " ".join(clean_text(item.text) for item in _children_by_local_name(entry, "Ustrd") if item.text)
        pmt_ref = extract_pmt_ref(remittance)
        invoice = extract_invoice(remittance)
        ntry_ref = _first_text_by_local_name(entry, "NtryRef")
        ntry_id = ntry_ref or f"NTRY-{idx}"
        camt_id = end_to_end_id or ntry_id
        transactions.append(CamtTransaction(ntry_id, camt_id, end_to_end_id, amount, direction, booking_date, booking_date, currency, remittance, counterparty, pmt_ref, invoice, {"ntry_id": ntry_id, "camt_id": camt_id, "end_to_end_id": end_to_end_id, "remittance": remittance, "counterparty": counterparty}))
    return transactions

def dataclass_to_dict(item):
    return asdict(item)
