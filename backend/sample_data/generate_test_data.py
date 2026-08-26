"""
Generate test-data.csv for reconciliation engine testing.
300 records across 6 scenarios.  Run from any directory; output lands next to this script.
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
random.seed(SEED)

OUT_PATH = Path(__file__).parent / "test-data.csv"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _date(start="2024-01-01", end="2025-12-31") -> str:
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    return (s + timedelta(days=random.randint(0, (e - s).days))).strftime("%Y-%m-%d")


def _amount(lo=200.0, hi=75_000.0) -> float:
    return round(random.uniform(lo, hi), 2)


class _Seq:
    """Simple auto-incrementing ID sequences."""
    def __init__(self):
        self._p = 1
        self._c = 1
        self._e = 1
        self._i = 1

    def psr(self):    v = f"PSR-{self._p:05d}";  self._p += 1;  return v
    def camt(self):   v = f"CAMT-{self._c:05d}"; self._c += 1;  return v
    def e2e(self):    v = f"E2E-{self._e:08d}";  self._e += 1;  return v
    def inv(self):    v = f"INV-{self._i:06d}";  self._i += 1;  return v


seq = _Seq()

COMPANIES = [
    "Acme Supply", "Global Logistics", "TechParts Inc", "Blue Ocean Trading",
    "Summit Finance", "Delta Freight", "Prime Vendors", "Horizon Imports",
    "Vertex Solutions", "Cascade Systems", "Meridian Group", "Apex Distributors",
    "Pinnacle Exports", "Stellar Commerce", "Nexus Trading", "Orbit Suppliers",
    "Quantum Goods", "Helix Partners", "Matrix Imports", "Zenith Wholesale",
    "Ironclad Supplies", "SkyBridge Cargo", "Pacific Rim Traders", "Atlas Corp",
    "Vanguard Freight", "Solaris Exports", "Beacon Industrial", "CrossRoads Logistics",
]

FUZZY_SUFFIXES = [" Ltd", " Limited", " Corp", " LLC", " Co.", " GmbH", " PLC", " SA"]

# Word-swap variants (reverse first/last word for reorder test)
def _fuzzy_company(base: str) -> str:
    mode = random.random()
    if mode < 0.5:
        return base + random.choice(FUZZY_SUFFIXES)
    # reorder words
    words = base.split()
    if len(words) > 1:
        words = words[1:] + words[:1]
    return " ".join(words)


# Semantic pairs: PSR counterparty → CAMT remittance text (no invoice patterns)
SEMANTIC_PAIRS = [
    ("Global Logistics",    "Settlement for Freight Transport Partners"),
    ("TechParts Inc",       "Payment for Electronic Components Delivery"),
    ("Acme Supply",         "Invoice Settlement - Industrial Materials Batch"),
    ("Blue Ocean Trading",  "Maritime Commerce Transaction Clearance"),
    ("Summit Finance",      "Corporate Financial Services Remittance"),
    ("Delta Freight",       "Cargo Transportation Cost Recovery"),
    ("Prime Vendors",       "Supplier Disbursement - Premium Goods"),
    ("Horizon Imports",     "International Trade Settlement Instruction"),
    ("Vertex Solutions",    "Software Services Payment Clearance"),
    ("Cascade Systems",     "Technology Infrastructure Cost Remittance"),
    ("Meridian Group",      "Cross-Border Commerce Settlement Advice"),
    ("Apex Distributors",   "Wholesale Distribution Payment Advice"),
    ("Pinnacle Exports",    "Export Revenue Clearance Instruction"),
    ("Stellar Commerce",    "Commercial Transaction Settlement Order"),
    ("Nexus Trading",       "Intercompany Trade Netting Confirmation"),
    ("Orbit Suppliers",     "Raw Material Procurement Cost Settlement"),
    ("Quantum Goods",       "Goods Delivery Charge Reconciliation"),
    ("Helix Partners",      "Partnership Disbursement - Operations"),
    ("Matrix Imports",      "Import Duty and Freight Cost Recovery"),
    ("Zenith Wholesale",    "Bulk Purchase Settlement Notification"),
    ("Ironclad Supplies",   "Industrial Equipment Supply Settlement"),
    ("SkyBridge Cargo",     "Air Freight Forwarding Cost Recovery"),
    ("Pacific Rim Traders", "Asia-Pacific Commerce Settlement Advice"),
    ("Atlas Corp",          "Corporate Operating Expense Disbursement"),
    ("Vanguard Freight",    "Logistics Network Cost Settlement"),
]

NOISE_REMITTANCES = [
    "Monthly Account Maintenance Fee",
    "SWIFT Interbank Messaging Charge",
    "Standing Order - Office Utilities",
    "Subscription Renewal - SaaS Platform",
    "FX Conversion Settlement",
    "Card Processing Fee",
    "Insurance Premium - Commercial Property",
    "Lease Agreement Instalment",
    "Consulting Retainer - Q4",
    "Regulatory Compliance Levy",
    "Wire Transfer Processing Fee",
    "Trade Finance Guarantee Charge",
    "Payroll Taxes - Quarterly Remittance",
    "Customs Duty Advance Payment",
    "IT Infrastructure Hosting Cost",
    "Pension Contribution - Employer Share",
    "Legal Services Retainer Fee",
    "Advertising Campaign Settlement",
    "R&D Grant Repayment Schedule",
    "Directors Loan Repayment",
]

BANK_FEE_LABELS = [
    "Monthly Account Fee",
    "Wire Transfer Charge",
    "FX Conversion Fee",
    "Overdraft Interest",
    "Card Processing Fee",
    "SWIFT Message Fee",
    "Safe Custody Charge",
    "Letter of Credit Fee",
    "Trade Finance Charge",
    "Account Maintenance Fee",
    "Inward Collection Fee",
    "Outward Collection Fee",
    "Cash Management Service Fee",
    "Foreign Currency Handling Charge",
]

FIELDNAMES = [
    "PSR_ID", "PSR_Ref", "PSR_Amount", "PSR_Invoice", "PSR_Counterparty", "PSR_Date",
    "CAMT_NtryId", "CAMT_EndToEndId", "CAMT_Amount", "CAMT_Counterparty",
    "CAMT_Remittance", "CAMT_Date",
    "Scenario", "Expected_Match_Type",
]

rows: list[dict] = []

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1 – Direct Match (80 records)
# ─────────────────────────────────────────────────────────────────────────────
for _ in range(80):
    e2e     = seq.e2e()
    inv     = seq.inv()
    amt     = _amount()
    dt      = _date()
    company = random.choice(COMPANIES)

    rows.append({
        "PSR_ID":           seq.psr(),
        "PSR_Ref":          e2e,
        "PSR_Amount":       amt,
        "PSR_Invoice":      inv,
        "PSR_Counterparty": company,
        "PSR_Date":         dt,
        "CAMT_NtryId":      seq.camt(),
        "CAMT_EndToEndId":  e2e,          # exact match
        "CAMT_Amount":      amt,           # exact match
        "CAMT_Counterparty": company,
        "CAMT_Remittance":  inv,           # exact invoice reference
        "CAMT_Date":        dt,
        "Scenario":         "Direct Match",
        "Expected_Match_Type": "DIRECT",
    })

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2 – Partial Match / Fuzzy (60 records)
# ─────────────────────────────────────────────────────────────────────────────
for _ in range(60):
    inv          = seq.inv()
    amt          = _amount()
    dt           = _date()
    company_base = random.choice(COMPANIES)
    psr_e2e      = seq.e2e()
    camt_e2e     = seq.e2e()            # different E2E IDs

    rows.append({
        "PSR_ID":           seq.psr(),
        "PSR_Ref":          psr_e2e,
        "PSR_Amount":       amt,
        "PSR_Invoice":      inv,
        "PSR_Counterparty": company_base,
        "PSR_Date":         dt,
        "CAMT_NtryId":      seq.camt(),
        "CAMT_EndToEndId":  camt_e2e,   # mismatch
        "CAMT_Amount":      amt,         # exact amount
        "CAMT_Counterparty": _fuzzy_company(company_base),   # slight name drift
        "CAMT_Remittance":  inv,
        "CAMT_Date":        dt,
        "Scenario":         "Partial Match - Fuzzy",
        "Expected_Match_Type": "FUZZY",
    })

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3 – AI Match – Semantic / Embeddings (50 records)
# ─────────────────────────────────────────────────────────────────────────────
for i in range(50):
    amt  = _amount()
    dt   = _date()
    pair = SEMANTIC_PAIRS[i % len(SEMANTIC_PAIRS)]

    # CAMT E2E is either blank or an opaque bank reference (no INV- pattern)
    if random.random() < 0.6:
        camt_e2e = ""
    else:
        camt_e2e = f"BNK-{random.randint(10000000, 99999999)}"

    rows.append({
        "PSR_ID":           seq.psr(),
        "PSR_Ref":          seq.e2e(),
        "PSR_Amount":       amt,
        "PSR_Invoice":      seq.inv(),
        "PSR_Counterparty": pair[0],
        "PSR_Date":         dt,
        "CAMT_NtryId":      seq.camt(),
        "CAMT_EndToEndId":  camt_e2e,    # missing/disguised
        "CAMT_Amount":      amt,
        "CAMT_Counterparty": "",          # no counterparty name in CAMT
        "CAMT_Remittance":  pair[1],      # semantic equivalent only
        "CAMT_Date":        dt,
        "Scenario":         "AI Match - Semantic",
        "Expected_Match_Type": "AI_SEMANTIC",
    })

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4 – AI Match – LLM Adjudication (50 records = 10 groups × 5)
# Each group: 1 true match row + 4 noise CAMT rows sharing the same PSR.
# ─────────────────────────────────────────────────────────────────────────────
for g in range(10):
    pair    = SEMANTIC_PAIRS[g % len(SEMANTIC_PAIRS)]
    psr_amt = _amount()
    dt      = _date()
    psr_id  = seq.psr()
    psr_e2e = seq.e2e()
    psr_inv = seq.inv()

    variance    = round(random.uniform(-15.0, 15.0), 2)
    camt_amount = round(psr_amt + variance, 2)

    # — True match row —
    rows.append({
        "PSR_ID":           psr_id,
        "PSR_Ref":          psr_e2e,
        "PSR_Amount":       psr_amt,
        "PSR_Invoice":      psr_inv,
        "PSR_Counterparty": pair[0],
        "PSR_Date":         dt,
        "CAMT_NtryId":      seq.camt(),
        "CAMT_EndToEndId":  "",
        "CAMT_Amount":      camt_amount,   # ±$15 variance
        "CAMT_Counterparty": "",
        "CAMT_Remittance":  pair[1],       # semantically related
        "CAMT_Date":        dt,
        "Scenario":         "AI Match - LLM",
        "Expected_Match_Type": "AI_LLM",
    })

    # — 4 noise rows (same PSR, different semantically-unrelated CAMT) —
    noise_sample = random.sample(NOISE_REMITTANCES, 4)
    for noise_rem in noise_sample:
        rows.append({
            "PSR_ID":           psr_id,
            "PSR_Ref":          psr_e2e,
            "PSR_Amount":       psr_amt,
            "PSR_Invoice":      psr_inv,
            "PSR_Counterparty": pair[0],
            "PSR_Date":         dt,
            "CAMT_NtryId":      seq.camt(),
            "CAMT_EndToEndId":  "",
            "CAMT_Amount":      camt_amount,  # identically-priced as the true match
            "CAMT_Counterparty": "",
            "CAMT_Remittance":  noise_rem,    # unrelated remittance text
            "CAMT_Date":        dt,
            "Scenario":         "AI Match - LLM Noise",
            "Expected_Match_Type": "AI_LLM_NOISE",
        })

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 5 – No Match – In-Transit (30 records)
# Pure PSR orphans; all CAMT columns blank.
# ─────────────────────────────────────────────────────────────────────────────
for _ in range(30):
    rows.append({
        "PSR_ID":           seq.psr(),
        "PSR_Ref":          seq.e2e(),
        "PSR_Amount":       _amount(),
        "PSR_Invoice":      seq.inv(),
        "PSR_Counterparty": random.choice(COMPANIES),
        "PSR_Date":         _date(),
        "CAMT_NtryId":      "",
        "CAMT_EndToEndId":  "",
        "CAMT_Amount":      "",
        "CAMT_Counterparty": "",
        "CAMT_Remittance":  "",
        "CAMT_Date":        "",
        "Scenario":         "No Match - In-Transit",
        "Expected_Match_Type": "UNMATCHED_PSR",
    })

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 6 – No Match – Bank Only Item (30 records)
# Pure CAMT orphans; all PSR columns blank.
# ─────────────────────────────────────────────────────────────────────────────
for _ in range(30):
    rows.append({
        "PSR_ID":           "",
        "PSR_Ref":          "",
        "PSR_Amount":       "",
        "PSR_Invoice":      "",
        "PSR_Counterparty": "",
        "PSR_Date":         "",
        "CAMT_NtryId":      seq.camt(),
        "CAMT_EndToEndId":  seq.e2e(),
        "CAMT_Amount":      round(random.uniform(5.0, 750.0), 2),
        "CAMT_Counterparty": "Bank of Record",
        "CAMT_Remittance":  random.choice(BANK_FEE_LABELS),
        "CAMT_Date":        _date(),
        "Scenario":         "No Match - Bank Only Item",
        "Expected_Match_Type": "UNMATCHED_CAMT",
    })

# ─────────────────────────────────────────────────────────────────────────────
# Write
# ─────────────────────────────────────────────────────────────────────────────
with open(OUT_PATH, "w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
    writer.writeheader()
    writer.writerows(rows)

# Summary
from collections import Counter
counts = Counter(r["Scenario"] for r in rows)
print(f"\nWrote {len(rows)} rows → {OUT_PATH}\n")
print(f"{'Scenario':<35} {'Count':>6}")
print("-" * 43)
for scenario in [
    "Direct Match",
    "Partial Match - Fuzzy",
    "AI Match - Semantic",
    "AI Match - LLM",
    "AI Match - LLM Noise",
    "No Match - In-Transit",
    "No Match - Bank Only Item",
]:
    print(f"{scenario:<35} {counts[scenario]:>6}")
print("-" * 43)
print(f"{'TOTAL':<35} {len(rows):>6}")
