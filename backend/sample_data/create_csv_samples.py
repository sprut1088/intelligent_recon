import csv
import os
import random

OUT_DIR = os.path.dirname(__file__)

def generate_csv_samples():
    csv_filename = os.path.join(OUT_DIR, "reconciliation_ai_scenarios.csv")
    
    # Configuration
    COUNTS = {
        "direct_match": 80,
        "partial_match": 60,
        "ai_match_clear": 50,
        "ai_match_maybe": 50,
        "no_match_psr": 30,
        "no_match_camt": 30
    }
    
    random.seed(42)
    seq = 1
    
    with open(csv_filename, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "PSR_ID", "PSR_Ref", "PSR_Amount", "PSR_Invoice", "PSR_Counterparty", "PSR_Date",
            "CAMT_NtryId", "CAMT_EndToEndId", "CAMT_Amount", "CAMT_Counterparty", "CAMT_Remittance", "CAMT_Date",
            "Scenario", "Expected_Match_Type"
        ])
        
        # 1. Direct Match (Exact matches for P1, P2, P3)
        for _ in range(COUNTS["direct_match"]):
            amt = 1000 + seq * 10
            psr_id = f"TX-2027-{seq:04d}"
            ref = f"PMT-REF-{seq:03d}"
            inv = f"INV-2027-{seq:04d}"
            cpty = f"Standard Corp {seq}"
            date = "2026-06-10"
            
            camt_ntry = f"NTRY-{seq:03d}"
            camt_ete = psr_id # Matches exactly
            camt_amt = amt
            camt_cpty = cpty
            camt_remit = f"{ref} {inv}"
            
            writer.writerow([
                psr_id, ref, amt, inv, cpty, date,
                camt_ntry, camt_ete, camt_amt, camt_cpty, camt_remit, date,
                "Direct Match - Exact ETE ID", "Auto-Close"
            ])
            seq += 1
            
        # 2. Partial Match (P4 Fuzzy / Tier 2a RapidFuzz)
        suffixes = ["Ltd", "Plc", "Group", "Holdings", "Inc", "LLC"]
        for i in range(COUNTS["partial_match"]):
            amt = 2000 + seq * 15
            psr_id = f"TX-2027-{seq:04d}"
            ref = f"PMT-FZ-{seq:03d}"
            inv = f"INV-FZ-{seq:04d}"
            
            base_name = f"Acme Supply {seq}"
            psr_cpty = base_name
            camt_cpty = f"{base_name} {random.choice(suffixes)}"
            if i % 2 == 0:
                psr_cpty = f"Tech Solutions {seq}"
                camt_cpty = f"Solutions Tech {seq}"
            
            date = "2026-06-10"
            
            camt_ntry = f"NTRY-FZ-{seq:03d}"
            camt_ete = f"ETE-FZ-{seq:04d}" # Dosen't match
            camt_amt = amt
            camt_remit = f"Payment for invoice {seq:04d} from {camt_cpty}"
            
            writer.writerow([
                psr_id, ref, amt, inv, psr_cpty, date,
                camt_ntry, camt_ete, camt_amt, camt_cpty, camt_remit, date,
                "Partial Match - Entity suffix / word order", "Suggested Match/Fuzzy"
            ])
            seq += 1

        # 3. AI Match Clear (Tier 2b Embeddings)
        industries = [
            ("Global Logistics", "Freight Transport Partners"),
            ("Tech Cloud Systems", "Software Hosting Solutions"),
            ("National Health Services", "Medical Supply Distributors")
        ]
        for i in range(COUNTS["ai_match_clear"]):
            amt = 3000 + seq * 20
            psr_id = f"TX-2027-{seq:04d}"
            ref = f"PMT-EM-{seq:03d}"
            inv = f"INV-EM-{seq:04d}"
            
            psr_cpty_base, semantic_match = industries[i % len(industries)]
            psr_cpty = f"{psr_cpty_base} {seq}"
            camt_cpty = f"Unknown Vendor {seq}" 
            date = "2026-06-10"
            
            camt_ntry = f"NTRY-EM-{seq:03d}"
            camt_ete = f"ETE-EM-{seq:04d}"
            camt_amt = amt
            camt_remit = f"Settlement for {semantic_match}. Reference {seq:04d}."
            
            writer.writerow([
                psr_id, ref, amt, inv, psr_cpty, date,
                camt_ntry, camt_ete, camt_amt, camt_cpty, camt_remit, date,
                "AI Match - Semantic similarity", "AI-Assisted Suggested Match"
            ])
            seq += 1

        # 4. AI Match Maybe (Tier 2c LLM with noisy candidates)
        # Note: We represent just the pair that SHOULD match here, we can generate the noise in the XML later.
        for i in range(COUNTS["ai_match_maybe"]):
            amt = 4000 + seq * 5
            # Add minor delta to amount
            camt_amt = amt + random.randint(-15, 15)
            
            psr_id = f"TX-2027-{seq:04d}"
            ref = f"PMT-LLM-{seq:03d}"
            inv = f"INV-LLM-{seq:04d}"
            psr_cpty = f"Complex Services {seq}"
            date = "2026-06-10"
            
            camt_ntry = f"NTRY-LLM-{seq:03d}"
            camt_ete = f"ETE-LLM-{seq:04d}"
            camt_cpty = "Complex Serv."
            camt_remit = f"Services rendered for contract {seq:04d}."
            
            writer.writerow([
                psr_id, ref, amt, inv, psr_cpty, date,
                camt_ntry, camt_ete, camt_amt, camt_cpty, camt_remit, date,
                "AI Match - Minor amount variance & Haystack", "AI - Adjudication Required"
            ])
            seq += 1

        # 5. No Match - PSR Orphan (In-Transit)
        for i in range(COUNTS["no_match_psr"]):
            amt = 5000 + seq * 10
            psr_id = f"TX-2027-{seq:04d}"
            ref = f"PMT-ORP-{seq:03d}"
            inv = f"INV-ORP-{seq:04d}"
            psr_cpty = f"Pending Payment {seq}"
            date = "2026-06-10"
            
            writer.writerow([
                psr_id, ref, amt, inv, psr_cpty, date,
                "", "", "", "", "", "",
                "No Match - In Transit", "Uncleared/In-Transit"
            ])
            seq += 1

        # 6. No Match - CAMT Orphan (Bank Fee etc.)
        for i in range(COUNTS["no_match_camt"]):
            amt = 50 + seq * 2
            camt_ntry = f"NTRY-FEE-{seq:03d}"
            camt_ete = f"ETE-FEE-{seq:04d}"
            camt_cpty = "Bank Auth"
            camt_remit = f"Monthly account cycle fee {seq}"
            date = "2026-06-10"
            
            writer.writerow([
                "", "", "", "", "", "",
                camt_ntry, camt_ete, amt, camt_cpty, camt_remit, date,
                "No Match - Bank Only Item", "Bank-only Item/Exception"
            ])
            seq += 1

    print(f"CSV generated with 300 entries at {csv_filename}")

if __name__ == "__main__":
    generate_csv_samples()
