# TASK-16 · Evidence Drawer — Stage 2a: Side-by-Side Field Diff

**Type:** Frontend  
**Branch:** `feat/evidence-drawer-ux`  
**Depends on:** TASK-14 (drawer clarity baseline), TASK-15 (raw fields available in API)  
**Blocks:** TASK-18  
**Can run in parallel with:** TASK-17  
**Effort:** ~3–4 hours

**Reference:** [docs/MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md](../MATCH_EVIDENCE_UX_IMPROVEMENT_PLAN.md) — Stage 2, item 7

---

## Background

The single highest-impact change in the entire plan. Currently the user is told a conclusion ("names don't match") but never shown the actual values. This task adds a two-column CAMT vs PSR comparison table inside the evidence drawer, with mismatched fields highlighted. It is the "show your work" moment that makes every downstream feature (overrides, learning, similar cases) meaningful.

Depends on TASK-15 confirming the raw field data is available in the API response.

---

## Acceptance Criteria

- [ ] A `FieldDiff` section appears in the evidence drawer below the existing narrative and above the factor rows
- [ ] Two columns: **PSR** (left) and **Bank (CAMT)** (right), labelled clearly
- [ ] Rows cover all comparable fields: Amount, Currency, Direction, Date, Reference/Remittance, Counterparty, Invoice
- [ ] Rows where PSR ≠ CAMT value are highlighted (amber background or coloured left border)
- [ ] Rows where values match are styled neutrally (no noise)
- [ ] Empty/null values displayed as `—` (not `undefined`, `null`, or blank)
- [ ] The diff table is read-only — no inputs
- [ ] On mobile / narrow drawer, the two columns stack gracefully (no horizontal overflow)

---

## Implementation Notes

### Component structure

```jsx
function FieldDiff({ item }) {
  const rows = [
    { label: 'Amount',       psr: item.psr_amount,         camt: item.bank_amount       },
    { label: 'Currency',     psr: item.psr_currency,       camt: item.camt_currency     },
    { label: 'Direction',    psr: item.psr_direction,      camt: item.camt_direction    },
    { label: 'Date',         psr: item.psr_execution_date, camt: item.camt_booking_date },
    { label: 'Reference',    psr: item.psr_reference,      camt: item.camt_pmt_ref      },
    { label: 'Counterparty', psr: item.psr_counterparty,   camt: item.camt_counterparty },
    { label: 'Invoice',      psr: item.psr_invoice,        camt: item.camt_invoice      },
    { label: 'Remittance',   psr: null,                    camt: item.camt_remittance   },
  ];

  const fmt = (v) => (v == null || v === '') ? '—' : v;
  const mismatch = (a, b) => a != null && b != null && String(a).trim() !== String(b).trim();

  return (
    <div className="field-diff">
      <div className="field-diff-header">
        <span>PSR (Internal)</span>
        <span>Bank (CAMT)</span>
      </div>
      {rows.map(({ label, psr, camt }) => (
        <div key={label} className={`field-diff-row ${mismatch(psr, camt) ? 'mismatch' : ''}`}>
          <span className="field-label">{label}</span>
          <span className="field-val">{fmt(psr)}</span>
          <span className="field-val">{fmt(camt)}</span>
        </div>
      ))}
    </div>
  );
}
```

### CSS (`App.css`)

```css
.field-diff { border: 1px solid #e5e7eb; border-radius: 6px; overflow: hidden; margin-bottom: 16px; }
.field-diff-header { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 6px 12px; background: #f9fafb; font-size: 0.75rem; font-weight: 600; color: #6b7280; }
.field-diff-row { display: grid; grid-template-columns: 120px 1fr 1fr; gap: 8px; padding: 5px 12px; border-top: 1px solid #f3f4f6; font-size: 0.85rem; }
.field-diff-row.mismatch { background: #fffbeb; border-left: 3px solid #f59e0b; }
.field-label { color: #6b7280; font-size: 0.8rem; }
.field-val { color: #111827; word-break: break-word; }
```

### Data sourcing

If TASK-15 confirms the detail endpoint `GET /api/reconcile/results/{case_id}` is needed, lazy-load it when the drawer opens: fetch on `item` change, show a skeleton while loading.

If fields are already present on the list item, no extra fetch is required.
