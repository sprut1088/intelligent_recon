"""
Generates psr_ai_sample.txt and camt_ai_sample.xml.
Retained in the repo so we can easily regenerate or expand AI test data in the future.

AI triage scenarios:
A – Clear zone: PSR name appears verbatim in CAMT remittance. P4 fuzzy fails.
B – Clear zone: PSR invoice alias appears in CAMT remittance.
C – Maybe zone: Semantic overlap only (industry/service terms), no exact token.
D – Maybe zone: Minor amount delta (≤ 50) + semantic overlap.
E – Clear zone: +1 day date offset (tests in_transit_days).
F – Clear zone: High volume generated batch for scale testing.
"""

import os
import uuid
import random

OUT_DIR = os.path.dirname(__file__)

def psr_line(n, ref, amt_cents, direction, invoice, counterparty, date="20260610"):
    tid = f"TX-2027-{n:04d}"
    ref_f = ref.ljust(30)[:30]
    inv_f = invoice.ljust(22)[:22]
    cpty_f = counterparty.ljust(30)[:30]
    amt_f = str(amt_cents).zfill(12)
    return f"20{tid}{date}{ref_f}{amt_f}{direction}{inv_f}{cpty_f}"

def camt_entry(ntry_ref, ete_id, amt, ccy, date, dbtr_nm, ustrd):
    return (
        f'<Ntry><NtryRef>{ntry_ref}</NtryRef>'
        f'<Amt Ccy="{ccy}">{amt}</Amt>'
        f'<CdtDbtInd>CRDT</CdtDbtInd>'
        f'<BookgDt><Dt>{date}</Dt></BookgDt>'
        f'<NtryDtls><TxDtls>'
        f'<Refs><EndToEndId>{ete_id}</EndToEndId></Refs>'
        f'<RltdPties><Dbtr><Nm>{dbtr_nm}</Nm></Dbtr></RltdPties>'
        f'<RmtInf><Ustrd>{ustrd}</Ustrd></RmtInf>'
        f'</TxDtls></NtryDtls></Ntry>'
    )

def generate_samples():
    new_psr = []
    new_camt = []
    
    # --- CONFIGURATION ---
    # Adjust these numbers to change the data mix dynamically!
    COUNTS = {
        "deterministic": 40,   # Scenario 0: Auto-closed (Exact matches)
        "tier2a_fuzz": 30,     # Scenario 1: RapidFuzz suffixes/reordering
        "tier2b_embed": 30,    # Scenario 2: Semantic embedding matches
        "tier2c_clumps": 10,   # Scenario 3: LLM needles in a haystack (produces 10 PSR, 50 CAMT)
        "psr_orphans": 20,     # Scenario 4: In-transit payments (no CAMT)
        "camt_orphans": 20     # Scenario 5: Bank fees/unknowns (no PSR)
    }
    
    random.seed(42) # For reproducible "random" generation
    seq = 1

    # ── SCENARIO 0: Deterministic Matches (P1-P3)
    for i in range(COUNTS["deterministic"]):
        cpty = f"Standard Corp {seq}"
        amt = 1000 + seq * 10
        ref = f"PMT-REF-{seq:03d}"
        inv = f"INV-2027-{seq:04d}"
        new_psr.append(psr_line(seq, ref, amt*100, "CR", inv, cpty))
        ustrd = f"{ref} {inv}"
        new_camt.append(camt_entry(f"NTRY-{seq:03d}", f"TX-2027-{seq:04d}", amt, "EUR", "2026-06-10", cpty, ustrd))
        seq += 1

    # ── SCENARIO 1: Tier 2a (RapidFuzz - Prefix/Suffix & Reordering)
    suffixes = ["Ltd", "Plc", "Group", "Holdings", "Inc", "LLC"]
    for i in range(COUNTS["tier2a_fuzz"]):
        base_name = f"Acme Supply {seq}"
        psr_cpty = base_name
        camt_cpty = f"{base_name} {random.choice(suffixes)}"
        if i % 3 == 0:
            # Reordering test
            psr_cpty = f"Tech Solutions {seq}"
            camt_cpty = f"Solutions Tech {seq}"
        
        amt = 2500 + seq * 15
        ref = f"PMT-FZ-{seq:03d}"
        inv = f"INV-FZ-{seq:04d}"
        
        new_psr.append(psr_line(seq, ref, amt*100, "CR", inv, psr_cpty))
        
        # Disguise formatting to break deterministic P1/P2/P3 rules
        ustrd = f"Payment for invoice {seq:04d} from {camt_cpty}"
        new_camt.append(camt_entry(f"NTRY-FZ-{seq:03d}", f"ETE-FZ-{seq:04d}", amt, "EUR", "2026-06-10", camt_cpty, ustrd))
        seq += 1

    # ── SCENARIO 2: Tier 2b (Embeddings - Semantic matches)
    industries = [
        ("Global Logistics", "Freight Transport Partners"),
        ("Tech Cloud Systems", "Software Hosting Solutions"),
        ("National Health Services", "Medical Supply Distributors"),
        ("Agri Farms", "Organic Crop Producers")
    ]
    for i in range(COUNTS["tier2b_embed"]):
        psr_cpty_base, semantic_match = industries[i % len(industries)]
        psr_cpty = f"{psr_cpty_base} {seq}"
        camt_cpty = f"Unknown Vendor {seq}" 
        
        amt = 3500 + seq * 5
        ref = f"PMT-EM-{seq:03d}"
        inv = f"INV-EM-{seq:04d}"
        new_psr.append(psr_line(seq, ref, amt*100, "CR", inv, psr_cpty))
        
        # Use completely different semantic words to break rapidfuzz/regex, forces vectors
        ustrd = f"Settlement for {semantic_match}. Inv {seq:04d}."
        new_camt.append(camt_entry(f"NTRY-EM-{seq:03d}", f"ETE-EM-{seq:04d}", amt, "EUR", "2026-06-10", camt_cpty, ustrd))
        seq += 1

    # ── SCENARIO 3: Tier 2c (LLM - Clumps of identical amounts)
    for i in range(COUNTS["tier2c_clumps"]):
        amt = 8000 + i * 100  # Distinct amount per clump
        
        # 1. The genuine PSR
        psr_cpty = f"Complex Services {seq}"
        ref = f"PMT-LLM-{seq:03d}"
        inv = f"INV-LLM-{seq:04d}"
        new_psr.append(psr_line(seq, ref, amt*100, "CR", inv, psr_cpty))
        
        # 2. The genuine CAMT match
        ustrd_match = f"Services rendered for contract {seq:04d}. Complex Dept."
        new_camt.append(camt_entry(f"NTRY-LLM-{seq:03d}-A", f"ETE-LLM-{seq:04d}", amt, "EUR", "2026-06-10", "Complex Serv.", ustrd_match))
        
        # 3. The 4 noisy CAMT records with identical amounts
        for j in range(4):
            noise_cpty = f"Noise Vendor {seq}-{j}"
            noise_ustrd = f"Irrelevant payment {j} for unrelated batch"
            new_camt.append(camt_entry(f"NTRY-LLM-{seq:03d}-N{j}", f"ETE-NOISE-{seq}-{j}", amt, "EUR", "2026-06-10", noise_cpty, noise_ustrd))
            
        seq += 1

    # ── SCENARIO 4: PSR Orphans (In-Transit payments)
    for i in range(COUNTS["psr_orphans"]):
        amt = 9000 + seq * 10
        ref = f"PMT-ORP-{seq:03d}"
        inv = f"INV-ORP-{seq:04d}"
        new_psr.append(psr_line(seq, ref, amt*100, "CR", inv, f"Orphan PSR {seq}"))
        seq += 1

    # ── SCENARIO 5: CAMT Orphans (Bank fees / unallocated)
    for i in range(COUNTS["camt_orphans"]):
        amt = 25 + i * 5
        # No matching PSR generated for these
        new_camt.append(camt_entry(f"NTRY-FEE-{seq:03d}", f"ETE-FEE-{seq:04d}", amt, "EUR", "2026-06-10", "Bank Auth", "Monthly account fee cycle"))
        seq += 1
        
    rand_suffix = uuid.uuid4().hex[:8].upper()

    # Write PSR
    total_psr = len(new_psr)
    psr_filename = f"PSR-{total_psr}-{rand_suffix}.txt"
    psr_out = os.path.join(OUT_DIR, psr_filename)
    with open(psr_out, "w", encoding="utf-8", newline="\n") as f:
        f.write("10MAINBKGRP20260610IE12BOFI90000098765432EUR\n")
        for line in new_psr:
            f.write(line + "\n")
        f.write(f"99{total_psr:06d}\n")
    print(f"PSR: {total_psr} records written to {psr_out}")

    # Write CAMT
    total_camt = len(new_camt)
    camt_filename = f"CAMT-{total_camt}-{rand_suffix}.xml"
    camt_out = os.path.join(OUT_DIR, camt_filename)
    with open(camt_out, "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt><Stmt>\n')
        for entry in new_camt:
            f.write(entry + "\n")
        f.write('</Stmt></BkToCstmrStmt></Document>\n')
    print(f"CAMT: {total_camt} entries written to {camt_out}")

if __name__ == "__main__":
    generate_samples()
