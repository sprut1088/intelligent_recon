import { useEffect, useMemo, useState } from 'react';
import { api } from './api/client';

const tabs = [
  ['workspace', 'Control Room'],
  ['intake', 'Data Intake'],
  ['dataprep', 'Data Prep Studio'],
  ['matching', 'Matching Studio'],
  ['results', 'Results Workbench'],
  ['exceptions', 'Exceptions'],
  ['dashboards', 'Dashboards'],
  ['learning', 'Learning Lab'],
  ['assistant', 'Recon Copilot'],
  ['governance', 'Governance'],
];

const money = (value) =>
  value === null || value === undefined || Number.isNaN(Number(value))
    ? '-'
    : new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 }).format(Number(value));

const pct = (value) => `${Number(value || 0).toFixed(Number(value || 0) % 1 === 0 ? 0 : 1)}%`;

function classForStatus(value = '') {
  const v = String(value).toLowerCase();
  if (v.startsWith('ai-assisted')) return 'ai';
  if (v.startsWith('ai -') || v.startsWith('ai –')) return 'ai-maybe';
  if (v.includes('matched') || v.includes('active') || v.includes('processed') || v.includes('ok') || v.includes('complete')) return 'success';
  if (v.includes('variance') || v.includes('ledger') || v.includes('warning') || v.includes('review') || v.includes('candidate')) return 'warning';
  if (v.includes('transit') || v.includes('new') || v.includes('manual')) return 'info';
  if (v.includes('error') || v.includes('high') || v.includes('failed')) return 'danger';
  return 'neutral';
}

function Tag({ children, tone = 'neutral' }) {
  return <span className={`tag ${tone}`}>{children}</span>;
}

function Metric({ label, value, hint, tone = 'neutral' }) {
  return (
    <div className={`metric ${tone}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-hint">{hint}</div>
    </div>
  );
}

function Panel({ title, subtitle, children, actions, className = '' }) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <div className="panel-head">
          <div>
            {title && <h3>{title}</h3>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

function BarList({ rows = [], labelKey = 'label', valueKey = 'value', empty = 'No data' }) {
  const max = Math.max(...rows.map((r) => Number(r[valueKey] || 0)), 1);
  if (!rows.length) return <p className="empty small">{empty}</p>;
  return (
    <div className="bar-list">
      {rows.map((r, idx) => {
        const value = Number(r[valueKey] || 0);
        return (
          <div className="bar-row" key={`${r[labelKey]}-${idx}`}>
            <div className="bar-label">{r[labelKey] || 'Unclassified'}</div>
            <div className="bar-track"><span style={{ width: `${Math.max(4, (value / max) * 100)}%` }} /></div>
            <div className="bar-value">{value}</div>
          </div>
        );
      })}
    </div>
  );
}

function Stepper({ lifecycle = [] }) {
  return (
    <div className="stepper">
      {lifecycle.map((s, idx) => (
        <div className={`step ${s.state}`} key={s.step}>
          <div className="step-index">{idx + 1}</div>
          <strong>{s.step}</strong>
          <span>{s.detail}</span>
        </div>
      ))}
    </div>
  );
}

function Workspace({ workspace, summary, onLoad, onRun, onSnapshot, onExport, loading }) {
  const caps = workspace?.capabilities || [];
  const lifecycle = workspace?.lifecycle || [];
  const insights = workspace?.agent_insights || [];
  const process = workspace?.process || {};

  return (
    <section className="screen">
      <div className="hero-card">
        <div className="hero-copy">
          <div className="eyebrow">Intelligent Recon Engine · Prototype</div>
          <h1>{process.name || 'Cash Account Real-Time Reconciliation'}</h1>
          <p>
            A distinct operations cockpit covering intake, data prep, no-code matching, exception workflow, dashboards,
            audit and human-in-the-loop learning for PSR versus CAMT.053 reconciliation.
          </p>
          <div className="hero-meta">
            <Tag tone="success">{process.status || 'Ready'}</Tag>
            <Tag tone="info">{process.environment || 'Prototype / UAT'}</Tag>
            <Tag tone="neutral">Owner: {process.owner || 'Recon Ops'}</Tag>
          </div>
        </div>
        <div className="hero-buttons">
          <button className="btn secondary" onClick={onLoad} disabled={loading}>Load sample PSR/CAMT</button>
          <button className="btn primary" onClick={onRun} disabled={loading}>Run reconciliation</button>
          <button className="btn ghost" onClick={onSnapshot} disabled={loading}>Create snapshot</button>
          <button className="btn ghost" onClick={onExport}>Export CSV</button>
        </div>
      </div>

      <div className="metric-grid six">
        <Metric label="PSR records" value={summary?.psr_records || summary?.raw?.psr_count || 0} hint="Internal settlement rows" tone="info" />
        <Metric label="CAMT entries" value={summary?.camt_entries || summary?.raw?.camt_count || 0} hint="Bank statement entries" tone="info" />
        <Metric label="Auto-closed" value={summary?.auto_closed || 0} hint={`${pct(summary?.match_rate)} match rate`} tone="success" />
        <Metric label="Open exceptions" value={summary?.exceptions || 0} hint="Manual, ledger and in-transit" tone="warning" />
        <Metric label="Learning signals" value={summary?.manual_resolutions || 0} hint="Captured analyst decisions" tone="neutral" />
        <Metric label="Variance exposure" value={money(summary?.variance_total || 0)} hint="Internal less bank total" tone="danger" />
      </div>

      <div className="grid two">
        <Panel title="Process lifecycle" subtitle="End-to-end workflow from raw feed to downstream-ready output">
          <Stepper lifecycle={lifecycle} />
        </Panel>
        <Panel title="AI operator insights" subtitle="Prototype differentiators beyond static rule configuration">
          <div className="insight-list">
            {insights.map((i) => <div className="insight" key={i}><span>AI</span><p>{i}</p></div>)}
          </div>
        </Panel>
      </div>

      <Panel title="Capability matrix" subtitle="End-to-end operational coverage from ingestion to exception resolution and pattern learning">
        <div className="capability-grid">
          {caps.map((c) => (
            <div className="capability" key={c.name}>
              <Tag tone={classForStatus(c.status)}>{c.status}</Tag>
              <strong>{c.name}</strong>
              <p>{c.detail}</p>
            </div>
          ))}
        </div>
      </Panel>
    </section>
  );
}

function DataIntake({ batches, submissions, selectedBatchId, setSelectedBatchId, quality, onUpload, onValidate, onRunBatch, loading }) {
  const [psrFile, setPsrFile] = useState(null);
  const [camtFile, setCamtFile] = useState(null);
  const [batchName, setBatchName] = useState('Treasury cash daily upload');
  const selectedBatch = (batches.items || []).find((b) => b.batch_id === selectedBatchId) || (batches.items || [])[0];
  const batchId = selectedBatch?.batch_id || selectedBatchId || '';
  const issues = quality?.issues || [];
  const files = submissions?.items || [];

  return (
    <section className="screen">
      <div className="screen-title">
        <div>
          <div className="eyebrow">Data intake</div>
          <h1>Submissions, snapshots and feed readiness</h1>
          <p>Upload PSR and CAMT.053 feeds, inspect processing state, validate quality, and trigger reconciliation snapshots.</p>
        </div>
      </div>

      <div className="grid two intake-grid">
        <Panel title="Create upload batch" subtitle="Manual upload for the prototype; the same API can be connected to SFTP or bank feed later.">
          <div className="form-grid">
            <label>Batch name</label>
            <input value={batchName} onChange={(e) => setBatchName(e.target.value)} />
            <label>PSR payment settlement file</label>
            <input type="file" accept=".txt,.dat,.psr,text/plain" onChange={(e) => setPsrFile(e.target.files?.[0] || null)} />
            <button className="btn secondary" disabled={!psrFile || loading} onClick={() => onUpload('PSR', psrFile, '', batchName)}>Upload PSR to new batch</button>
            <label>Existing batch</label>
            <select value={batchId} onChange={(e) => setSelectedBatchId(e.target.value)}>
              <option value="">Select batch</option>
              {(batches.items || []).map((b) => <option key={b.batch_id} value={b.batch_id}>{b.batch_name} · {b.status}</option>)}
            </select>
            <label>CAMT.053 bank statement</label>
            <input type="file" accept=".xml,application/xml,text/xml" onChange={(e) => setCamtFile(e.target.files?.[0] || null)} />
            <button className="btn secondary" disabled={!camtFile || !batchId || loading} onClick={() => onUpload('CAMT', camtFile, batchId, '')}>Upload CAMT to selected batch</button>
          </div>
        </Panel>

        <Panel title="Selected batch control" subtitle="Data quality validation should run before auto-close decisions are trusted.">
          {selectedBatch ? (
            <>
              <dl className="kv">
                <dt>Batch</dt><dd>{selectedBatch.batch_name}</dd>
                <dt>Status</dt><dd><Tag tone={classForStatus(selectedBatch.status)}>{selectedBatch.status}</Tag></dd>
                <dt>PSR file</dt><dd>{selectedBatch.psr_file_id || '-'}</dd>
                <dt>CAMT file</dt><dd>{selectedBatch.camt_file_id || '-'}</dd>
              </dl>
              <div className="button-row">
                <button className="btn secondary" disabled={!batchId || loading} onClick={() => onValidate(batchId)}>Validate quality</button>
                <button className="btn primary" disabled={!batchId || loading} onClick={() => onRunBatch(batchId)}>Run uploaded batch</button>
              </div>
            </>
          ) : <p className="empty small">Upload a PSR file to create a batch.</p>}
        </Panel>
      </div>

      <Panel title="Submissions queue" subtitle="Equivalent operational view for uploaded files, processing status, document state and usage.">
        <div className="table-wrap">
          <table>
            <thead><tr><th>File</th><th>Type</th><th>Batch</th><th>Upload status</th><th>Document status</th><th>Used in</th><th>Profile</th></tr></thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.file_id}>
                  <td><strong>{f.original_filename}</strong><br/><span className="muted">{f.file_id}</span></td>
                  <td><Tag tone="info">{f.file_type}</Tag></td>
                  <td>{f.batch_name || f.batch_id}</td>
                  <td><Tag tone={classForStatus(f.status)}>{f.status}</Tag></td>
                  <td><Tag tone={classForStatus(f.document_status)}>{f.document_status}</Tag></td>
                  <td>{f.used_in || '-'}</td>
                  <td><code>{JSON.stringify(f.profile || {})}</code></td>
                </tr>
              ))}
              {!files.length && <tr><td colSpan="7" className="empty">No submissions yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Data quality report" subtitle="Header, trailer, duplicates, scaling, missing values and cross-feed controls.">
        {quality ? (
          <>
            <div className="metric-grid three">
              <Metric label="Errors" value={quality.error_count || 0} hint="Stop production auto-close" tone="danger" />
              <Metric label="Warnings" value={quality.warning_count || 0} hint="Review before pilot" tone="warning" />
              <Metric label="Files checked" value={(quality.files || []).length} hint="PSR and CAMT expected" tone="info" />
            </div>
            <div className="table-wrap compact">
              <table>
                <thead><tr><th>Severity</th><th>Issue</th><th>Record</th><th>Message</th></tr></thead>
                <tbody>
                  {issues.map((i) => <tr key={i.issue_id}><td><Tag tone={classForStatus(i.severity)}>{i.severity}</Tag></td><td>{i.issue_code}</td><td>{i.record_id || '-'}</td><td>{i.message}</td></tr>)}
                  {!issues.length && <tr><td colSpan="4" className="empty">No quality issues found.</td></tr>}
                </tbody>
              </table>
            </div>
          </>
        ) : <p className="empty small">Run validation to see data quality results.</p>}
      </Panel>
    </section>
  );
}

function DataPrep({ preview, predictions }) {
  const canonical = preview?.canonical_fields || [];
  const psrRows = preview?.psr?.rows || [];
  const camtRows = preview?.camt?.rows || [];
  const predictionRows = predictions?.predictions || [];

  return (
    <section className="screen">
      <div className="screen-title">
        <div>
          <div className="eyebrow">Data prep studio</div>
          <h1>Map, transform and normalise operational data</h1>
          <p>Business-readable mapping and cleansing layer for PSR fixed-width and CAMT.053 XML before reconciliation runs.</p>
        </div>
      </div>

      <div className="grid two">
        <Panel title="Canonical output model" subtitle="Consolidated field set used by the match engine">
          <div className="field-grid">
            {canonical.map((f) => (
              <div className="field-card" key={f.field}>
                <Tag tone="neutral">{f.type}</Tag>
                <strong>{f.label}</strong>
                <span>PSR: {f.psr}</span>
                <span>CAMT: {f.camt}</span>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="AI field prediction" subtitle="Suggested match-field pairing with confidence and rationale">
          <div className="prediction-list">
            {predictionRows.map((p) => (
              <div className="prediction" key={`${p.left_field}-${p.right_field}`}>
                <div>
                  <strong>{p.left_field} ↔ {p.right_field}</strong>
                  <p>{p.rationale}</p>
                </div>
                <div className="confidence-ring"><span>{p.confidence}%</span></div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Transform and cleanse rules" subtitle="Prototype rules kept transparent for audit and operations sign-off">
        <div className="rule-grid">
          {(preview?.normalisation_rules || []).map((r) => (
            <div className="rule-card" key={r.rule}>
              <strong>{r.rule}</strong>
              <p>{r.applies_to}</p>
            </div>
          ))}
        </div>
      </Panel>

      <div className="grid two">
        <Panel title={`PSR preview (${preview?.psr?.total || 0} rows)`}>
          <PreviewTable rows={psrRows} columns={["id", "reference", "amount", "direction", "invoice", "counterparty", "currency"]} />
        </Panel>
        <Panel title={`CAMT preview (${preview?.camt?.total || 0} rows)`}>
          <PreviewTable rows={camtRows} columns={["ntry_id", "pmt_ref", "amount", "direction", "invoice", "counterparty", "currency"]} />
        </Panel>
      </div>
    </section>
  );
}

function PreviewTable({ rows, columns }) {
  return (
    <div className="table-wrap compact tight">
      <table>
        <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, idx) => <tr key={idx}>{columns.map((c) => <td key={c}>{String(r[c] ?? '-')}</td>)}</tr>)}
          {!rows.length && <tr><td colSpan={columns.length} className="empty">No preview data.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function MatchingStudio({ patterns, rules, onTunePattern, onTogglePattern, onCreatePattern }) {
  const [drafts, setDrafts] = useState({});
  const [newName, setNewName] = useState('Invoice suffix normalisation');

  useEffect(() => {
    const next = {};
    patterns.forEach((p) => {
      next[p.pattern_id] = {
        execution_mode: p.execution_mode || 'SUGGESTION',
        confidence_threshold: p.confidence_threshold ?? 0.8,
        pattern_rule: p.pattern_rule || {},
      };
    });
    setDrafts(next);
  }, [patterns]);

  const updateDraft = (id, field, value) => {
    setDrafts((prev) => ({ ...prev, [id]: { ...(prev[id] || {}), [field]: value } }));
  };

  return (
    <section className="screen">
      <div className="screen-title">
        <div>
          <div className="eyebrow">Matching studio</div>
          <h1>No-code match rules, multi-pass logic and pattern registry</h1>
          <p>Operations-friendly rule text backed by configurable FastAPI pattern records and deterministic reconciliation logic.</p>
        </div>
      </div>

      <Panel title="Rule builder" subtitle="Add a controlled suggestion-only rule without writing code">
        <div className="builder-row">
          <input value={newName} onChange={(e) => setNewName(e.target.value)} />
          <button className="btn primary" onClick={() => onCreatePattern(newName)}>Create suggestion pattern</button>
        </div>
      </Panel>

      <div className="grid two">
        <Panel title="Natural rule language view" subtitle="Readable rules equivalent to a business-owned recon configuration">
          <div className="nrl-list">
            {(rules?.items || []).map((r) => (
              <div className="nrl-card" key={r.pattern_id}>
                <div><Tag tone={classForStatus(r.status)}>{r.status}</Tag> <Tag tone="info">{r.execution_mode}</Tag></div>
                <strong>{r.pattern_name}</strong>
                <p>{r.natural_rule}</p>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Multi-pass execution order" subtitle="The same cases are evaluated through ordered passes, then routed by confidence">
          <div className="pass-list">
            {(patterns || []).map((p, idx) => (
              <div className="pass" key={p.pattern_id}>
                <span>{idx + 1}</span>
                <div><strong>{p.pattern_id} · {p.pattern_name}</strong><p>{p.execution_mode} · threshold {p.confidence_threshold}</p></div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Pattern registry and tuning" subtitle="Tune thresholds or suspend risky rules for testing and governance">
        <div className="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>Name</th><th>Status</th><th>Mode</th><th>Threshold</th><th>Rule JSON</th><th>Actions</th></tr></thead>
            <tbody>
              {patterns.map((p) => {
                const draft = drafts[p.pattern_id] || {};
                return (
                  <tr key={p.pattern_id}>
                    <td><strong>{p.pattern_id}</strong></td>
                    <td>{p.pattern_name}</td>
                    <td><Tag tone={classForStatus(p.status)}>{p.status}</Tag></td>
                    <td>
                      <select value={draft.execution_mode || p.execution_mode} onChange={(e) => updateDraft(p.pattern_id, 'execution_mode', e.target.value)}>
                        <option value="AUTO_CLOSE">AUTO_CLOSE</option>
                        <option value="SUGGESTION">SUGGESTION</option>
                        <option value="MANUAL">MANUAL</option>
                        <option value="LEDGER_OR_IN_TRANSIT">LEDGER_OR_IN_TRANSIT</option>
                      </select>
                    </td>
                    <td><input className="small-input" type="number" step="0.01" min="0" max="1" value={draft.confidence_threshold ?? p.confidence_threshold} onChange={(e) => updateDraft(p.pattern_id, 'confidence_threshold', Number(e.target.value))} /></td>
                    <td><code>{JSON.stringify(p.pattern_rule || {})}</code></td>
                    <td className="action-cell">
                      <button className="btn secondary" onClick={() => onTunePattern(p.pattern_id, draft)}>Save</button>
                      <button className="btn ghost" onClick={() => onTogglePattern(p)}>{p.status === 'ACTIVE' ? 'Suspend' : 'Activate'}</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </section>
  );
}

const varianceTone = (v) => {
  if (v === null || v === undefined) return '';
  if (v === 0) return 'positive';
  if (Math.abs(v) <= MINOR_VARIANCE_TOLERANCE) return 'warning';
  return 'negative';
};

function AiPill({ rule }) {
  if (!rule || (!rule.startsWith('TIER2B') && !rule.startsWith('TIER2C'))) return null;
  const isNoMatch = rule === 'TIER2C_NO_MATCH';
  return <span className={`ai-pill ${isNoMatch ? 'muted' : 'accent'}`} title={rule}>AI</span>;
}

function SortTh({ col, label, sortCol, sortDir, onSort }) {
  const active = sortCol === col;
  return (
    <th onClick={() => onSort(col)} style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}>
      {label}{active ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
    </th>
  );
}

function ResultTable({ rows, onSelect }) {
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState('asc');

  const onSort = (col) => {
    if (sortCol === col) setSortDir((d) => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('asc'); }
  };

  const sorted = useMemo(() => {
    if (!sortCol) return rows;
    return [...rows].sort((a, b) => {
      const av = a[sortCol] ?? '';
      const bv = b[sortCol] ?? '';
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
  }, [rows, sortCol, sortDir]);

  const sp = { sortCol, sortDir, onSort };

  return (
    <div className="table-wrap results-table">
      <table>
        <thead>
          <tr>
            <th>Case</th>
            <th>Internal</th>
            <th>Bank</th>
            <th>Reference</th>
            <th>Counterparty</th>
            <SortTh col="variance" label="Variance" {...sp} />
            <SortTh col="reconciliation_status" label="Status" {...sp} />
            <SortTh col="rule_applied" label="Rule" {...sp} />
            <SortTh col="match_confidence" label="Confidence" {...sp} />
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.result_id} onClick={() => onSelect?.(r)} className="clickable">
              <td><strong>{r.result_id}</strong><AiPill rule={r.rule_applied} /><br/><span className="muted">{r.psr_id || '-'} / {r.camt_id || '-'}</span></td>
              <td>{money(r.internal_amount)}</td>
              <td>{money(r.bank_amount)}</td>
              <td>{r.reference || '-'}</td>
              <td>{r.counterparty || '-'}</td>
              <td className={varianceTone(r.variance)}>{r.variance != null ? money(r.variance) : '-'}</td>
              <td><Tag tone={classForStatus(r.reconciliation_status)}>{r.reconciliation_status}</Tag></td>
              <td>{r.rule_applied || '-'}</td>
              <td><div className="mini-score"><span style={{ width: `${r.match_confidence || 0}%` }} />{r.match_confidence}%</div></td>
            </tr>
          ))}
          {!sorted.length && <tr><td colSpan="9" className="empty">No records to display.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceDrawer({ selected, onClose, onResolve, rows = [], selectedIndex = -1, onPrev, onNext }) {
  if (!selected) return null;
  const score = selected.feature_snapshot?.score_breakdown || {};
  const components = score.components || [];
  const suggestions = selected.suggestions || [];
  const aiSuggestion = suggestions.find(s => s.action === 'CONFIRM_AI_MATCH');
  const total = rows.length;
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer">
        <div className="drawer-nav">
          <button className="btn ghost" disabled={selectedIndex <= 0} onClick={onPrev}>← Prev</button>
          <span>{selectedIndex >= 0 ? `${selectedIndex + 1} / ${total}` : ''}</span>
          <button className="btn ghost" disabled={selectedIndex < 0 || selectedIndex >= total - 1} onClick={onNext}>Next →</button>
          <button className="btn ghost" onClick={onClose}>Close</button>
        </div>
        <div className="drawer-body">
          <div className="eyebrow">Match evidence</div>
          <h2>{selected.result_id}</h2>
          <p>{selected.explanation}</p>
          <dl className="kv drawer-kv">
            <dt>Status</dt><dd><Tag tone={classForStatus(selected.reconciliation_status)}>{selected.reconciliation_status}</Tag></dd>
            <dt>Rule applied</dt><dd>{selected.rule_applied || '-'}</dd>
            <dt>Reason</dt><dd>{selected.reason_code || '-'}</dd>
            <dt>Invoice</dt><dd>{selected.invoice || '-'}</dd>
            <dt>Counterparty</dt><dd>{selected.counterparty || '-'}</dd>
            <dt>Variance</dt><dd>{money(selected.variance)}</dd>
          </dl>
          <Panel title="Why this decision?" subtitle={score.decision_basis || 'Evidence breakdown captured by the engine.'} className="nested-panel">
            <div className="score-large"><span style={{ width: `${selected.match_confidence || 0}%` }} /></div>
            <div className="evidence-list">
              {components.map((c) => (
                <div className="evidence" key={c.component}>
                  <Tag tone={c.passed ? 'success' : 'warning'}>{c.passed ? 'Pass' : 'Check'}</Tag>
                  <strong>{c.component}</strong>
                  <span>{c.weight}%</span>
                  <p>{c.evidence}</p>
                </div>
              ))}
              {!components.length && <p className="empty small">No field-level evidence stored.</p>}
            </div>
          </Panel>
          <Panel title="Suggested actions" className="nested-panel">
            <div className="action-stack">
              {suggestions.map((s, idx) => (
                <div className="suggestion" key={idx}>
                  <strong>{s.action}</strong>
                  <p>{s.reason || (s.confidence != null ? `${(s.confidence * 100).toFixed(1)}%` : '')}</p>
                </div>
              ))}
              {!suggestions.length && <p className="empty small">No suggestions available.</p>}
            </div>
          </Panel>
        </div>
        {selected.exception_flag === 'Y' && (
          <div className="drawer-footer">
            {aiSuggestion && (
              <button className="btn primary full" onClick={() => onResolve(selected, 'CONFIRM_AI_MATCH')}>Confirm AI match</button>
            )}
            <button className={`btn ${aiSuggestion ? 'ghost' : 'primary'} full`} onClick={() => onResolve(selected)}>Resolve and capture learning</button>
          </div>
        )}
      </aside>
    </>
  );
}

const PAGE_SIZE = 100;
const MINOR_VARIANCE_TOLERANCE = 50;

const STATUS_OPTIONS = [
  '',
  'Matched & Settled (Auto-Close)',
  'Uncleared / In-Transit Payment',
  'AI-Assisted Suggested Match',
  'AI - Analyst Adjudication Required',
  'Post to Short or Over Ledger',
  'Suggested Match - Analyst Review',
  'Bank-only Item - Investigation',
];

function SummaryBar({ summary = {}, total = 0, activeFilter, onFilter }) {
  const statuses = summary.statuses || [];
  const statusCount = (match) => statuses
    .filter(s => match(s.reconciliation_status || ''))
    .reduce((acc, s) => acc + (s.count || 0), 0);
  const exceptionCount = summary.raw?.kpi?.exception_count ?? 0;
  const aiSuggestedCount = statusCount(s => s === 'AI-Assisted Suggested Match');
  const chips = [
    { label: 'Total',        value: total,            filter: '' },
    { label: 'Matched',      value: statusCount(s => s.includes('Matched') || s.includes('Auto-Close')), filter: 'Matched & Settled (Auto-Close)' },
    { label: 'AI Suggested', value: aiSuggestedCount, filter: 'AI-Assisted Suggested Match' },
    { label: 'Exceptions',   value: exceptionCount - aiSuggestedCount,   filter: 'exceptions' },
    { label: 'In-Transit',   value: statusCount(s => s.includes('In-Transit') || s.includes('Uncleared')), filter: 'Uncleared / In-Transit Payment' },
  ];
  return (
    <div className="summary-bar">
      {chips.map(c => (
        <button key={c.label} className={`chip${activeFilter === c.filter ? ' active' : ''}`} onClick={() => onFilter(c.filter)}>
          <strong>{c.value}</strong><span>{c.label}</span>
        </button>
      ))}
    </div>
  );
}

function ResultsWorkbench({ results, summary, selected, setSelected, refreshResults, onAiTriage, loading }) {
  const [search, setSearch] = useState('');
  const [exceptionOnly, setExceptionOnly] = useState(false);
  const [selectedStatus, setSelectedStatus] = useState('');
  const [page, setPage] = useState(0);

  const total = results.total || 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);
  const from = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const to = Math.min((page + 1) * PAGE_SIZE, total);
  const countLabel = total === 0 ? 'No records' : `Showing ${from}\u2013${to} of ${total}`;

  const activeFilter = exceptionOnly ? 'exceptions' : selectedStatus;

  const onFilter = (filter) => {
    setPage(0);
    if (filter === '') {
      setSelectedStatus(''); setExceptionOnly(false);
      refreshResults({ status: '', exceptionOnly: false, limit: PAGE_SIZE, offset: 0 });
    } else if (filter === 'exceptions') {
      setExceptionOnly(true); setSelectedStatus('');
      refreshResults({ exceptionOnly: true, status: '', limit: PAGE_SIZE, offset: 0 });
    } else {
      setSelectedStatus(filter); setExceptionOnly(false);
      refreshResults({ status: filter, exceptionOnly: false, limit: PAGE_SIZE, offset: 0 });
    }
  };

  const runSearch = () => { setPage(0); refreshResults({ search, exceptionOnly, status: selectedStatus, limit: PAGE_SIZE, offset: 0 }); };

  return (
    <section className="screen">
      <div className="screen-title split">
        <div>
          <div className="eyebrow">Results workbench</div>
          <h1>Matched, proposed and unresolved records</h1>
          <p>Drill into match evidence, failed fields, confidence and next-best action.</p>
        </div>
        <div className="toolbar" style={{ flexWrap: 'nowrap', gap: '0.5rem', alignItems: 'center' }}>
          {/* Filter group — allowed to shrink/wrap internally */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center', flex: 1, minWidth: 0 }}>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && runSearch()}
              placeholder="Search PSR, CAMT, invoice, party"
              style={{ minWidth: '180px', flex: 1 }}
            />
            <select
              value={selectedStatus}
              onChange={(e) => {
                const val = e.target.value;
                setSelectedStatus(val);
                setPage(0);
                refreshResults({ search, exceptionOnly, status: val, limit: PAGE_SIZE, offset: 0 });
              }}
              style={{ minWidth: '160px' }}
            >
              <option value="">All statuses</option>
              {STATUS_OPTIONS.filter(Boolean).map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <label className="toggle" style={{ whiteSpace: 'nowrap' }}>
              <input
                type="checkbox"
                checked={exceptionOnly}
                onChange={(e) => {
                  const val = e.target.checked;
                  setExceptionOnly(val);
                  setPage(0);
                  refreshResults({ search, exceptionOnly: val, status: selectedStatus, limit: PAGE_SIZE, offset: 0 });
                }}
              /> Exceptions only
            </label>
          </div>
          {/* AI triage — always anchored to the right, never wraps */}
          <span style={{ borderLeft: '1px solid var(--border)', height: '1.5rem', flexShrink: 0 }} />
          <button className="btn primary" style={{ flexShrink: 0, whiteSpace: 'nowrap' }} disabled={loading} onClick={onAiTriage}>Run AI triage</button>
        </div>
      </div>
      <SummaryBar summary={summary} total={total} activeFilter={activeFilter} onFilter={onFilter} />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.25rem 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button
            className="btn secondary"
            disabled={page === 0}
            onClick={() => { const p = page - 1; setPage(p); refreshResults({ search, exceptionOnly, status: selectedStatus, limit: PAGE_SIZE, offset: p * PAGE_SIZE }); }}
          >← Prev</button>
          <span style={{ fontSize: '0.85rem', color: 'var(--muted, #888)' }}>Page {page + 1} of {totalPages || 1}</span>
          <button
            className="btn secondary"
            disabled={page >= totalPages - 1}
            onClick={() => { const p = page + 1; setPage(p); refreshResults({ search, exceptionOnly, status: selectedStatus, limit: PAGE_SIZE, offset: p * PAGE_SIZE }); }}
          >Next →</button>
        </div>
        <span style={{ fontSize: '0.8rem', color: 'var(--muted, #888)' }}>{countLabel}</span>
      </div>
      <ResultTable rows={results.items || []} onSelect={setSelected} />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.5rem 0', gap: '0.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button
            className="btn secondary"
            disabled={page === 0}
            onClick={() => { const p = page - 1; setPage(p); refreshResults({ search, exceptionOnly, status: selectedStatus, limit: PAGE_SIZE, offset: p * PAGE_SIZE }); }}
          >← Prev</button>
          <span style={{ fontSize: '0.85rem', color: 'var(--muted, #888)' }}>Page {page + 1} of {totalPages || 1}</span>
          <button
            className="btn secondary"
            disabled={page >= totalPages - 1}
            onClick={() => { const p = page + 1; setPage(p); refreshResults({ search, exceptionOnly, status: selectedStatus, limit: PAGE_SIZE, offset: p * PAGE_SIZE }); }}
          >Next →</button>
        </div>
        <span style={{ fontSize: '0.8rem', color: 'var(--muted, #888)' }}>{countLabel}</span>
      </div>
      <EvidenceDrawer
        selected={selected}
        onClose={() => setSelected(null)}
        onResolve={setSelected}
        rows={results.items || []}
        selectedIndex={(results.items || []).findIndex(r => r.result_id === selected?.result_id)}
        onPrev={() => { const idx = (results.items || []).findIndex(r => r.result_id === selected?.result_id); if (idx > 0) setSelected(results.items[idx - 1]); }}
        onNext={() => { const idx = (results.items || []).findIndex(r => r.result_id === selected?.result_id); if (idx < (results.items || []).length - 1) setSelected(results.items[idx + 1]); }}
      />
    </section>
  );
}

function ManualResolveModal({ exceptionItem, onClose, onSubmit }) {
  const suggestions = exceptionItem?.suggestions || [];
  const aiSuggestion = suggestions.find(s => s.action === 'CONFIRM_AI_MATCH' || s.action === 'ROUTE_TO_ANALYST');
  const isAiPreFilled = !!aiSuggestion;

  const defaultReason = aiSuggestion ? 'AI_ASSISTED_MATCH' : 'REMITTANCE_FORMAT_MISMATCH';
  const defaultComment = aiSuggestion
    ? `AI triage suggested this match (confidence ${Math.round((aiSuggestion.confidence || 0) * 100)}%). ${exceptionItem?.explanation || ''} Analyst reviewed and confirmed.`
    : 'Analyst confirmed this case after checking invoice, amount and counterparty evidence.';

  const [reason, setReason] = useState(defaultReason);
  const [resolutionType, setResolutionType] = useState('MATCHED_MANUAL');
  const [comment, setComment] = useState(defaultComment);
  const [fields, setFields] = useState(['invoice_suffix', 'amount', 'counterparty']);
  if (!exceptionItem) return null;
  const fieldOptions = ['reference', 'invoice', 'invoice_suffix', 'amount', 'currency', 'counterparty', 'booking_date', 'remittance_text'];
  const toggleField = (f) => setFields((prev) => prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f]);
  return (
    <div className="modal-backdrop">
      <div className="modal large">
        <div className="eyebrow">Human-in-loop learning</div>
        {isAiPreFilled && (
          <div className="eyebrow" style={{ color: '#7c3aed', marginBottom: '8px' }}>✦ AI pre-filled · review before confirming</div>
        )}
        <h2>Resolve exception and record learning signal</h2>
        <p>Case {exceptionItem.result_id}. The engine records trusted fields, selected outcome and reason code as governed learning data.</p>
        <div className="grid two no-gap">
          <div className="form-grid">
            <label>Resolution type</label>
            <select value={resolutionType} onChange={(e) => setResolutionType(e.target.value)}>
              <option value="MATCHED_MANUAL">Manual match</option>
              <option value="LEDGER_ALLOCATION">Ledger allocation</option>
              <option value="IN_TRANSIT">In-transit / wait for next CAMT</option>
              <option value="BANK_ONLY_INVESTIGATION">Bank-only investigation</option>
            </select>
            <label>Reason code</label>
            <select value={reason} onChange={(e) => setReason(e.target.value)}>
              {isAiPreFilled && <option value="AI_ASSISTED_MATCH">AI-assisted match (analyst confirmed)</option>}
              <option value="REMITTANCE_FORMAT_MISMATCH">Remittance format mismatch</option>
              <option value="COUNTERPARTY_ALIAS">Counterparty alias issue</option>
              <option value="BATCH_SETTLEMENT">Batch settlement grouping</option>
              <option value="DELAYED_BANK_POSTING">Delayed bank posting</option>
              <option value="MINOR_AMOUNT_VARIANCE">Minor amount variance</option>
            </select>
          </div>
          <div>
            <label className="label">Fields trusted by analyst</label>
            <div className="chip-row">
              {fieldOptions.map((f) => <button key={f} className={`chip ${fields.includes(f) ? 'active' : ''}`} onClick={() => toggleField(f)}>{f}</button>)}
            </div>
          </div>
        </div>
        <label className="label">Comment</label>
        <textarea value={comment} onChange={(e) => setComment(e.target.value)} />
        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={() => onSubmit(exceptionItem, resolutionType, reason, comment, fields)}>Confirm and learn</button>
        </div>
      </div>
    </div>
  );
}

function Exceptions({ exceptions, workflowRules, onResolveClick, onWorkflowUpdate }) {
  const rows = exceptions.items || [];
  return (
    <section className="screen">
      <div className="screen-title">
        <div>
          <div className="eyebrow">Exception workflow</div>
          <h1>Assign, prioritise, label and resolve breaks</h1>
          <p>Automated workflow rules can label date breaks, assign owners, add comments, escalate aged items and capture learning signals.</p>
        </div>
      </div>

      <Panel title="Workflow rules" subtitle="Business-readable exception automation">
        <div className="workflow-grid">
          {(workflowRules?.items || []).map((r) => (
            <div className="workflow-card" key={r.rule_id}>
              <div><Tag tone={r.enabled ? 'success' : 'neutral'}>{r.enabled ? 'Enabled' : 'Off'}</Tag></div>
              <strong>{r.name}</strong>
              <p>{r.condition}</p>
              <ul>{r.actions.map((a) => <li key={a}>{a}</li>)}</ul>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Open exception queue" subtitle="Operational view with owner, SLA, priority, variance and match confidence">
        <div className="table-wrap exception-table">
          <table>
            <thead><tr><th>Case</th><th>Priority</th><th>Owner</th><th>Workflow</th><th>SLA due</th><th>Status</th><th>Variance</th><th>Confidence</th><th>Actions</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.case_id || r.result_id}>
                  <td><strong>{r.case_id || r.result_id}</strong><br/><span className="muted">{r.psr_id || r.camt_id}</span></td>
                  <td><Tag tone={classForStatus(r.priority)}>{r.priority || 'Medium'}</Tag></td>
                  <td>{r.owner || 'Unassigned'}</td>
                  <td>{r.workflow_status || 'NEW'}</td>
                  <td>{r.sla_due_at || '-'}</td>
                  <td><Tag tone={classForStatus(r.reconciliation_status)}>{r.reconciliation_status}</Tag></td>
                  <td>{money(r.variance)}</td>
                  <td>{r.match_confidence}%</td>
                  <td className="action-cell">
                    <button className="btn secondary" onClick={() => onWorkflowUpdate(r.case_id || r.result_id, { owner: 'analyst_01', workflow_status: 'IN_REVIEW', comment: 'Assigned from exception queue' })}>Assign</button>
                    <button className="btn ghost" onClick={() => onWorkflowUpdate(r.case_id || r.result_id, { priority: 'High', comment: 'Escalated by analyst' })}>Escalate</button>
                    <button className="btn primary" onClick={() => onResolveClick(r)}>Resolve</button>
                  </td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan="9" className="empty">No open exceptions.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
    </section>
  );
}

function Dashboards({ dashboard, onExport }) {
  const charts = dashboard?.charts || {};
  const summary = dashboard?.summary || {};
  return (
    <section className="screen">
      <div className="screen-title split">
        <div>
          <div className="eyebrow">Dashboards</div>
          <h1>Reconciliation control tower</h1>
          <p>Role-based oversight for match rate, open exceptions, ageing, owners, root causes and rule performance.</p>
        </div>
        <button className="btn ghost" onClick={onExport}>Export results CSV</button>
      </div>

      <div className="metric-grid five">
        <Metric label="Total cases" value={summary.total_cases || 0} hint="Current run" tone="neutral" />
        <Metric label="Match rate" value={pct(summary.match_rate)} hint="Auto-closed cases" tone="success" />
        <Metric label="Open exceptions" value={summary.exceptions || 0} hint="Active workflow queue" tone="warning" />
        <Metric label="Avg confidence" value={pct(summary.average_confidence)} hint="Engine score" tone="info" />
        <Metric label="Abs variance" value={money(summary.absolute_variance || 0)} hint="Break exposure" tone="danger" />
      </div>

      <div className="grid two">
        <Panel title="Open cases by status"><BarList rows={charts.by_status || []} /></Panel>
        <Panel title="Open exceptions by ageing"><BarList rows={charts.by_age || []} /></Panel>
        <Panel title="Rule performance"><BarList rows={charts.by_rule || []} /></Panel>
        <Panel title="Root-cause categories"><BarList rows={charts.by_reason || []} /></Panel>
        <Panel title="Owner workload"><BarList rows={charts.by_owner || []} /></Panel>
        <Panel title="Priority distribution"><BarList rows={charts.by_priority || []} /></Panel>
      </div>

      <Panel title="Root-cause insight feed" subtitle="Actionable observations generated from current run and workflow state">
        <div className="insight-list horizontal">
          {(dashboard?.root_cause_insights || []).map((i) => <div className="insight" key={i}><span>RC</span><p>{i}</p></div>)}
        </div>
      </Panel>
    </section>
  );
}

function Learning({ candidates, events, onSeed, onDiscover, onApprove }) {
  return (
    <section className="screen">
      <div className="screen-title split">
        <div>
          <div className="eyebrow">Learning lab</div>
          <h1>Convert repeated manual resolutions into governed patterns</h1>
          <p>Human-in-the-loop learning observes analyst behaviour and promotes candidate rules through approval gates.</p>
        </div>
        <div className="button-row">
          <button className="btn secondary" onClick={onSeed}>Seed demo learning</button>
          <button className="btn primary" onClick={onDiscover}>Discover patterns</button>
        </div>
      </div>

      <div className="grid two">
        <Panel title="Candidate pattern inbox" subtitle="New rules are suggestion-only until back-tested and approved">
          <div className="candidate-list">
            {candidates.map((c) => (
              <div className="candidate" key={c.candidate_pattern_id}>
                <div>
                  <Tag tone={classForStatus(c.status)}>{c.status}</Tag>
                  <strong>{c.pattern_name}</strong>
                  <p>{c.observed_case_count} observed cases · {c.backtest_precision}% prototype precision · false-positive estimate {c.estimated_false_positive_rate}%</p>
                </div>
                {c.status !== 'APPROVED' && <button className="btn secondary" onClick={() => onApprove(c.candidate_pattern_id)}>Approve suggestion</button>}
              </div>
            ))}
            {!candidates.length && <p className="empty small">No learnt pattern candidates yet. Resolve exceptions or seed demo learning.</p>}
          </div>
        </Panel>
        <Panel title="Learning event stream" subtitle="Structured analyst actions, not just audit text">
          <div className="event-list">
            {events.slice(0, 8).map((e) => (
              <div className="event" key={e.event_id}>
                <strong>{e.event_type}</strong>
                <span>{e.case_id} · {e.user_id} · {e.event_timestamp}</span>
              </div>
            ))}
            {!events.length && <p className="empty small">No analyst actions captured yet.</p>}
          </div>
        </Panel>
      </div>

      <Panel title="Promotion path" subtitle="Safety-first governance model for learned patterns">
        <div className="promotion">
          {['Manual resolution', 'Feature extraction', 'Candidate rule', 'Back-test', 'Lead approval', 'Suggest only', 'Auto-close eligible'].map((s, idx) => <div className="promo" key={s}><span>{idx + 1}</span>{s}</div>)}
        </div>
      </Panel>
    </section>
  );
}

function Assistant({ onAsk, answer }) {
  const [question, setQuestion] = useState('Which exceptions should I prioritise today?');
  const prompts = [
    'Show auto-close match rate',
    'Which rules caused the most exceptions?',
    'What is the total variance?',
    'How many learning patterns exist?',
  ];
  return (
    <section className="screen">
      <div className="screen-title">
        <div>
          <div className="eyebrow">Recon Copilot</div>
          <h1>Interactive operations assistant</h1>
          <p>Ask reconciliation questions and trigger guided investigation from summary, workflow and learning state.</p>
        </div>
      </div>
      <Panel title="Ask the assistant">
        <div className="assistant-box">
          <input value={question} onChange={(e) => setQuestion(e.target.value)} />
          <button className="btn primary" onClick={() => onAsk(question)}>Ask</button>
        </div>
        <div className="prompt-row">
          {prompts.map((q) => <button className="btn ghost" key={q} onClick={() => { setQuestion(q); onAsk(q); }}>{q}</button>)}
        </div>
        {answer && <div className="assistant-answer"><strong>Assistant</strong><p>{answer.answer}</p></div>}
      </Panel>
    </section>
  );
}

function Governance({ events, workspace, onSnapshot }) {
  return (
    <section className="screen">
      <div className="screen-title split">
        <div>
          <div className="eyebrow">Governance and audit</div>
          <h1>Control, traceability and process evidence</h1>
          <p>Audit trail, snapshot governance, pattern approval and configuration evidence for regulated operations.</p>
        </div>
        <button className="btn primary" onClick={onSnapshot}>Create snapshot</button>
      </div>

      <div className="grid two">
        <Panel title="Process controls">
          <dl className="kv">
            <dt>Process ID</dt><dd>{workspace?.process?.process_id || 'IRE-CASH-001'}</dd>
            <dt>Environment</dt><dd>{workspace?.process?.environment || 'Prototype / UAT'}</dd>
            <dt>Owner</dt><dd>{workspace?.process?.owner || 'Recon Ops Lead'}</dd>
            <dt>Last snapshot</dt><dd>{workspace?.process?.last_snapshot || '-'}</dd>
          </dl>
        </Panel>
        <Panel title="Audit design">
          <div className="rule-grid">
            <div className="rule-card"><strong>Immutable user events</strong><p>Manual resolutions and overrides are stored as append-only events.</p></div>
            <div className="rule-card"><strong>Pattern approval</strong><p>Learned rules require review before active use.</p></div>
            <div className="rule-card"><strong>Suggestion-first learning</strong><p>AI-derived logic does not auto-close until back-tested.</p></div>
          </div>
        </Panel>
      </div>

      <Panel title="Audit trail">
        <div className="event-list audit-list">
          {events.map((e) => (
            <div className="event" key={e.event_id}>
              <strong>{e.event_type}</strong>
              <span>{e.event_timestamp} · {e.case_id} · {e.user_id}</span>
              <code>{JSON.stringify(e.event_payload)}</code>
            </div>
          ))}
          {!events.length && <p className="empty small">No events recorded yet.</p>}
        </div>
      </Panel>
    </section>
  );
}

export default function App() {
  const [active, setActive] = useState('workspace');
  const [summary, setSummary] = useState({ statuses: [], reasons: [] });
  const [results, setResults] = useState({ items: [] });
  const [batches, setBatches] = useState({ items: [] });
  const [selectedBatchId, setSelectedBatchId] = useState('');
  const [quality, setQuality] = useState(null);
  const [exceptions, setExceptions] = useState({ items: [] });
  const [patterns, setPatterns] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [events, setEvents] = useState([]);
  const [workspace, setWorkspace] = useState(null);
  const [submissions, setSubmissions] = useState({ items: [] });
  const [preview, setPreview] = useState(null);
  const [predictions, setPredictions] = useState(null);
  const [noCodeRules, setNoCodeRules] = useState({ items: [] });
  const [workflowRules, setWorkflowRules] = useState({ items: [] });
  const [dashboard, setDashboard] = useState(null);
  const [selected, setSelected] = useState(null);
  const [modalItem, setModalItem] = useState(null);
  const [assistantAnswer, setAssistantAnswer] = useState(null);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState('');

  const refresh = async () => {
    const [summaryData, resultsData, exceptionsData, patternsData, candidatesData, eventsData, batchesData, workspaceData, submissionsData, previewData, predictionData, ruleData, workflowRuleData, dashboardData] = await Promise.all([
      api.summary(),
      api.results({ limit: PAGE_SIZE }),

      api.exceptions({ limit: 150 }),
      api.patterns(),
      api.candidates(),
      api.events(),
      api.batches(),
      api.workspaceOverview(),
      api.workspaceSubmissions(),
      api.dataPreview(),
      api.fieldPredictions(),
      api.noCodeRules(),
      api.workflowRules(),
      api.dashboardModel(),
    ]);
    setSummary(summaryData);
    setResults(resultsData);
    setExceptions(exceptionsData);
    setPatterns(patternsData);
    setCandidates(candidatesData);
    setEvents(eventsData);
    setBatches(batchesData);
    setWorkspace(workspaceData);
    setSubmissions(submissionsData);
    setPreview(previewData);
    setPredictions(predictionData);
    setNoCodeRules(ruleData);
    setWorkflowRules(workflowRuleData);
    setDashboard(dashboardData);
  };

  const safe = async (fn, message) => {
    try {
      setLoading(true);
      await fn();
      await refresh();
      setToast(typeof message === 'function' ? message() : message);
      setTimeout(() => setToast(''), 3200);
    } catch (err) {
      setToast(err.message || 'Unexpected error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh().catch(() => {}); }, []);

  const refreshResults = async ({ search = '', exceptionOnly = false, status = '', limit = PAGE_SIZE, offset = 0 } = {}) => {
    setResults(await api.results({ limit, offset, search, exceptionOnly, status }));
  };

  const uploadReconFile = async (fileType, file, batchId, batchName) => {
    await safe(async () => {
      const response = await api.uploadFile(file, fileType, batchId, batchName);
      setSelectedBatchId(response.batch.batch_id);
      setQuality(null);
    }, `${fileType} file uploaded`);
  };

  const validateSelectedBatch = async (batchId) => {
    await safe(async () => {
      const report = await api.validateBatch(batchId);
      setQuality(report);
    }, 'Data quality validation completed');
  };

  const runSelectedBatch = async (batchId) => {
    await safe(() => api.runBatch(batchId), 'Uploaded batch reconciled');
  };

  const runAiTriage = async () => {
    let result;
    await safe(
      async () => {
        result = await api.aiTriage();
        await refreshResults({ search: '', exceptionOnly: false, status: '' });
      },
      () => {
        const suggested = (result?.clear_count ?? 0) + (result?.llm_adjudicated_count ?? 0);
        const review = (result?.maybe_count ?? 0) - (result?.llm_adjudicated_count ?? 0);
        const parts = [];
        if (suggested) parts.push(`${suggested} suggested`);
        if (review > 0) parts.push(`${review} awaiting review`);
        return `AI triage complete — ${parts.length ? parts.join(', ') : '0 suggestions'}`;
      },
    );
  };

  const tunePattern = async (patternId, draft) => {
    await safe(() => api.updatePattern(patternId, {
      execution_mode: draft.execution_mode,
      confidence_threshold: draft.confidence_threshold,
      pattern_rule: draft.pattern_rule,
    }), 'Pattern configuration saved');
  };

  const togglePattern = async (pattern) => {
    await safe(() => pattern.status === 'ACTIVE' ? api.deactivatePattern(pattern.pattern_id) : api.activatePattern(pattern.pattern_id), 'Pattern status updated');
  };

  const createPattern = async (name) => {
    await safe(() => api.createPattern ? api.createPattern({
      pattern_name: name,
      pattern_type: 'LEARNED_DRAFT',
      pattern_rule: { fields: ['invoice_suffix', 'amount', 'counterparty'], status: 'suggestion_only' },
      status: 'ACTIVE',
      execution_mode: 'SUGGESTION',
      confidence_threshold: 0.87,
      approved_by: 'prototype_user',
    }) : Promise.resolve(), 'Suggestion pattern created');
  };

  const updateWorkflow = async (caseId, payload) => {
    await safe(() => api.updateWorkflow(caseId, { ...payload, updated_by: 'analyst_01' }), 'Exception workflow updated');
  };

  const submitResolution = async (item, resolutionType, reason, comment, fields) => {
    await safe(() => api.resolveException(item.result_id || item.case_id, {
      final_resolution_type: resolutionType,
      reason_code: reason,
      psr_transaction_ids: item.psr_id ? [item.psr_id] : [],
      bank_transaction_ids: item.camt_id ? [item.camt_id] : [],
      fields_used: fields,
      fields_ignored: ['exact_invoice_format', 'exact_pmt_ref'],
      user_comment: comment,
      learning_eligible: true,
    }), 'Manual resolution captured as learning signal');
    setModalItem(null);
  };

  const exportCsv = () => {
    window.open(api.exportResultsUrl(), '_blank', 'noopener,noreferrer');
  };

  const screen = useMemo(() => {
    if (active === 'workspace') return <Workspace workspace={workspace} summary={summary} onLoad={() => safe(api.loadSampleData, 'Sample PSR/CAMT loaded')} onRun={() => safe(api.runRecon, 'Reconciliation completed')} onSnapshot={() => safe(api.createSnapshot, 'Snapshot created')} onExport={exportCsv} loading={loading} />;
    if (active === 'intake') return <DataIntake batches={batches} submissions={submissions} selectedBatchId={selectedBatchId} setSelectedBatchId={setSelectedBatchId} quality={quality} onUpload={uploadReconFile} onValidate={validateSelectedBatch} onRunBatch={runSelectedBatch} loading={loading} />;
    if (active === 'dataprep') return <DataPrep preview={preview} predictions={predictions} />;
    if (active === 'matching') return <MatchingStudio patterns={patterns} rules={noCodeRules} onTunePattern={tunePattern} onTogglePattern={togglePattern} onCreatePattern={createPattern} />;
    if (active === 'results') return <ResultsWorkbench results={results} summary={summary} selected={selected} setSelected={setSelected} refreshResults={refreshResults} onAiTriage={runAiTriage} loading={loading} />;
    if (active === 'exceptions') return <Exceptions exceptions={exceptions} workflowRules={workflowRules} onResolveClick={setModalItem} onWorkflowUpdate={updateWorkflow} />;
    if (active === 'dashboards') return <Dashboards dashboard={dashboard} onExport={exportCsv} />;
    if (active === 'learning') return <Learning candidates={candidates} events={events} onSeed={() => safe(api.seedLearning, 'Demo learning signals seeded')} onDiscover={() => safe(api.discover, 'Pattern discovery completed')} onApprove={(id) => safe(() => api.approveCandidate(id), 'Candidate approved as learnt suggestion')} />;
    if (active === 'assistant') return <Assistant answer={assistantAnswer} onAsk={async (q) => setAssistantAnswer(await api.assistant(q))} />;
    if (active === 'governance') return <Governance events={events} workspace={workspace} onSnapshot={() => safe(api.createSnapshot, 'Snapshot created')} />;
    return null;
  }, [active, workspace, summary, results, exceptions, patterns, candidates, events, batches, submissions, selectedBatchId, quality, preview, predictions, noCodeRules, workflowRules, dashboard, selected, assistantAnswer, loading]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark">IR</div>
          <div>
            <strong>Intelligent Recon</strong>
            <span>Operations Studio</span>
          </div>
        </div>
        <nav className="nav-list">
          {tabs.map(([key, label]) => <button key={key} className={active === key ? 'active' : ''} onClick={() => setActive(key)}>{label}</button>)}
        </nav>
        <div className="sidebar-card">
          <span>Client demo mode</span>
          <strong>PSR ↔ CAMT.053</strong>
          <p>Intelligent reconciliation with explainability and learning.</p>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div>
            <strong>Cash Account Reconciliation</strong>
            <span>Real-time reconciliation · exception automation · learning</span>
          </div>
          <div className="topbar-actions">
            {loading && <span className="loading">Working…</span>}
            <Tag tone="success">FastAPI 8090</Tag>
            <Tag tone="info">React 8181</Tag>
          </div>
        </header>
        {screen}
      </main>
      {modalItem && <ManualResolveModal exceptionItem={modalItem} onClose={() => setModalItem(null)} onSubmit={submitResolution} />}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
