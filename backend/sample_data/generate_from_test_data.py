import os
import csv
import uuid

OUT_DIR = os.path.dirname(__file__)

def csv_to_files():
    csv_filename = os.path.join(OUT_DIR, "reconciliation_ai_scenario-news.csv")
    
    if not os.path.exists(csv_filename):
        print(f"Error: Could not find {csv_filename}")
        return

    psr_lines = []
    camt_entries = []
    seen_psr_ids = set()

    with open(csv_filename, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Check if this row has PSR data
            if row.get('PSR_ID'):
                raw_id = row['PSR_ID']
                if raw_id not in seen_psr_ids:
                    seen_psr_ids.add(raw_id)
                    # Right pad the ID so it's exactly 12 characters!
                    tid = raw_id.ljust(12)[:12]
                    date = row['PSR_Date'].replace("-", "") # 2026-06-10 -> 20260610
                    ref_f = row['PSR_Ref'].ljust(20)[:20]
                    
                    # Multiply amount by 100 for cents representation, assuming base div 100 
                    amt_cents = int(float(row['PSR_Amount']) * 100)
                    amt_f = str(amt_cents).zfill(12)
                    
                    direction = "CR"
                    inv_f = row['PSR_Invoice'].ljust(20)[:20]
                    cpty_f = row['PSR_Counterparty'].ljust(24)[:24]
                    
                    psr_line = f"20{tid}{date}{ref_f}{amt_f}{direction}{inv_f}{cpty_f}"
                    psr_lines.append(psr_line)
                
            # Check if this row has CAMT data
            if row.get('CAMT_NtryId'):
                ntry_ref = row['CAMT_NtryId']
                ete_id = row['CAMT_EndToEndId']
                amt = row['CAMT_Amount']
                date = row['CAMT_Date']
                dbtr_nm = row['CAMT_Counterparty']
                ustrd = row['CAMT_Remittance']
                
                # XML escape some potential problematic chars
                dbtr_nm = dbtr_nm.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                ustrd = ustrd.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                
                camt_entry = (
                    f'<Ntry><NtryRef>{ntry_ref}</NtryRef>'
                    f'<Amt Ccy="EUR">{amt}</Amt>'
                    f'<CdtDbtInd>CRDT</CdtDbtInd>'
                    f'<BookgDt><Dt>{date}</Dt></BookgDt>'
                    f'<NtryDtls><TxDtls>'
                    f'<Refs><EndToEndId>{ete_id}</EndToEndId></Refs>'
                    f'<RltdPties><Dbtr><Nm>{dbtr_nm}</Nm></Dbtr></RltdPties>'
                    f'<RmtInf><Ustrd>{ustrd}</Ustrd></RmtInf>'
                    f'</TxDtls></NtryDtls></Ntry>'
                )
                camt_entries.append(camt_entry)

    # Output to files
    rand_suffix = uuid.uuid4().hex[:8].upper()
    
    # ── Write PSR File ──
    total_psr = len(psr_lines)
    psr_filename = f"PSR-{total_psr}-{rand_suffix}.txt"
    psr_out = os.path.join(OUT_DIR, psr_filename)
    with open(psr_out, "w", encoding="utf-8", newline="\n") as f:
        f.write("10MAINBKGRP20260610IE12BOFI90000098765432EUR\n") # Header
        for line in psr_lines:
            f.write(line + "\n")
        f.write(f"99{total_psr:06d}\n") # Trailer

    print(f"[{total_psr}] PSR records successfully written to {psr_filename}")

    # ── Write CAMT File ──
    total_camt = len(camt_entries)
    camt_filename = f"CAMT-{total_camt}-{rand_suffix}.xml"
    camt_out = os.path.join(OUT_DIR, camt_filename)
    with open(camt_out, "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt><Stmt>\n')
        for entry in camt_entries:
            f.write(entry + "\n")
        f.write('</Stmt></BkToCstmrStmt></Document>\n')

    print(f"[{total_camt}] CAMT entries successfully written to {camt_filename}")

if __name__ == "__main__":
    csv_to_files()
