import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api/client';

const tabs = [
  ['workspace', 'Control Room'],
  ['intake', 'Data Intake'],
  ['dataprep', 'Data Prep Studio'],
  ['matching', 'Matching Studio'],
  ['pattern-builder', 'Pattern Builder'],
  ['patterns', 'Pattern Manager'],
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

function compareVersions(left = '1.0', right = '1.0') {
  const parse = (value) => String(value || '1.0').split('.').map((part) => Number(part) || 0);
  const leftParts = parse(left);
  const rightParts = parse(right);
  const length = Math.max(leftParts.length, rightParts.length);
  for (let index = 0; index < length; index += 1) {
    const leftValue = leftParts[index] ?? 0;
    const rightValue = rightParts[index] ?? 0;
    if (leftValue !== rightValue) return leftValue - rightValue;
  }
  return 0;
}

function classForStatus(value = '') {
  const v = String(value).toLowerCase();
  if (v.startsWith('ai-assisted')) return 'ai';
  if (v.startsWith('ai -') || v.startsWith('ai –')) return 'ai-maybe';
  if (v.includes('ai confirmed')) return 'ai-nomatch';
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

function DataIntake({ batches, submissions, selectedBatchId, setSelectedBatchId, quality, batchRunResult, validatedBatchId, onUpload, onUploadBatch, onValidate, onRunBatch, onNavigate, loading, patternGroups }) {
  const [psrFile, setPsrFile] = useState(null);
  const [camtFile, setCamtFile] = useState(null);
  const [batchName, setBatchName] = useState('');
  const [amountDivisor, setAmountDivisor] = useState('auto');
  const [selectedPatternGroup, setSelectedPatternGroup] = useState('');
  const qualityTableRef = useRef(null);
  const selectedBatch = (batches.items || []).find((b) => b.batch_id === selectedBatchId) || (batches.items || [])[0];
  const batchId = selectedBatch?.batch_id || selectedBatchId || '';
  const issues = quality?.issues || [];
  const files = submissions?.items || [];

  const scrollToQualityTable = () => qualityTableRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });

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
            <input
              value={batchName}
              placeholder="e.g. Treasury cash daily upload"
              onChange={(e) => setBatchName(e.target.value)}
            />
            <label>PSR payment settlement file</label>
            <input type="file" accept=".txt,.dat,.psr,text/plain" onChange={(e) => setPsrFile(e.target.files?.[0] || null)} />
            <label>CAMT.053 bank statement</label>
            <input type="file" accept=".xml,application/xml,text/xml" onChange={(e) => setCamtFile(e.target.files?.[0] || null)} />
            <button
              className="btn primary"
              style={{ gridColumn: '1 / -1', marginTop: '0.25rem' }}
              disabled={!psrFile || !camtFile || !batchName.trim() || loading}
              onClick={() => onUploadBatch(psrFile, camtFile, batchName.trim())}
            >
              Upload batch
            </button>
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
              <div className="form-grid" style={{ marginBottom: '0.75rem' }}>
                <label title="Divide raw PSR integer amounts by this value. Auto detects by comparing PSR references to CAMT amounts.">PSR amount divisor</label>
                <select value={amountDivisor} onChange={(e) => setAmountDivisor(e.target.value)}>
                  <option value="auto">Auto-detect</option>
                  <option value="1">1 — amounts already match CAMT scale</option>
                  <option value="100">100 — amounts in minor units (cents)</option>
                </select>
                <label title="Only patterns in this group will be used during reconciliation.">Pattern group</label>
                <select value={selectedPatternGroup || (patternGroups || [])[0] || ''} onChange={(e) => setSelectedPatternGroup(e.target.value)}>
                  {(patternGroups || []).map((g) => (
                    <option key={g} value={g}>{g}</option>
                  ))}
                </select>
              </div>
              <div className="button-row">
                <button className="btn secondary" disabled={!batchId || loading} onClick={() => onValidate(batchId)}>Validate quality</button>
                <button className="btn primary" disabled={!batchId || loading || validatedBatchId !== batchId} onClick={() => onRunBatch(batchId, amountDivisor === 'auto' ? null : Number(amountDivisor), selectedPatternGroup || (patternGroups || [])[0] || null)}>Run uploaded batch</button>
              </div>

              {quality && (
                <div style={{ marginTop: '1.25rem', borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
                  <div style={{ fontSize: '0.72rem', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: '0.6rem' }}>Data quality</div>
                  <div className="metric-grid three" style={{ marginBottom: '0.4rem' }}>
                    <div style={{ cursor: (quality.error_count || 0) > 0 ? 'pointer' : 'default' }} onClick={(quality.error_count || 0) > 0 ? scrollToQualityTable : undefined} title={(quality.error_count || 0) > 0 ? 'Click to see issue details below' : undefined}>
                      <Metric label="Errors" value={quality.error_count || 0} hint={(quality.error_count || 0) > 0 ? '↓ See details' : 'None'} tone="danger" />
                    </div>
                    <div style={{ cursor: (quality.warning_count || 0) > 0 ? 'pointer' : 'default' }} onClick={(quality.warning_count || 0) > 0 ? scrollToQualityTable : undefined} title={(quality.warning_count || 0) > 0 ? 'Click to see issue details below' : undefined}>
                      <Metric label="Warnings" value={quality.warning_count || 0} hint={(quality.warning_count || 0) > 0 ? '↓ See details' : 'None'} tone="warning" />
                    </div>
                    <Metric label="Files checked" value={(quality.files || []).length} hint="PSR + CAMT" tone="info" />
                  </div>
                </div>
              )}

              {batchRunResult && (
                <div style={{ marginTop: '1.25rem', borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
                  <div style={{ fontSize: '0.72rem', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: '0.6rem' }}>Batch run results</div>
                  <div className="metric-grid three" style={{ marginBottom: '0.75rem' }}>
                    <div style={{ cursor: 'pointer' }} onClick={() => onNavigate('results')} title="Open Results Workbench">
                      <Metric label="PSR transactions" value={batchRunResult.psr_count || 0} hint="→ Results Workbench" tone="info" />
                    </div>
                    <div style={{ cursor: 'pointer' }} onClick={() => onNavigate('results')} title="Open Results Workbench">
                      <Metric label="CAMT entries" value={batchRunResult.camt_count || 0} hint="→ Results Workbench" tone="info" />
                    </div>
                    <div style={{ cursor: 'pointer' }} onClick={() => onNavigate('results')} title="Open Results Workbench">
                      <Metric label="Cases created" value={batchRunResult.case_count || 0} hint="→ Results Workbench" tone="good" />
                    </div>
                  </div>
                  <div className="button-row" style={{ marginTop: '0.5rem' }}>
                    <button className="btn secondary small" onClick={() => onNavigate('results')}>View Results Workbench →</button>
                    <button className="btn secondary small" onClick={() => onNavigate('exceptions')}>View Exceptions →</button>
                  </div>
                </div>
              )}
            </>
          ) : <p className="empty small">Upload a PSR file to create a batch.</p>}
        </Panel>
      </div>

      <Panel title="Submissions queue" subtitle="Equivalent operational view for uploaded files, processing status, document state and usage.">
        <div className="table-wrap" style={{ maxHeight: '300px', overflowY: 'auto' }}>
          <table>
            <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}><tr><th>File</th><th>Type</th><th>Batch</th><th>Upload status</th><th>Document status</th><th>Used in</th><th>Profile</th></tr></thead>
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

      {quality && (
        <div ref={qualityTableRef}>
          <Panel title="Data quality issue details" subtitle={`${issues.length} issue${issues.length !== 1 ? 's' : ''} found · ${quality.error_count || 0} error${(quality.error_count || 0) !== 1 ? 's' : ''}, ${quality.warning_count || 0} warning${(quality.warning_count || 0) !== 1 ? 's' : ''}`}>
            <div className="table-wrap compact" style={{ maxHeight: '340px', overflowY: 'auto' }}>
              <table>
                <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}><tr><th>Severity</th><th>Issue</th><th>Record</th><th>Message</th></tr></thead>
                <tbody>
                  {issues.map((i) => <tr key={i.issue_id}><td><Tag tone={classForStatus(i.severity)}>{i.severity}</Tag></td><td>{i.issue_code}</td><td>{i.record_id || '-'}</td><td>{i.message}</td></tr>)}
                  {!issues.length && <tr><td colSpan="4" className="empty">No quality issues found.</td></tr>}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}

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

function PatternManagement({ patterns, onCreate, onDelete }) {
  const BLANK_PATTERN = {
    pattern_name: '',
    pattern_type: 'CUSTOM',
    pattern_rule: '{\n  "fields": [],\n  "mode": "SUGGESTION"\n}',
    status: 'DRAFT',
    execution_mode: 'SUGGESTION',
    confidence_threshold: 0.80,
    approved_by: 'prototype_user',
  };

  const [selectedGroup, setSelectedGroup] = useState('');
  // rowEdits tracks unsaved inline edits: { pattern_id: { field: value } }
  const [rowEdits, setRowEdits] = useState({});
  const [showSaveAsGroupModal, setShowSaveAsGroupModal] = useState(false);
  const [newGroupName, setNewGroupName] = useState('');
  const [showAddPatternModal, setShowAddPatternModal] = useState(false);
  const [addPatternDraft, setAddPatternDraft] = useState({ ...BLANK_PATTERN });
  const [showNewGroupModal, setShowNewGroupModal] = useState(false);
  const [newGroupDraft, setNewGroupDraft] = useState({ group_name: '', ...BLANK_PATTERN });
  const [errors, setErrors] = useState({});

  const groupedPatterns = useMemo(() => {
    const groups = {};
    (patterns || []).forEach((p) => {
      const key = (p.pattern_group || 'default').trim() || 'default';
      if (!groups[key]) groups[key] = [];
      groups[key].push(p);
    });
    return Object.entries(groups)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([groupName, items]) => ({
        groupName,
        items: [...items].sort((a, b) => (a.pattern_name || '').localeCompare(b.pattern_name || '')),
      }));
  }, [patterns]);

  // Auto-select first group on load
  useEffect(() => {
    if (!selectedGroup && groupedPatterns[0]) setSelectedGroup(groupedPatterns[0].groupName);
  }, [groupedPatterns, selectedGroup]);

  // Clear row edits when switching groups
  useEffect(() => { setRowEdits({}); }, [selectedGroup]);

  const hasEdits = Object.keys(rowEdits).length > 0;
  const activeGroup = groupedPatterns.find((g) => g.groupName === selectedGroup) || groupedPatterns[0];

  const updateRowEdit = (patternId, field, value) =>
    setRowEdits((prev) => ({ ...prev, [patternId]: { ...(prev[patternId] || {}), [field]: value } }));

  // Copies all patterns from the active group (with applied edits) into a brand new group name
  const saveAsNewGroup = async () => {
    const name = newGroupName.trim();
    if (!name) { setErrors({ newGroup: 'Group name is required' }); return; }
    if (!activeGroup) return;
    for (const p of activeGroup.items) {
      const edits = rowEdits[p.pattern_id] || {};
      const ruleStr = edits.pattern_rule !== undefined ? edits.pattern_rule : JSON.stringify(p.pattern_rule || {});
      let rule;
      try { rule = JSON.parse(ruleStr); }
      catch { setErrors({ newGroup: `Invalid rule JSON in "${p.pattern_name}"` }); return; }
      await onCreate({
        pattern_name: edits.pattern_name ?? p.pattern_name,
        pattern_type: edits.pattern_type ?? p.pattern_type,
        pattern_group: name,
        pattern_rule: rule,
        status: edits.status ?? p.status,
        execution_mode: edits.execution_mode ?? p.execution_mode,
        confidence_threshold: edits.confidence_threshold ?? p.confidence_threshold,
        approved_by: edits.approved_by ?? p.approved_by ?? 'prototype_user',
      });
    }
    setShowSaveAsGroupModal(false);
    setNewGroupName('');
    setRowEdits({});
    setSelectedGroup(name);
  };

  const saveAddPattern = () => {
    let rule;
    try { rule = JSON.parse(addPatternDraft.pattern_rule); }
    catch { setErrors({ addPattern: 'Invalid JSON in pattern rule' }); return; }
    onCreate({ ...addPatternDraft, pattern_name: addPatternDraft.pattern_name || 'New pattern', pattern_group: selectedGroup || 'default', pattern_rule: rule });
    setShowAddPatternModal(false);
    setAddPatternDraft({ ...BLANK_PATTERN });
    setErrors({});
  };

  const saveNewGroup = () => {
    const name = newGroupDraft.group_name.trim();
    if (!name) { setErrors({ newGroupModal: 'Group name is required' }); return; }
    let rule;
    try { rule = JSON.parse(newGroupDraft.pattern_rule); }
    catch { setErrors({ newGroupModal: 'Invalid JSON in pattern rule' }); return; }
    onCreate({ pattern_name: newGroupDraft.pattern_name || 'New pattern', pattern_type: newGroupDraft.pattern_type, pattern_group: name, pattern_rule: rule, status: newGroupDraft.status, execution_mode: newGroupDraft.execution_mode, confidence_threshold: newGroupDraft.confidence_threshold, approved_by: newGroupDraft.approved_by });
    setShowNewGroupModal(false);
    setSelectedGroup(name);
    setNewGroupDraft({ group_name: '', ...BLANK_PATTERN });
    setErrors({});
  };

  return (
    <section className="screen">
      <div className="screen-title">
        <div>
          <div className="eyebrow">Pattern manager</div>
          <h1>Pattern groups</h1>
          <p>A group is a named set of patterns. Edit patterns inline and save the full set as a new group.</p>
        </div>
        <button className="btn primary" onClick={() => { setErrors({}); setShowNewGroupModal(true); }}>Add new group</button>
      </div>

      <Panel
        title="Groups"
        subtitle="Pick a group to view its patterns. Edit any row, then save all changes as a new group."
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {/* Group selector + action bar */}
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <select value={selectedGroup} onChange={(e) => setSelectedGroup(e.target.value)} style={{ minWidth: '200px' }}>
              {groupedPatterns.map((g) => (
                <option key={g.groupName} value={g.groupName}>{g.groupName} ({g.items.length})</option>
              ))}
            </select>

            {hasEdits && (
              <>
                <button className="btn primary" onClick={() => { setNewGroupName(''); setErrors({}); setShowSaveAsGroupModal(true); }}>
                  Save edits as new group
                </button>
                <button className="btn ghost" onClick={() => setRowEdits({})}>Discard edits</button>
              </>
            )}

            <button className="btn secondary" style={{ marginLeft: 'auto' }} onClick={() => { setErrors({}); setShowAddPatternModal(true); }}>
              Add pattern to group
            </button>
          </div>

          {hasEdits && (
            <div className="tag warning" style={{ alignSelf: 'flex-start' }}>
              Unsaved edits — click "Save edits as new group" to persist
            </div>
          )}

          {/* Patterns table */}
          {activeGroup ? (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Pattern name</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Mode</th>
                    <th>Confidence</th>
                    <th>Rule (JSON)</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {activeGroup.items.map((p) => {
                    const edits = rowEdits[p.pattern_id] || {};
                    const dirty = Object.keys(edits).length > 0;
                    const rowStyle = dirty ? { background: 'var(--warning-bg, #fffbeb)' } : {};
                    return (
                      <tr key={p.pattern_id} style={rowStyle}>
                        <td>
                          <input
                            style={{ width: '100%' }}
                            value={edits.pattern_name ?? p.pattern_name}
                            onChange={(e) => updateRowEdit(p.pattern_id, 'pattern_name', e.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            style={{ width: '90px' }}
                            value={edits.pattern_type ?? p.pattern_type}
                            onChange={(e) => updateRowEdit(p.pattern_id, 'pattern_type', e.target.value)}
                          />
                        </td>
                        <td>
                          <select value={edits.status ?? p.status} onChange={(e) => updateRowEdit(p.pattern_id, 'status', e.target.value)}>
                            <option>DRAFT</option><option>ACTIVE</option><option>INACTIVE</option>
                          </select>
                        </td>
                        <td>
                          <select value={edits.execution_mode ?? p.execution_mode} onChange={(e) => updateRowEdit(p.pattern_id, 'execution_mode', e.target.value)}>
                            <option value="SUGGESTION">SUGGESTION</option>
                            <option value="AUTO_CLOSE">AUTO_CLOSE</option>
                            <option value="MANUAL">MANUAL</option>
                            <option value="LEDGER_OR_IN_TRANSIT">LEDGER_OR_IN_TRANSIT</option>
                          </select>
                        </td>
                        <td>
                          <input
                            type="number" min="0" max="1" step="0.01"
                            style={{ width: '70px' }}
                            value={edits.confidence_threshold ?? p.confidence_threshold}
                            onChange={(e) => updateRowEdit(p.pattern_id, 'confidence_threshold', Number(e.target.value))}
                          />
                        </td>
                        <td><code style={{ fontSize: '0.72rem' }}>{JSON.stringify(p.pattern_rule || {})}</code></td>
                        <td>
                          <button className="btn ghost" onClick={() => onDelete(p.pattern_id)}>Remove</button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty">No groups yet. Click "Add new group" to create one.</p>
          )}
        </div>
      </Panel>

      {/* ── Save edits as new group modal ── */}
      {showSaveAsGroupModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
          <div style={{ background: 'white', padding: '1.5rem', borderRadius: '12px', width: 'min(480px, 90vw)', boxShadow: '0 12px 28px rgba(0,0,0,0.2)' }}>
            <h3 style={{ margin: '0 0 0.5rem' }}>Save edits as new group</h3>
            <p className="muted" style={{ marginBottom: '1rem' }}>
              All {activeGroup?.items.length} patterns from <strong>{selectedGroup}</strong> will be copied with your edits into the new group.
            </p>
            <label>New group name</label>
            <input
              autoFocus
              value={newGroupName}
              placeholder="e.g. Invoice Rules v2"
              onChange={(e) => setNewGroupName(e.target.value)}
              style={{ width: '100%', marginTop: '0.35rem', marginBottom: '0.75rem' }}
            />
            {errors.newGroup && <p className="error-text">{errors.newGroup}</p>}
            <div className="button-row">
              <button className="btn secondary" onClick={() => setShowSaveAsGroupModal(false)}>Cancel</button>
              <button className="btn primary" onClick={saveAsNewGroup}>Create new group</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Add pattern to existing group modal ── */}
      {showAddPatternModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
          <div style={{ background: 'white', padding: '1.25rem', borderRadius: '12px', width: 'min(560px, 90vw)', boxShadow: '0 12px 28px rgba(0,0,0,0.2)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.8rem' }}>
              <strong>Add pattern to &ldquo;{selectedGroup}&rdquo;</strong>
              <button className="btn ghost" onClick={() => setShowAddPatternModal(false)}>Close</button>
            </div>
            <div className="form-grid">
              <label>Name</label>
              <input value={addPatternDraft.pattern_name} onChange={(e) => setAddPatternDraft((d) => ({ ...d, pattern_name: e.target.value }))} />
              <label>Type</label>
              <input value={addPatternDraft.pattern_type} onChange={(e) => setAddPatternDraft((d) => ({ ...d, pattern_type: e.target.value }))} />
              <label>Status</label>
              <select value={addPatternDraft.status} onChange={(e) => setAddPatternDraft((d) => ({ ...d, status: e.target.value }))}>
                <option>DRAFT</option><option>ACTIVE</option><option>INACTIVE</option>
              </select>
              <label>Execution mode</label>
              <select value={addPatternDraft.execution_mode} onChange={(e) => setAddPatternDraft((d) => ({ ...d, execution_mode: e.target.value }))}>
                <option value="SUGGESTION">SUGGESTION</option>
                <option value="AUTO_CLOSE">AUTO_CLOSE</option>
                <option value="MANUAL">MANUAL</option>
                <option value="LEDGER_OR_IN_TRANSIT">LEDGER_OR_IN_TRANSIT</option>
              </select>
              <label>Confidence</label>
              <input type="number" min="0" max="1" step="0.01" value={addPatternDraft.confidence_threshold} onChange={(e) => setAddPatternDraft((d) => ({ ...d, confidence_threshold: Number(e.target.value) }))} />
              <label>Approved by</label>
              <input value={addPatternDraft.approved_by} onChange={(e) => setAddPatternDraft((d) => ({ ...d, approved_by: e.target.value }))} />
              <label>Rule JSON</label>
              <textarea rows={4} value={addPatternDraft.pattern_rule} onChange={(e) => setAddPatternDraft((d) => ({ ...d, pattern_rule: e.target.value }))} />
              {errors.addPattern && <p className="error-text">{errors.addPattern}</p>}
              <div className="button-row">
                <button className="btn secondary" onClick={() => setShowAddPatternModal(false)}>Cancel</button>
                <button className="btn primary" onClick={saveAddPattern}>Add pattern</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Add new group modal ── */}
      {showNewGroupModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
          <div style={{ background: 'white', padding: '1.25rem', borderRadius: '12px', width: 'min(560px, 90vw)', boxShadow: '0 12px 28px rgba(0,0,0,0.2)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.8rem' }}>
              <strong>Create new group</strong>
              <button className="btn ghost" onClick={() => setShowNewGroupModal(false)}>Close</button>
            </div>
            <div className="form-grid">
              <label>Group name</label>
              <input autoFocus value={newGroupDraft.group_name} placeholder="e.g. Invoice Rules" onChange={(e) => setNewGroupDraft((d) => ({ ...d, group_name: e.target.value }))} />
              <label>First pattern name</label>
              <input value={newGroupDraft.pattern_name} onChange={(e) => setNewGroupDraft((d) => ({ ...d, pattern_name: e.target.value }))} />
              <label>Type</label>
              <input value={newGroupDraft.pattern_type} onChange={(e) => setNewGroupDraft((d) => ({ ...d, pattern_type: e.target.value }))} />
              <label>Status</label>
              <select value={newGroupDraft.status} onChange={(e) => setNewGroupDraft((d) => ({ ...d, status: e.target.value }))}>
                <option>DRAFT</option><option>ACTIVE</option>
              </select>
              <label>Execution mode</label>
              <select value={newGroupDraft.execution_mode} onChange={(e) => setNewGroupDraft((d) => ({ ...d, execution_mode: e.target.value }))}>
                <option value="SUGGESTION">SUGGESTION</option>
                <option value="AUTO_CLOSE">AUTO_CLOSE</option>
                <option value="MANUAL">MANUAL</option>
                <option value="LEDGER_OR_IN_TRANSIT">LEDGER_OR_IN_TRANSIT</option>
              </select>
              <label>Confidence</label>
              <input type="number" min="0" max="1" step="0.01" value={newGroupDraft.confidence_threshold} onChange={(e) => setNewGroupDraft((d) => ({ ...d, confidence_threshold: Number(e.target.value) }))} />
              <label>Approved by</label>
              <input value={newGroupDraft.approved_by} onChange={(e) => setNewGroupDraft((d) => ({ ...d, approved_by: e.target.value }))} />
              <label>Rule JSON</label>
              <textarea rows={4} value={newGroupDraft.pattern_rule} onChange={(e) => setNewGroupDraft((d) => ({ ...d, pattern_rule: e.target.value }))} />
              {errors.newGroupModal && <p className="error-text">{errors.newGroupModal}</p>}
              <div className="button-row">
                <button className="btn secondary" onClick={() => setShowNewGroupModal(false)}>Cancel</button>
                <button className="btn primary" onClick={saveNewGroup}>Create group</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function PatternBuilder({ onGenerateMapping, onGeneratePatterns, onSuggestPatterns, onSave, onSaveBulk, proposedPatterns, setProposedPatterns }) {
  const [camtFile, setCamtFile] = useState(null);
  const [otherFile, setOtherFile] = useState(null);
  const [mappingResult, setMappingResult] = useState(null);
  const [patternResult, setPatternResult] = useState(null);
  const [providedRegexMap, setProvidedRegexMap] = useState('');
  const [selectedPattern, setSelectedPattern] = useState(null);
  const [error, setError] = useState('');
  const [loadingPattern, setLoadingPattern] = useState(false);
  const [loadingMapping, setLoadingMapping] = useState(false);

  // Save-as-group state
  const today = new Date().toISOString().slice(0, 10);
  const [groupName, setGroupName] = useState(`auto-${today}`);
  const [selectedGroupPatterns, setSelectedGroupPatterns] = useState(new Set());
  const [bulkSaveStatus, setBulkSaveStatus] = useState(null); // null | {loading} | {success} | {error}

  // Auto-select all patterns when a new analysis result arrives
  useEffect(() => {
    if (!patternResult) return;
    const allKeys = new Set([
      ...(patternResult.deterministic_patterns || []).map(p => `det-${p.rule}`),
      ...(patternResult.llm_patterns || []).map((p, i) => `llm-${p.rule_id || i}`),
    ]);
    setSelectedGroupPatterns(allKeys);
    setBulkSaveStatus(null);
  }, [patternResult]);

  const loadMapping = async () => {
    if (!camtFile || !otherFile) return;
    setError('');
    setLoadingMapping(true);
    try {
      const result = await onGenerateMapping(camtFile, otherFile);
      setMappingResult(result);
    } catch (err) {
      setError(err.message || 'Unable to generate regex mapping');
      setMappingResult(null);
    } finally {
      setLoadingMapping(false);
    }
  };

  const buildPatterns = async () => {
    if (!camtFile || !otherFile) return;
    setError('');
    setLoadingPattern(true);
    try {
      // Use field_extractors from the mapping step when no manual override is typed
      let regexMap = null;
      if (providedRegexMap) {
        try { regexMap = JSON.parse(providedRegexMap); } catch (_) { /* ignore */ }
      } else if (mappingResult) {
        regexMap = mappingResult.llm_output?.field_extractors
          || mappingResult.format_info?.suggested_regex_map
          || null;
      }
      const result = await onGeneratePatterns(camtFile, otherFile, regexMap);
      setPatternResult(result);
      // Flatten deterministic + LLM patterns for the candidates table
      const allPats = [
        ...(result.deterministic_patterns || []).map(p => ({
          pattern_name: p.pattern_name,
          mapping_key: p.rule,
          regex_inferred: {},
          pattern_rule: { fields: p.fields_used || [], mode: 'DETERMINISTIC' },
        })),
        ...(result.llm_patterns || []).map(p => ({
          pattern_name: p.pattern_name,
          mapping_key: p.rule_id,
          regex_inferred: {},
          pattern_rule: { fields: p.fields_used || [], mode: 'LLM_SUGGESTED', tolerance_spec: p.tolerance_spec },
        })),
      ];
      setProposedPatterns(allPats.length > 0 ? allPats : [result]);
      setSelectedPattern(allPats[0] || result);
    } catch (err) {
      setError(err.message || 'Unable to generate reconciliation pattern');
      setPatternResult(null);
    } finally {
      setLoadingPattern(false);
    }
  };

  const suggestPatterns = async () => {
    if (!camtFile || !otherFile) return;
    setError('');
    setLoadingPattern(true);
    try {
      const result = await onSuggestPatterns(camtFile, otherFile);
      // result contains examples, prompt and llm_output
      const suggestions = (result.llm_output && result.llm_output.regex_map) ? result.llm_output : result;
      setPatternResult(suggestions);
      setProposedPatterns([suggestions]);
      setSelectedPattern(suggestions);
    } catch (err) {
      setError(err.message || 'Unable to generate LLM suggestions');
      setPatternResult(null);
    } finally {
      setLoadingPattern(false);
    }
  };

  const savePattern = async () => {
    if (!selectedPattern) return;
    await onSave({
      pattern_name: selectedPattern.pattern_name || 'Generated pattern',
      pattern_type: 'AUTO_GENERATED',
      pattern_version: '1.0',
      pattern_rule: selectedPattern.pattern_rule,
      status: 'DRAFT',
      execution_mode: 'SUGGESTION',
      confidence_threshold: 0.8,
      approved_by: 'prototype_user',
    });
  };

  return (
    <section className="screen">
      <div className="screen-title">
        <div>
          <div className="eyebrow">Pattern builder</div>
          <h1>Upload CAMT and text/PSR, infer regex, then save generated patterns</h1>
          <p>Use the CAMT/PSR flow to generate a candidate pattern, edit it, and persist it into the registry.</p>
        </div>
      </div>

      <div className="grid two">
        <Panel title="Upload source files" subtitle="Choose the bank CAMT file and the corresponding settlement/text file.">
          <div className="form-grid">
            <label>CAMT file</label>
            <input type="file" accept=".xml,application/xml,text/xml" onChange={(e) => setCamtFile(e.target.files?.[0] || null)} />
            <label>Other file</label>
            <input type="file" accept=".txt,.dat,.psr,text/plain,.xml" onChange={(e) => setOtherFile(e.target.files?.[0] || null)} />
            <label>Optional regex override JSON</label>
            <textarea rows={4} value={providedRegexMap} onChange={(e) => setProvidedRegexMap(e.target.value)} placeholder='{"pmt_ref":"\\d+"}' />
            <div className="button-row">
              <button className="btn secondary" onClick={loadMapping} disabled={!camtFile || !otherFile || loadingMapping}>{loadingMapping ? 'Analysing…' : 'Generate regex mapping'}</button>
              <button className="btn ghost" onClick={suggestPatterns} disabled={!camtFile || !otherFile || loadingPattern}>{loadingPattern ? 'Suggesting…' : 'Find missing-ref suggestions (LLM)'}</button>
              <button className="btn primary" onClick={buildPatterns} disabled={!camtFile || !otherFile || loadingPattern}>{loadingPattern ? 'Generating…' : 'Generate pattern'}</button>
            </div>
            {error && <p className="error-text">{error}</p>}
          </div>
        </Panel>

        <Panel title="Reconciliation pattern results" subtitle="Match statistics and active rules from the two-phase analysis.">
          {patternResult?.stats ? (() => {
            const s = patternResult.stats;
            const rate = Math.round((s.match_rate || 0) * 100);
            const rateTone = rate >= 80 ? 'success' : rate >= 50 ? 'warning' : 'danger';
            return (
              <>
                <div className="metric-row">
                  <Metric label="CAMT entries" value={s.camt_total ?? '—'} />
                  <Metric label="Flat-file records" value={s.flat_total ?? '—'} />
                  <Metric label="Matched" value={s.camt_matched ?? '—'} tone="success" />
                  <Metric label="Unmatched" value={s.camt_unmatched ?? '—'} tone={s.camt_unmatched > 0 ? 'warning' : 'success'} />
                  <Metric label="Match rate" value={`${rate}%`} tone={rateTone} hint="camt entries matched" />
                  <Metric label="LLM patterns" value={patternResult.llm_patterns?.length ?? 0} tone={patternResult.llm_available ? 'success' : 'neutral'} />
                </div>
                {patternResult.llm_explanation && (
                  <p style={{ marginTop: '0.75rem', fontSize: '0.83rem', color: 'var(--text-muted, #888)' }}>
                    {patternResult.llm_explanation}
                  </p>
                )}
              </>
            );
          })() : (
            <p className="empty">Run “Generate pattern” to see results.</p>
          )}
          {patternResult && (
            <div className="button-row" style={{ marginTop: '1rem' }}>
              <button className="btn primary" onClick={savePattern}>Save generated pattern</button>
            </div>
          )}
        </Panel>
      </div>

      {mappingResult && (
        <Panel
          title="File Format Detection"
          subtitle={
            mappingResult.llm_available
              ? 'LLM-generated field extractors and structural detection'
              : 'Structural detection from matched CAMT / flat-file pairs'
          }
        >
          {/* ── summary metrics ───────────────────────────────── */}
          {(() => {
            const conf = mappingResult.pattern_confidence;
            const confTone = conf >= 80 ? 'success' : conf >= 50 ? 'warning' : 'danger';
            const llmEx = mappingResult.llm_output?.field_extractors;
            const fieldConfidence = llmEx && Object.keys(llmEx).length > 0
              ? Math.round(
                  Object.values(llmEx)
                    .map(f => f.confidence === 'high' ? 100 : f.confidence === 'medium' ? 60 : 30)
                    .reduce((a, b) => a + b, 0) / Object.keys(llmEx).length
                )
              : null;
            const fcTone = fieldConfidence == null ? 'neutral' : fieldConfidence >= 80 ? 'success' : fieldConfidence >= 50 ? 'warning' : 'danger';
            return (
              <div className="metric-row">
                <Metric
                  label="Format"
                  value={mappingResult.format_info?.detected_type ?? '—'}
                  tone={
                    mappingResult.format_info?.detected_type === 'FIXED_WIDTH' ? 'success'
                      : mappingResult.format_info?.detected_type === 'DELIMITED' ? 'info'
                      : 'neutral'
                  }
                />
                <Metric label="Record prefix" value={mappingResult.format_info?.record_prefix ?? '—'} />
                <Metric label="Delimiter" value={mappingResult.format_info?.delimiter ?? 'none'} />
                <Metric label="Matched lines" value={mappingResult.match_count ?? '—'} hint={`of ${mappingResult.camt_ref_index_size ?? '?'} CAMT identifiers`} />
                <Metric
                  label="Pattern confidence"
                  value={conf != null ? `${conf}%` : '—'}
                  hint="match ratio × structural clarity"
                  tone={conf != null ? confTone : 'neutral'}
                />
                <Metric
                  label="LLM samples sent"
                  value={mappingResult.llm_samples_sent ?? mappingResult.examples?.length ?? '—'}
                  hint="entry pairs in prompt"
                />
                {fieldConfidence != null && (
                  <Metric
                    label="Field confidence"
                    value={`${fieldConfidence}%`}
                    hint="avg across extracted fields"
                    tone={fcTone}
                  />
                )}
              </div>
            );
          })()}

          {/* ── field extractors ──────────────────────────────── */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: '1.5rem 0 0.5rem' }}>
            <h4 style={{ margin: 0 }}>Field extractors</h4>
            {mappingResult.llm_available
              ? <Tag tone="success">LLM</Tag>
              : <Tag tone="neutral">structural</Tag>}
          </div>
          <div className="table-wrap compact tight">
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Regex</th>
                  <th>Maps to CAMT</th>
                  <th>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const llmEx = mappingResult.llm_output?.field_extractors;
                  const structural = mappingResult.format_info?.suggested_regex_map;
                  if (llmEx && Object.keys(llmEx).length > 0) {
                    return Object.entries(llmEx).map(([field, info]) => (
                      <tr key={field}>
                        <td><code>{field}</code></td>
                        <td><pre style={{ margin: 0, fontSize: '0.73rem', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{info.regex}</pre></td>
                        <td><code style={{ fontSize: '0.78rem' }}>{info.maps_to_camt}</code></td>
                        <td><Tag tone={info.confidence === 'high' ? 'success' : info.confidence === 'medium' ? 'warning' : 'danger'}>{info.confidence}</Tag></td>
                      </tr>
                    ));
                  }
                  if (structural && Object.keys(structural).length > 0) {
                    return Object.entries(structural).map(([field, pattern]) => (
                      <tr key={field}>
                        <td><code>{field}</code></td>
                        <td><pre style={{ margin: 0, fontSize: '0.73rem', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{pattern}</pre></td>
                        <td>—</td>
                        <td><Tag tone="neutral">structural</Tag></td>
                      </tr>
                    ));
                  }
                  return (
                    <tr>
                      <td colSpan={4} className="empty">
                        {mappingResult.llm_error
                          ? `LLM unavailable — ${mappingResult.llm_error}`
                          : 'No field extractors available.'}
                      </td>
                    </tr>
                  );
                })()}
              </tbody>
            </table>
          </div>

          {/* ── LLM layout explanation ────────────────────────── */}
          {mappingResult.llm_output?.explanation && (
            <p style={{ marginTop: '1rem', color: 'var(--text-muted, #888)', fontSize: '0.83rem' }}>
              <strong>Layout: </strong>{mappingResult.llm_output.explanation}
            </p>
          )}

          {/* ── matched CAMT / flat-file pairs ────────────────── */}
          {mappingResult.examples?.length > 0 && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: '1.5rem 0 0.5rem' }}>
                <h4 style={{ margin: 0 }}>Matched entry pairs</h4>
                <Tag tone="neutral">{mappingResult.examples.length}</Tag>
              </div>
              <div className="table-wrap compact tight">
                <table>
                  <thead>
                    <tr>
                      <th>CAMT entry</th>
                      <th>Identifiers found</th>
                      <th>Matched flat-file line</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mappingResult.examples.map((ex, idx) => (
                      <tr key={idx}>
                        <td>
                          <code style={{ fontWeight: 600 }}>{ex.ntry_ref}</code>
                          {ex.pmt_ref && <div style={{ fontSize: '0.74rem', opacity: 0.7 }}>PMT-REF: {ex.pmt_ref}</div>}
                          {ex.invoice && <div style={{ fontSize: '0.74rem', opacity: 0.7 }}>INV: {ex.invoice}</div>}
                          <div style={{ fontSize: '0.74rem', opacity: 0.7 }}>{ex.amount} {ex.currency} · {ex.direction}</div>
                        </td>
                        <td>
                          {Object.entries(ex.refs || {}).map(([tag, val]) => (
                            <div key={tag} style={{ fontSize: '0.74rem' }}>
                              <span style={{ opacity: 0.55 }}>{tag}: </span><code>{val}</code>
                            </div>
                          ))}
                        </td>
                        <td>
                          {ex.matched_text?.length > 0 ? (
                            <pre style={{ margin: 0, fontSize: '0.68rem', whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxWidth: '48ch' }}>
                              {ex.matched_text[0]}
                            </pre>
                          ) : (
                            <span className="empty">no match</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Panel>
      )}

      {/* ── Deterministic pattern results ─────────────────────── */}
      {patternResult?.deterministic_patterns?.length > 0 && (
        <Panel title="Deterministic patterns" subtitle="Rules that fired — each entry matched at most once, in priority order.">
          <div className="table-wrap compact tight">
            <table>
              <thead>
                <tr>
                  <th>Rule</th>
                  <th>Pattern name</th>
                  <th>Fields used</th>
                  <th>Matched</th>
                  <th>Sample pair</th>
                </tr>
              </thead>
              <tbody>
                {patternResult.deterministic_patterns.map((p) => (
                  <tr key={p.rule}>
                    <td><Tag tone="success">{p.rule}</Tag></td>
                    <td>{p.pattern_name}</td>
                    <td>{(p.fields_used || []).map(f => <code key={f} style={{ marginRight: '0.25rem' }}>{f}</code>)}</td>
                    <td style={{ fontWeight: 600 }}>{p.matched_count}</td>
                    <td style={{ fontSize: '0.74rem' }}>
                      {p.sample_pairs?.[0] ? (
                        <span>
                          <code>{p.sample_pairs[0].camt_id}</code>
                          {' ↔ '}
                          <code>{p.sample_pairs[0].flat_tx_id || p.sample_pairs[0].flat_reference || `line ${p.sample_pairs[0].flat_line_no}`}</code>
                        </span>
                      ) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {patternResult.all_deterministic_rules?.filter(r => r.matched_count === 0).length > 0 && (
            <details style={{ marginTop: '0.75rem', fontSize: '0.8rem', color: 'var(--text-muted,#888)' }}>
              <summary style={{ cursor: 'pointer' }}>Rules that did not fire ({patternResult.all_deterministic_rules.filter(r => r.matched_count === 0).length})</summary>
              <ul style={{ margin: '0.25rem 0 0 1rem' }}>
                {patternResult.all_deterministic_rules.filter(r => r.matched_count === 0).map(r => (
                  <li key={r.rule}>{r.pattern_name} — <em>0 matches</em></li>
                ))}
              </ul>
            </details>
          )}
        </Panel>
      )}

      {/* ── LLM-suggested patterns for unmatched ────────────── */}
      {patternResult && (patternResult.llm_patterns?.length > 0 || patternResult.unmatched_count > 0) && (
        <Panel
          title={`LLM-suggested patterns for unmatched (${patternResult.unmatched_count ?? 0})`}
          subtitle={patternResult.llm_available ? 'Fuzzy / tolerance-based patterns proposed by LLM' : 'LLM not configured — patterns below are placeholders'}
        >
          {patternResult.llm_patterns?.length > 0 ? (
            <div className="table-wrap compact tight">
              <table>
                <thead>
                  <tr>
                    <th>Rule ID</th>
                    <th>Pattern name</th>
                    <th>Fields used</th>
                    <th>Tolerance</th>
                    <th>Coverage</th>
                    <th>Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {patternResult.llm_patterns.map((p, i) => (
                    <tr key={p.rule_id || i}>
                      <td><code>{p.rule_id}</code></td>
                      <td>{p.pattern_name}</td>
                      <td>{(p.fields_used || []).map(f => <code key={f} style={{ marginRight: '0.25rem' }}>{f}</code>)}</td>
                      <td style={{ fontSize: '0.73rem' }}>
                        {p.tolerance_spec ? <pre style={{ margin: 0 }}>{JSON.stringify(p.tolerance_spec)}</pre> : '—'}
                      </td>
                      <td><Tag tone={p.estimated_coverage === 'high' ? 'success' : p.estimated_coverage === 'medium' ? 'warning' : 'neutral'}>{p.estimated_coverage ?? '—'}</Tag></td>
                      <td><Tag tone={p.confidence === 'high' ? 'success' : p.confidence === 'medium' ? 'warning' : 'danger'}>{p.confidence ?? '—'}</Tag></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty">
              {patternResult.llm_error
                ? `LLM unavailable — ${patternResult.llm_error}`
                : `${patternResult.unmatched_count} unmatched entries. Configure LLM to get fuzzy pattern suggestions.`}
            </p>
          )}

          {patternResult.unmatched_samples?.length > 0 && (
            <details style={{ marginTop: '1rem' }}>
              <summary style={{ cursor: 'pointer', fontSize: '0.83rem' }}>Unmatched CAMT samples ({patternResult.unmatched_samples.length})</summary>
              <div className="table-wrap compact tight" style={{ marginTop: '0.5rem' }}>
                <table>
                  <thead><tr><th>CAMT ID</th><th>Amount</th><th>Direction</th><th>Counterparty</th><th>Remittance</th></tr></thead>
                  <tbody>
                    {patternResult.unmatched_samples.map((s, i) => (
                      <tr key={i}>
                        <td><code>{s.camt_id}</code></td>
                        <td>{s.amount} {s.currency}</td>
                        <td>{s.direction}</td>
                        <td style={{ fontSize: '0.78rem' }}>{s.counterparty}</td>
                        <td style={{ fontSize: '0.75rem', maxWidth: '30ch', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.remittance}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </Panel>
      )}

      <Panel title="Proposed pattern candidates" subtitle="Select and edit candidate patterns before saving.">

      {/* ── Save as pattern group ──────────────────────────── */}
      {patternResult && ((patternResult.deterministic_patterns?.length ?? 0) + (patternResult.llm_patterns?.length ?? 0)) > 0 && (() => {
        // Constants for converting analysis output → registry format
        const DET_EXEC = { EXACT_E2E: 'AUTO_CLOSE', EXACT_PMT_REF: 'AUTO_CLOSE', EXACT_INVOICE: 'SUGGESTION', AMOUNT_DIRECTION: 'SUGGESTION' };
        const DET_CONF = { EXACT_E2E: 0.95, EXACT_PMT_REF: 0.92, EXACT_INVOICE: 0.90, AMOUNT_DIRECTION: 0.80 };

        const allSaveable = [
          ...(patternResult.deterministic_patterns || []).map(p => ({
            key: `det-${p.rule}`, label: p.pattern_name, badge: 'Deterministic', badgeTone: 'success',
            toPayload: () => ({
              pattern_name: p.pattern_name, pattern_type: 'FILE_DETECTED', pattern_version: '1.0',
              pattern_rule: { fields: p.fields_used || [], mode: 'AUTO' },
              status: 'ACTIVE', execution_mode: DET_EXEC[p.rule] || 'SUGGESTION',
              confidence_threshold: DET_CONF[p.rule] ?? 0.80, approved_by: 'prototype_user',
            }),
          })),
          ...(patternResult.llm_patterns || []).map((p, i) => ({
            key: `llm-${p.rule_id || i}`, label: p.pattern_name, badge: 'LLM suggested', badgeTone: 'warning',
            toPayload: () => ({
              pattern_name: p.pattern_name, pattern_type: 'LLM_SUGGESTED', pattern_version: '1.0',
              pattern_rule: { fields: p.fields_used || [], mode: 'SUGGESTION', ...(p.tolerance_spec || {}) },
              status: 'DRAFT', execution_mode: 'SUGGESTION',
              confidence_threshold: 0.75, approved_by: 'prototype_user',
            }),
          })),
        ];

        const allSelected = allSaveable.every(item => selectedGroupPatterns.has(item.key));
        const someSelected = allSaveable.some(item => selectedGroupPatterns.has(item.key));

        const toggleAll = () => {
          if (allSelected) setSelectedGroupPatterns(new Set());
          else setSelectedGroupPatterns(new Set(allSaveable.map(i => i.key)));
        };
        const toggleOne = (key) => {
          setSelectedGroupPatterns(prev => {
            const next = new Set(prev);
            next.has(key) ? next.delete(key) : next.add(key);
            return next;
          });
        };

        const saveBulk = async () => {
          if (!groupName.trim()) { setBulkSaveStatus({ error: 'Group name cannot be blank.' }); return; }
          const toSave = allSaveable.filter(i => selectedGroupPatterns.has(i.key)).map(i => i.toPayload());
          if (!toSave.length) { setBulkSaveStatus({ error: 'Select at least one pattern.' }); return; }
          setBulkSaveStatus({ loading: true });
          try {
            const res = await onSaveBulk(groupName.trim(), toSave);
            setBulkSaveStatus({ success: `Saved ${res.created} pattern(s) to group "${res.group_name}".${res.skipped > 0 ? ` (${res.skipped} already existed, skipped)` : ''}` });
          } catch (err) {
            setBulkSaveStatus({ error: err.message || 'Failed to save patterns.' });
          }
        };

        return (
          <Panel
            title="Save as pattern group"
            subtitle="Pick which patterns to persist, give the group a name, then save them all at once."
          >
            {/* group name */}
            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginBottom: '1rem' }}>
              <label style={{ fontWeight: 600, whiteSpace: 'nowrap', fontSize: '0.85rem' }}>Group name</label>
              <input
                type="text"
                value={groupName}
                onChange={e => { setGroupName(e.target.value); setBulkSaveStatus(null); }}
                placeholder="e.g. psr-camt-2026-q3"
                style={{ flex: 1, padding: '0.35rem 0.6rem', borderRadius: '4px', border: '1px solid var(--border, #ccc)', fontFamily: 'monospace', fontSize: '0.85rem' }}
              />
            </div>

            {/* pattern checklist */}
            <div className="table-wrap compact tight">
              <table>
                <thead>
                  <tr>
                    <th style={{ width: '2rem' }}>
                      <input
                        type="checkbox"
                        checked={allSelected}
                        ref={el => { if (el) el.indeterminate = !allSelected && someSelected; }}
                        onChange={toggleAll}
                        title="Select / deselect all"
                      />
                    </th>
                    <th>Pattern name</th>
                    <th>Origin</th>
                    <th>Registry rule stored as</th>
                    <th>Mode</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {allSaveable.map(item => {
                    const payload = item.toPayload();
                    return (
                      <tr key={item.key}>
                        <td><input type="checkbox" checked={selectedGroupPatterns.has(item.key)} onChange={() => toggleOne(item.key)} /></td>
                        <td>{item.label}</td>
                        <td><Tag tone={item.badgeTone}>{item.badge}</Tag></td>
                        <td style={{ fontSize: '0.73rem' }}>
                          <code>{(payload.pattern_rule.fields || []).join(', ') || '—'}</code>
                        </td>
                        <td><Tag tone={payload.execution_mode === 'AUTO_CLOSE' ? 'success' : 'warning'}>{payload.execution_mode}</Tag></td>
                        <td><Tag tone={payload.status === 'ACTIVE' ? 'success' : 'neutral'}>{payload.status}</Tag></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="button-row" style={{ marginTop: '1rem' }}>
              <button
                className="btn primary"
                onClick={saveBulk}
                disabled={!someSelected || bulkSaveStatus?.loading}
              >
                {bulkSaveStatus?.loading ? 'Saving…' : `Save ${[...selectedGroupPatterns].length} pattern(s) to group`}
              </button>
              {bulkSaveStatus?.success && (
                <span style={{ color: 'var(--success, #16a34a)', fontSize: '0.84rem' }}>{bulkSaveStatus.success}</span>
              )}
              {bulkSaveStatus?.error && (
                <span style={{ color: 'var(--danger, #dc2626)', fontSize: '0.84rem' }}>{bulkSaveStatus.error}</span>
              )}
            </div>
          </Panel>
        );
      })()}

        <div className="table-wrap compact tight">
          <table>
            <thead>
              <tr><th>Name</th><th>Mapping key</th><th>Regex</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {proposedPatterns.length ? proposedPatterns.map((pattern, idx) => (
                <tr key={idx}>
                  <td>{pattern.pattern_name}</td>
                  <td>{pattern.mapping_key}</td>
                  <td><pre>{JSON.stringify(pattern.regex_inferred, null, 2)}</pre></td>
                  <td className="action-cell">
                    <button className="btn secondary" onClick={() => setSelectedPattern(pattern)}>Edit</button>
                    <button className="btn primary" onClick={savePattern}>Save</button>
                  </td>
                </tr>
              )) : (
                <tr><td colSpan={4} className="empty">No proposed patterns generated yet.</td></tr>
              )}
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
  if (!rule || !rule.startsWith('TIER2C') && !rule.startsWith('AI_DOMAIN') && !rule.startsWith('AI_PENDING')) return null;
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

  const computeAge = (r) => {
    // Age is only meaningful for open/unresolved records.
    const closedStatuses = ['Matched & Settled (Auto-Close)', 'Resolved Manually'];
    if (closedStatuses.includes(r.reconciliation_status)) return null;
    // For matched records where the backend already computed a settlement lag, trust it.
    if (r.aging_days > 0) return { days: r.aging_days, bucket: r.aging_bucket };
    // For unmatched records aging_days is 0 because one date is missing.
    // Compute "days since the oldest available date" so the client can see how stale the item is.
    // Bank-only: use booking_date (bank entry exists, no PSR).
    // In-Transit / exceptions: use value_date (PSR exists, no bank match yet).
    const dateStr = r.value_date || r.booking_date;
    if (!dateStr) return null;
    const days = Math.floor((Date.now() - new Date(dateStr.slice(0, 10)).getTime()) / 86400000);
    if (days < 0) return null;
    const bucket = days <= 1 ? '0-1 Days' : days <= 2 ? '2 Days' : days <= 5 ? '3-5 Days' : '6+ Days';
    return { days, bucket };
  };

  const agingTone = (bucket) => {
    if (!bucket) return 'neutral';
    if (bucket.startsWith('6+')) return 'danger';
    if (bucket.startsWith('3-5') || bucket.startsWith('2')) return 'warning';
    return 'info';
  };

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
            <SortTh col="aging_days" label="Age" {...sp} />
            <SortTh col="match_confidence" label="Confidence" {...sp} />
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const age = computeAge(r);
            return (
              <tr key={r.result_id} onClick={() => onSelect?.(r)} className="clickable">
                <td><strong>{r.result_id}</strong><AiPill rule={r.rule_applied} /><br/><span className="muted">{r.psr_id || '-'} / {r.camt_id || '-'}</span></td>
                <td>{money(r.internal_amount)}</td>
                <td>{money(r.bank_amount)}</td>
                <td>{r.reference || '-'}</td>
                <td>{r.counterparty || '-'}</td>
                <td className={varianceTone(r.variance)}>{r.variance != null ? money(r.variance) : '-'}</td>
                <td><Tag tone={classForStatus(r.reconciliation_status)}>{r.reconciliation_status}</Tag></td>
                <td>
                  {age
                    ? <Tag tone={agingTone(age.bucket)} title={age.bucket}>{age.days}d</Tag>
                    : <span className="muted">-</span>}
                </td>
                <td><div className="mini-score"><span style={{ width: `${r.match_confidence || 0}%` }} />{r.match_confidence}%</div></td>
              </tr>
            );
          })}
          {!sorted.length && <tr><td colSpan="9" className="empty">No records to display.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function FieldDiff({ item }) {
  const fmt = (v) => (v == null || v === '') ? '\u2014' : String(v);
  const mismatch = (a, b) => a != null && a !== '' && b != null && b !== '' && String(a).trim() !== String(b).trim();
  const isValidId = (id) => Boolean(id && id.trim() && !['NOT FOUND', 'N/A', 'NONE', 'NULL'].includes(id.trim().toUpperCase()));
  const hasPsr = Boolean(item.psr_id);
  const hasCamtData = item.bank_amount != null;
  const fields = [
    {
      key: 'id',
      label: 'ID',
      psr: hasPsr && isValidId(item.psr_id)
        ? <a className="source-link" href={`#psr-${item.psr_id}`}>{item.psr_id}</a>
        : fmt(hasPsr ? item.psr_id : null),
      camt: hasCamtData && isValidId(item.camt_id)
        ? <a className="source-link" href={`#camt-${item.camt_id}`}>{item.camt_id}</a>
        : fmt(hasCamtData ? item.camt_id : null),
      psrRaw: hasPsr ? item.psr_id : null,
      camtRaw: hasCamtData ? item.camt_id : null,
    },
    { key: 'amount', label: 'Amount', psr: fmt(hasPsr ? item.internal_amount : null), camt: fmt(hasCamtData ? item.bank_amount : null), psrRaw: hasPsr ? item.internal_amount : null, camtRaw: hasCamtData ? item.bank_amount : null },
    { key: 'direction', label: 'Direction', psr: fmt(hasPsr ? item.psr_direction : null), camt: fmt(hasCamtData ? item.camt_direction : null), psrRaw: hasPsr ? item.psr_direction : null, camtRaw: hasCamtData ? item.camt_direction : null },
    { key: 'date', label: 'Date', psr: fmt(hasPsr ? item.value_date : null), camt: fmt(hasCamtData ? item.booking_date : null), psrRaw: hasPsr ? item.value_date : null, camtRaw: hasCamtData ? item.booking_date : null },
    { key: 'reference', label: 'Reference', psr: fmt(hasPsr ? item.reference : null), camt: fmt(hasCamtData ? item.camt_pmt_ref : null), psrRaw: hasPsr ? item.reference : null, camtRaw: hasCamtData ? item.camt_pmt_ref : null },
    { key: 'counterparty', label: 'Counterparty', psr: fmt(hasPsr ? item.counterparty : null), camt: fmt(hasCamtData ? item.camt_counterparty : null), psrRaw: hasPsr ? item.counterparty : null, camtRaw: hasCamtData ? item.camt_counterparty : null },
    { key: 'invoice', label: 'Invoice', psr: fmt(hasPsr ? item.invoice : null), camt: fmt(hasCamtData ? item.camt_invoice : null), psrRaw: hasPsr ? item.invoice : null, camtRaw: hasCamtData ? item.camt_invoice : null },
    { key: 'remittance', label: 'Remittance', psr: fmt(null), camt: fmt(hasCamtData ? item.camt_remittance : null), psrRaw: null, camtRaw: hasCamtData ? item.camt_remittance : null },
  ];
  return (
    <div className="field-diff field-diff-transposed">
      <div className="field-diff-scroll">
        <table className="field-diff-table">
          <thead>
            <tr>
              <th>Source</th>
              {fields.map((f) => <th key={f.key}>{f.label}</th>)}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">PSR (Internal)</th>
              {fields.map((f) => <td key={`psr-${f.key}`} className={mismatch(f.psrRaw, f.camtRaw) ? 'mismatch' : ''}>{f.psr}</td>)}
            </tr>
            <tr>
              <th scope="row">Bank (CAMT)</th>
              {fields.map((f) => <td key={`camt-${f.key}`} className={mismatch(f.psrRaw, f.camtRaw) ? 'mismatch' : ''}>{f.camt}</td>)}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EvidenceDrawer({ selected, onClose, onResolve, onRefresh, rows = [], selectedIndex = -1, onPrev, onNext, onSelect, batchAvg = null }) {
  const [detail, setDetail] = useState(null);
  const [overrideMode, setOverrideMode] = useState(false);
  const [overrideReason, setOverrideReason] = useState('');
  const [overrideNote, setOverrideNote] = useState('');
  const [overrideLoading, setOverrideLoading] = useState(false);
  const [similarCases, setSimilarCases] = useState(null);
  const [similarOpen, setSimilarOpen] = useState(false);
  const [noMatchLoading, setNoMatchLoading] = useState(null);
  const [drawerFilter, setDrawerFilter] = useState('all');
  const [shortcutsHidden, setShortcutsHidden] = useState(() => localStorage.getItem('hideDrawerShortcuts') === '1');

  const filteredRows = useMemo(() => {
    switch (drawerFilter) {
      case 'low': return rows.filter(r => r.match_confidence != null && r.match_confidence < 60);
      case 'ai':  return rows.filter(r => r.rule_applied?.startsWith('TIER2'));
      default:    return rows;
    }
  }, [rows, drawerFilter]);

  const filteredIndex = filteredRows.findIndex(r => r.result_id === selected?.result_id);

  const goTo = (delta) => {
    const next = filteredRows[filteredIndex + delta];
    if (next && onSelect) onSelect(next);
    else if (delta === -1) onPrev?.();
    else onNext?.();
  };

  useEffect(() => {
    if (!selected?.result_id) {
      setDetail(null); setOverrideMode(false); setOverrideReason(''); setOverrideNote('');
      setSimilarCases(null); setSimilarOpen(false);
      setDrawerFilter('all');
      return;
    }
    setDetail(null);
    setOverrideMode(false);
    setOverrideReason('');
    setOverrideNote('');
    setSimilarCases(null);
    setSimilarOpen(false);
    setNoMatchLoading(null);
    api.caseDetail(selected.result_id).then(d => setDetail(d.case)).catch(() => {});
    api.similarCases(selected.result_id).then(setSimilarCases).catch(() => setSimilarCases({ items: [], count: 0 }));
  }, [selected?.result_id]);

  useEffect(() => {
    if (!selected) return;
    const MATCH_STATUSES_KB = ['Suggested Match - Analyst Review', 'Suggested Match - Learned Pattern', 'Exception - Amount Variance Review', 'Post to Short or Over Ledger', 'AI-Assisted Suggested Match', 'AI - Analyst Adjudication Required'];
    const handler = (e) => {
      const tag = document.activeElement?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      if (e.key === 'ArrowLeft')  { e.preventDefault(); goTo(-1); }
      if (e.key === 'ArrowRight') { e.preventDefault(); goTo(1); }
      if (e.key === 'Escape')     { onClose(); }
      if ((e.key === 'r' || e.key === 'R') && !overrideMode) {
        const item = detail ? { ...selected, ...detail } : selected;
        if (MATCH_STATUSES_KB.includes(item.reconciliation_status)) { e.preventDefault(); onResolve(item); }
      }
      if ((e.key === 'o' || e.key === 'O') && !overrideMode) {
        const item = detail ? { ...selected, ...detail } : selected;
        if (MATCH_STATUSES_KB.includes(item.reconciliation_status)) { e.preventDefault(); setOverrideMode(true); }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [selected, detail, overrideMode, filteredIndex, filteredRows, onSelect, onPrev, onNext, onClose, onResolve]);

  const submitNoMatch = async (resolutionType, reasonCode) => {
    setNoMatchLoading(resolutionType);
    try {
      await api.noMatchResolve(selected.result_id, resolutionType, reasonCode);
      onClose();
      onRefresh?.();
    } catch (e) {
      alert(e.message);
    } finally {
      setNoMatchLoading(null);
    }
  };
  const submitOverride = async () => {
    if (!overrideReason) return;
    setOverrideLoading(true);
    try {
      await api.overrideResolve(selected.result_id, overrideReason, overrideNote);
      onClose();
      onRefresh?.();
    } finally {
      setOverrideLoading(false);
    }
  };
  if (!selected) return null;
  const item = detail ? { ...selected, ...detail } : selected;
  const score = item.feature_snapshot?.score_breakdown || {};
  const components = score.components || [];
  const suggestions = item.suggestions || [];
  const hasMatch = item.bank_amount != null || item.camt_id;
  const total = rows.length;
  return (
    <>
      <div className="evidence-modal-backdrop" onClick={onClose} />
      <div className="evidence-modal-wrap" role="dialog" aria-modal="true" aria-label="Match evidence details">
      <aside className="evidence-modal">
        <div className="drawer-nav">
          <button className="btn ghost" disabled={filteredIndex <= 0} onClick={() => goTo(-1)}>← Prev</button>
          <span className="drawer-nav-counter">
            {filteredIndex >= 0 ? `${filteredIndex + 1} / ${filteredRows.length}` : `0 / ${filteredRows.length}`}
            {drawerFilter !== 'all' && <span className="filter-badge">{drawerFilter === 'low' ? 'Low conf' : 'AI'}</span>}
          </span>
          <div className="drawer-filter-pills">
            {['all', 'low', 'ai'].map(f => (
              <button key={f} className={`filter-pill${drawerFilter === f ? ' active' : ''}`} onClick={() => {
                setDrawerFilter(f);
                const newFiltered = f === 'low' ? rows.filter(r => r.match_confidence != null && r.match_confidence < 60)
                  : f === 'ai' ? rows.filter(r => r.rule_applied?.startsWith('TIER2')) : rows;
                if (newFiltered.length > 0 && !newFiltered.find(r => r.result_id === selected?.result_id)) {
                  onSelect?.(newFiltered[0]);
                }
              }}>
                {f === 'all' ? 'All' : f === 'low' ? 'Low conf' : 'AI'}
                <span className="pill-count">{(f === 'low' ? rows.filter(r => r.match_confidence != null && r.match_confidence < 60) : f === 'ai' ? rows.filter(r => r.rule_applied?.startsWith('TIER2')) : rows).length}</span>
              </button>
            ))}
          </div>
          <button className="btn ghost" disabled={filteredIndex < 0 || filteredIndex >= filteredRows.length - 1} onClick={() => goTo(1)}>Next →</button>
          <button className="btn ghost" onClick={onClose}>Close</button>
        </div>
        <div className="drawer-body">
          <div className="eyebrow">Match evidence</div>
          <h2>{selected.result_id}</h2>
          <p>{selected.explanation}</p>
          <dl className="kv drawer-kv">
            <dt>Status</dt><dd><Tag tone={classForStatus(item.reconciliation_status)}>{item.reconciliation_status}</Tag></dd>
            <dt>Rule applied</dt><dd>
              {ruleLabel(item.rule_applied) || '-'}
              {item.rule_applied && <span className="rule-code">{item.rule_applied}</span>}
            </dd>
            <dt>Reason</dt><dd>{item.reason_code || '-'}</dd>
            {item.variance != null && <><dt>Variance</dt><dd>{money(item.variance)}</dd></>}
          </dl>
          {hasMatch && <FieldDiff item={item} />}
          <Panel title="Why this decision?" className="nested-panel">
            {(() => {
              const NO_COMPARISON_STATUSES = ['Uncleared / In-Transit Payment', 'Bank-only Item - Investigation'];
              const isAiConfirmedNoMatch = item.reconciliation_status === 'AI Confirmed — No Match';
              const isNoComparison = NO_COMPARISON_STATUSES.includes(item.reconciliation_status);
              if (isAiConfirmedNoMatch) {
                const candidatesReviewed = item.feature_snapshot?.candidates_reviewed || [];
                return (
                  <>
                    <p className="no-match-explanation">
                      AI reviewed all available candidates and found no credible match.
                      {item.explanation ? ` ${item.explanation}` : ''}
                    </p>
                    <p className="no-match-explanation" style={{ marginTop: '0.5rem', color: 'var(--muted, #64748b)', fontStyle: 'italic' }}>
                      If the bank posting is delayed, this payment may be matched in the next CAMT statement cycle. If it remains unmatched, route to the exception queue for investigation.
                    </p>
                    <div style={{ marginTop: '1rem', background: 'var(--bg, #f8fafc)', border: '1px solid var(--line, #e2e8f0)', borderRadius: '6px', padding: '0.5rem 0.75rem', fontSize: '0.8rem' }}>
                      <p style={{ fontSize: '0.72rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--muted, #64748b)', marginBottom: '0.35rem' }}>PSR (Internal)</p>
                      <div style={{ color: '#334155', fontWeight: 600 }}>{item.counterparty || '—'}</div>
                      <div style={{ marginTop: '0.15rem', color: '#475569' }}>
                        {item.internal_amount != null && <span>{item.currency || ''} {Number(item.internal_amount).toLocaleString('en-EU', {minimumFractionDigits:2})}</span>}
                        {item.value_date && <span style={{ marginLeft: '0.75rem', color: 'var(--muted)' }}>{item.value_date}</span>}
                        {item.reference && <span style={{ marginLeft: '0.75rem', color: 'var(--muted)', fontFamily: 'monospace', fontSize: '0.72rem' }}>{item.reference}</span>}
                      </div>
                      {item.invoice && <div style={{ marginTop: '0.1rem', color: 'var(--muted)', fontSize: '0.72rem' }}>Invoice: {item.invoice}</div>}
                    </div>
                    {candidatesReviewed.length > 0 && (
                      <div style={{ marginTop: '0.75rem' }}>
                        <p style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--muted, #64748b)', marginBottom: '0.5rem' }}>Candidates reviewed ({candidatesReviewed.length})</p>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                          {candidatesReviewed.map((c, i) => (
                            <div key={i} style={{ background: 'var(--bg, #f8fafc)', border: '1px solid var(--line, #e2e8f0)', borderRadius: '6px', padding: '0.5rem 0.75rem', fontSize: '0.8rem' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '0.5rem' }}>
                                <span style={{ fontWeight: 600, fontFamily: 'monospace', color: '#475569' }}>{c.camt_id}</span>
                                <span style={{ color: 'var(--muted)', fontSize: '0.72rem' }}>domain score {c.domain_score != null ? (c.domain_score * 100).toFixed(0) : '—'}%</span>
                              </div>
                              <div style={{ marginTop: '0.2rem', color: '#334155' }}>
                                {c.counterparty || <em style={{color:'var(--muted)'}}>no counterparty</em>}
                                {c.amount != null && <span style={{ marginLeft: '0.75rem', color: 'var(--muted)' }}>{c.currency} {Number(c.amount).toLocaleString('en-EU', {minimumFractionDigits:2})}</span>}
                                {c.date && <span style={{ marginLeft: '0.75rem', color: 'var(--muted)' }}>{c.date}</span>}
                              </div>
                              {c.remittance && <div style={{ marginTop: '0.15rem', color: 'var(--muted)', fontStyle: 'italic', fontSize: '0.72rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.remittance}</div>}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                );
              }
              if (isNoComparison) {
                return (
                  <p className="no-match-explanation">
                    All matching rules were applied — no {item.reconciliation_status === 'Bank-only Item - Investigation' ? 'PSR payment entry could be paired with this bank transaction' : 'bank transaction could be paired with this PSR entry'}.
                    {item.explanation ? ` ${item.explanation}` : ' The item has been queued for monitoring on the next CAMT cycle.'}
                  </p>
                );
              }
              return (
              <>
              <div className="score-labelled">
                <p className="score-label">{ruleLabel(score.rule_applied || item.rule_applied) || 'Rule decision confidence'}</p>
                <div className="score-bar-row">
                  <div className="score-large"><span style={{ width: `${score.engine_confidence ?? item.match_confidence ?? 0}%` }} /></div>
                  <span className="score-pct">{score.engine_confidence ?? item.match_confidence ?? 0}%</span>
                </div>
                <p className="confidence-field-summary">
                  {(() => {
                    const passed = components.filter(c => c.passed);
                    const total = components.length;
                    const fieldScore = total ? Math.round(passed.reduce((s, c) => s + c.weight, 0)) : null;
                    const engineConf = score.engine_confidence ?? item.match_confidence ?? 0;
                    const overridden = total > 0 && fieldScore !== null && fieldScore !== engineConf;
                    if (total > 0) {
                      return overridden
                        ? `Field evidence: ${passed.length} / ${total} fields matched (${fieldScore}% weighted score — rule override to ${engineConf}% due to variance)`
                        : `Field evidence: ${passed.length} / ${total} fields matched (${fieldScore}% weighted score)`;
                    }
                    return score.decision_basis || 'Evidence breakdown captured by the engine.';
                  })()}
                </p>
                {batchAvg != null && item.match_confidence != null && (
                  <p className={`confidence-trend${item.match_confidence < batchAvg - 20 ? ' outlier' : ''}`}>
                    Batch avg: {batchAvg.toFixed(0)}% —{' '}
                    {item.match_confidence < batchAvg - 20
                      ? '⚠ Low outlier — significantly below batch average'
                      : item.match_confidence < batchAvg
                        ? 'this item is below average'
                        : 'this item is above average'}
                  </p>
                )}
              </div>
              <div className="evidence-list">
                {components.map((c) => (
                  <div className="evidence" key={c.component}>
                    <Tag tone={c.passed ? 'success' : (c.weight >= 30 ? 'danger' : 'warning')}>
                      {c.passed ? 'Pass' : (c.weight >= 30 ? 'Fail' : 'Low')}
                    </Tag>
                    <strong>{c.component}</strong>
                    <span className="evidence-score" title="Points scored / points available">{c.passed ? c.weight : 0}&nbsp;/&nbsp;{c.weight}</span>
                    <p>{c.evidence}</p>
                  </div>
                ))}
                {!components.length && <p className="empty small">No field-level evidence stored.</p>}
              </div>
              </>
              );
            })()}
          </Panel>
{suggestions.length > 0 && item.reconciliation_status !== 'AI Confirmed — No Match' && (
          <Panel title="Suggested actions" className="nested-panel">
            <div className="action-stack">
              {suggestions.map((s, idx) => {
                const cfg = actionConfig(s.action);
                return (
                  <div className={`suggestion suggestion-${cfg.tone}`} key={idx}>
                    <strong>{cfg.label}</strong>
                    {cfg.desc && <p className="suggestion-desc">{cfg.desc}</p>}
                  </div>
                );
              })}
            </div>
          </Panel>
)}
          {similarCases?.count > 0 && (
            <div className="nested-panel similar-panel">
              <button className="similar-header" onClick={() => setSimilarOpen(o => !o)}>
                <span>{similarCases.count} similar resolved case{similarCases.count !== 1 ? 's' : ''}</span>
                <span className="similar-chevron">{similarOpen ? '▲' : '▼'}</span>
              </button>
              {similarOpen && (
                <div className="similar-list">
                  {similarCases.items.map(s => (
                    <div className="similar-item" key={s.case_id}>
                      <span className="similar-rule">{ruleLabel(s.rule_applied)}</span>
                      <Tag tone={classForStatus(s.reconciliation_status)}>{s.reconciliation_status}</Tag>
                      <span className="similar-date">{s.updated_at?.slice(0, 10) || ''}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
        {item.exception_flag === 'Y' && (() => {
          const MATCH_STATUSES = [
            'Suggested Match - Analyst Review',
            'Suggested Match - Learned Pattern',
            'Exception - Amount Variance Review',
            'Post to Short or Over Ledger',
          ];
          const NO_MATCH_STATUSES = [
            'Uncleared / In-Transit Payment',
            'Bank-only Item - Investigation',
          ];
          const isMatch = MATCH_STATUSES.includes(item.reconciliation_status);
          const isNoMatch = NO_MATCH_STATUSES.includes(item.reconciliation_status);
          const isBankOnly = item.reconciliation_status === 'Bank-only Item - Investigation';
          const isLedgerPost = item.reconciliation_status === 'Post to Short or Over Ledger';
          const isAiSuggested = item.reconciliation_status === 'AI-Assisted Suggested Match';
          const isAiReview = item.reconciliation_status === 'AI - Analyst Adjudication Required';
          const isAiNoMatch = item.reconciliation_status === 'AI Confirmed — No Match';

          if (!isMatch && !isNoMatch && !isAiSuggested && !isAiReview && !isAiNoMatch && !overrideMode) return null;

          if (isAiSuggested || isAiReview) {
            if (overrideMode) {
              return (
                <div className="drawer-footer">
                  <div className="override-panel">
                    <label className="override-label">Reason for override</label>
                    <select
                      className="override-select"
                      value={overrideReason}
                      onChange={e => setOverrideReason(e.target.value)}
                    >
                      <option value="">— Select a reason —</option>
                      <option value="same_entity_diff_name">Same entity, different name format</option>
                      <option value="known_alias">Known counterparty alias</option>
                      <option value="data_entry_error">Data entry error in source system</option>
                      <option value="timing_difference">Timing difference (split settlement)</option>
                      <option value="other">Other</option>
                    </select>
                    {overrideReason === 'other' && (
                      <textarea
                        className="override-note"
                        placeholder="Describe the reason..."
                        value={overrideNote}
                        onChange={e => setOverrideNote(e.target.value)}
                        rows={3}
                      />
                    )}
                    <button
                      className="btn primary full"
                      onClick={submitOverride}
                      disabled={!overrideReason || (overrideReason === 'other' && !overrideNote.trim()) || overrideLoading}
                    >
                      {overrideLoading ? 'Submitting\u2026' : 'Submit Override'}
                    </button>
                    <button className="btn link" onClick={() => setOverrideMode(false)}>\u2190 Back</button>
                  </div>
                </div>
              );
            }
            return (
              <div className="drawer-footer">
                <button className="btn primary full" onClick={() => onResolve(item)}>
                  {isAiSuggested ? 'Confirm AI Match' : 'Confirm Match'}
                </button>
                <button className="btn secondary full" onClick={() => setOverrideMode(true)}>Override AI</button>
              </div>
            );
          }

          if (isAiNoMatch) {
            return (
              <div className="drawer-footer no-match-footer">
                <p className="no-match-hint">Route to exception queue — AI found no match; monitor for next CAMT cycle:</p>
                <button
                  className="btn secondary full"
                  disabled={noMatchLoading != null}
                  onClick={() => submitNoMatch('ROUTE_TO_EXCEPTION', 'NO_BANK_MATCH')}
                >
                  {noMatchLoading === 'ROUTE_TO_EXCEPTION' ? 'Routing…' : 'Route to Exception Queue'}
                </button>
              </div>
            );
          }

          if (isNoMatch) {
            return (
              <div className="drawer-footer no-match-footer">
                <p className="no-match-hint">No bank match \u2014 choose how to action this item:</p>
                <button
                  className="btn secondary full"
                  disabled={noMatchLoading != null}
                  onClick={() => submitNoMatch('ROUTE_TO_EXCEPTION', 'NO_BANK_MATCH')}
                >
                  {noMatchLoading === 'ROUTE_TO_EXCEPTION' ? 'Routing\u2026' : 'Route to Exception Queue'}
                </button>
                {!isBankOnly && (
                  <button
                    className="btn ghost full"
                    disabled={noMatchLoading != null}
                    onClick={() => submitNoMatch('POST_TO_LEDGER', 'NO_ACCEPTABLE_CANDIDATES')}
                  >
                    {noMatchLoading === 'POST_TO_LEDGER' ? 'Posting\u2026' : 'Post to Short / Over Ledger'}
                  </button>
                )}
              </div>
            );
          }

          return (
            <div className="drawer-footer">
              {!overrideMode ? (
                <>
                  <button className="btn primary full" onClick={() => onResolve(item)}>
                    {isLedgerPost ? 'Confirm Ledger Post' : 'Confirm Resolution'}
                  </button>
                  <button className="btn secondary full" onClick={() => setOverrideMode(true)}>Override AI</button>
                </>
              ) : (
                <div className="override-panel">
                  <label className="override-label">Reason for override</label>
                  <select
                    className="override-select"
                    value={overrideReason}
                    onChange={e => setOverrideReason(e.target.value)}
                  >
                    <option value="">— Select a reason —</option>
                    <option value="same_entity_diff_name">Same entity, different name format</option>
                    <option value="known_alias">Known counterparty alias</option>
                    <option value="data_entry_error">Data entry error in source system</option>
                    <option value="timing_difference">Timing difference (split settlement)</option>
                    <option value="other">Other</option>
                  </select>
                  {overrideReason === 'other' && (
                    <textarea
                      className="override-note"
                      placeholder="Describe the reason..."
                      value={overrideNote}
                      onChange={e => setOverrideNote(e.target.value)}
                      rows={3}
                    />
                  )}
                  <button
                    className="btn primary full"
                    onClick={submitOverride}
                    disabled={!overrideReason || (overrideReason === 'other' && !overrideNote.trim()) || overrideLoading}
                  >
                    {overrideLoading ? 'Submitting\u2026' : 'Submit Override'}
                  </button>
                  <button className="btn link" onClick={() => setOverrideMode(false)}>\u2190 Back</button>
                </div>
              )}
            </div>
          );
        })()}
        {!shortcutsHidden && (
          <div className="shortcut-legend">
            <span>← → navigate &nbsp;·&nbsp; R confirm &nbsp;·&nbsp; O override &nbsp;·&nbsp; Esc close</span>
            <button className="btn link small" onClick={() => { setShortcutsHidden(true); localStorage.setItem('hideDrawerShortcuts', '1'); }}>hide</button>
          </div>
        )}
      </aside>
      </div>
    </>
  );
}

const ACTION_CONFIG = {
  CONFIRM_AI_MATCH: {
    label: 'Accept AI Match',
    desc:  'Mark this PSR as matched to the suggested bank entry.',
    tone:  'confirm',
  },
  CONFIRM_LEARNED_MATCH: {
    label: 'Accept Learned Match',
    desc:  'A learned pattern suggested this match — confirm to close.',
    tone:  'confirm',
  },
  REVIEW_FUZZY_CANDIDATE: {
    label: 'Review Fuzzy Match',
    desc:  'Counterparty similarity was high but not exact — verify before confirming.',
    tone:  'analyst',
  },
  POST_LEDGER_CANDIDATE: {
    label: 'Post to Short / Over Ledger',
    desc:  'Amount variance is within tolerance — recommend posting the difference to ledger.',
    tone:  'analyst',
  },
  ROUTE_TO_REVIEW: {
    label: 'Route for Variance Review',
    desc:  'Amount variance exceeds tolerance — escalate for manual review.',
    tone:  'analyst',
  },
  ROUTE_TO_EXCEPTION_QUEUE: {
    label: 'Route to Exception Queue',
    desc:  'No bank match found — monitor for next CAMT cycle.',
    tone:  'nomatch',
  },
  INVESTIGATE_BANK_ONLY: {
    label: 'Investigate Bank Entry',
    desc:  'Bank entry received with no matching internal payment — investigate source.',
    tone:  'nomatch',
  },
  ROUTE_TO_ANALYST: {
    label: 'Escalate for Review',
    desc:  'Send to analyst queue for manual verification.',
    tone:  'analyst',
  },
  NO_MATCH: {
    label: 'Mark as No Match',
    desc:  'Record this PSR as unmatched; no bank entry corresponds.',
    tone:  'nomatch',
  },
};
const actionConfig = (code) => ACTION_CONFIG[code] ?? { label: code, desc: '', tone: 'neutral' };

const RULE_LABELS = {
  // Full engine rule codes
  P1_EXACT_END_TO_END_ID:   'EndToEnd ID exact match',
  P2_PMT_REF_AMOUNT:        'PMT reference + amount match',
  P3_INVOICE_USTRD_AMOUNT:  'Invoice + amount match',
  P4_COUNTERPARTY_FUZZY:    'Counterparty fuzzy + amount match',
  P5_EXCEPTION_HANDLING:    'No match found',
  P7_AMOUNT_VARIANCE:       'Amount variance rule',
  P8_LEARNED_INVOICE_SUFFIX:'Learned: invoice suffix match',
  // Short codes (used in kv display)
  P1: 'EndToEnd ID exact match',
  P2: 'PMT reference + amount match',
  P3: 'Invoice + amount match',
  P4: 'Counterparty fuzzy + amount match',
  P5: 'No match found',
  P6: 'One-to-many grouping match',
  P7: 'Amount variance rule',
  // AI triage codes
  AI_DOMAIN_SCORED:     'AI candidate identified — awaiting adjudication',
  AI_PENDING_LLM:       'AI candidate identified — awaiting adjudication',
  TIER2C_LLM:           'AI reviewed — match suggested',
  TIER2C_NO_MATCH:      'AI reviewed — no match found',
  TIER2C_ROUTE_ANALYST: 'AI reviewed — analyst review required',
  TIER2C_CONFIRM:       'AI reviewed — match confirmed',
};
const ruleLabel = (code) => RULE_LABELS[code] ?? code;

const PAGE_SIZE = 100;
const MINOR_VARIANCE_TOLERANCE = 50;

const STATUS_OPTIONS = [
  '',
  'Matched & Settled (Auto-Close)',
  'Resolved Manually',
  'Uncleared / In-Transit Payment',
  'Bank-only Item - Investigation',
  'AI-Assisted Suggested Match',
  'AI - Analyst Adjudication Required',
  'AI Confirmed — No Match',
  'Suggested Match - Analyst Review',
  'Suggested Match - Learned Pattern',
  'Exception - Amount Variance Review',
  'Post to Short or Over Ledger',
];

function SummaryBar({ summary = {}, total = 0, activeFilter, onFilter }) {
  const statuses = summary.statuses || [];
  const statusCount = (match) => statuses
    .filter(s => match(s.reconciliation_status || ''))
    .reduce((acc, s) => acc + (s.count || 0), 0);
  const exceptionCount = summary.raw?.kpi?.exception_count ?? 0;
  const aiSuggestedCount = statusCount(s => s === 'AI-Assisted Suggested Match');
  const aiReviewCount    = statusCount(s => s === 'AI - Analyst Adjudication Required');
  const aiNoMatchCount   = statusCount(s => s === 'AI Confirmed — No Match');
  const aiProcessedCount = aiSuggestedCount + aiReviewCount + aiNoMatchCount;
  const inTransitCount   = statusCount(s => s.includes('In-Transit') || s.includes('Uncleared')) + aiNoMatchCount;
  const bankOnlyCount    = statusCount(s => s === 'Bank-only Item - Investigation');
  // Exceptions = all exception_flag='Y' rows minus In-Transit (non-AI) and Bank-only;
  // AI Suggested + AI Review ARE included as they need analyst action.
  const baseExceptions   = Math.max(0, exceptionCount - statusCount(s => s.includes('In-Transit') || s.includes('Uncleared')) - bankOnlyCount);
  const chips = [
    { label: 'Total',      value: total,          filter: '' },
    { label: 'Matched',    value: statusCount(s => s.includes('Matched') || s.includes('Auto-Close') || s === 'Resolved Manually'), filter: 'matched' },
    { label: 'Exceptions', value: baseExceptions,  filter: 'exceptions' },
    { label: 'In-Transit', value: inTransitCount,  filter: 'in_transit' },
    { label: 'Bank Only',  value: bankOnlyCount,   filter: 'Bank-only Item - Investigation' },
  ];
  const aiActive = activeFilter === 'ai_processed';
  return (
    <div className="summary-bar" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        {chips.map(c => (
          <button key={c.label} className={`chip${activeFilter === c.filter ? ' active' : ''}`} onClick={() => onFilter(c.filter)}>
            <strong>{c.value}</strong><span>{c.label}</span>
          </button>
        ))}
      </div>
      <button
        onClick={() => onFilter(aiActive ? '' : 'ai_processed')}
        style={{
          display: 'flex', alignItems: 'center', gap: '0.4rem',
          padding: '0.35rem 0.85rem',
          borderRadius: '20px',
          border: aiActive ? '1.5px solid #7c3aed' : '1.5px solid #c4b5fd',
          background: aiActive ? '#7c3aed' : '#ede9fe',
          color: aiActive ? '#fff' : '#5b21b6',
          fontWeight: 600, fontSize: '0.82rem', cursor: 'pointer',
          boxShadow: aiActive ? '0 2px 8px rgba(124,58,237,0.25)' : 'none',
          transition: 'all .15s',
          whiteSpace: 'nowrap',
        }}
        title="Filter to all AI-processed records"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
        </svg>
        AI Processed
        <span style={{
          background: aiActive ? 'rgba(255,255,255,0.25)' : '#c4b5fd',
          color: aiActive ? '#fff' : '#5b21b6',
          borderRadius: '10px', padding: '0 6px', fontSize: '0.72rem', fontWeight: 700,
        }}>{aiProcessedCount}</span>
      </button>
    </div>
  );
}

function AiTriageLoader() {
  const steps = [
    { label: 'Scanning unmatched PSR records', duration: 0 },
    { label: 'Running embedding similarity (Tier 2b)', duration: 3000 },
    { label: 'Sending candidates to LLM for adjudication (Tier 2c)', duration: 7000 },
    { label: 'Updating cases and refreshing results', duration: 18000 },
  ];
  const [stepIdx, setStepIdx] = useState(0);
  const [dots, setDots] = useState('');

  useEffect(() => {
    const timers = steps.slice(1).map((s, i) =>
      setTimeout(() => setStepIdx(i + 1), s.duration)
    );
    const dotTimer = setInterval(() => setDots(d => d.length >= 3 ? '' : d + '.'), 500);
    return () => { timers.forEach(clearTimeout); clearInterval(dotTimer); };
  }, []);

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(16,32,51,0.55)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200,
    }}>
      <div style={{
        background: 'var(--panel)', borderRadius: '20px', padding: '2rem 2.5rem',
        maxWidth: '420px', width: '100%', boxShadow: '0 24px 60px rgba(0,0,0,0.25)',
        display: 'flex', flexDirection: 'column', gap: '1.25rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2a10 10 0 1 0 10 10"/><path d="M12 6v6l4 2"/>
          </svg>
          <strong style={{ fontSize: '1rem', color: 'var(--ink)' }}>AI triage running{dots}</strong>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          {steps.map((s, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', opacity: i > stepIdx ? 0.35 : 1 }}>
              {i < stepIdx
                ? <span style={{ color: 'var(--good)', fontSize: '1rem', lineHeight: 1 }}>✓</span>
                : i === stepIdx
                  ? <span style={{ width: '14px', height: '14px', border: '2.5px solid var(--primary)', borderTopColor: 'transparent', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.7s linear infinite' }} />
                  : <span style={{ width: '14px', height: '14px', border: '2px solid var(--line)', borderRadius: '50%', display: 'inline-block' }} />
              }
              <span style={{ fontSize: '0.85rem', color: i === stepIdx ? 'var(--ink)' : 'var(--muted)', fontWeight: i === stepIdx ? 600 : 400 }}>{s.label}</span>
            </div>
          ))}
        </div>
        <p style={{ fontSize: '0.75rem', color: 'var(--muted)', margin: 0 }}>
          LLM adjudication typically takes 10–30 seconds. Results will load automatically.
        </p>
      </div>
    </div>
  );
}

function ResultsWorkbench({ results, summary, selected, setSelected, refreshResults, onAiTriage, onResolve, loading, triageRunning }) {
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
    } else if (filter === 'ai_processed') {
      setSelectedStatus('ai_processed'); setExceptionOnly(false);
      refreshResults({ status: 'ai_processed', exceptionOnly: false, limit: PAGE_SIZE, offset: 0 });
    } else if (filter === 'in_transit') {
      setSelectedStatus('in_transit'); setExceptionOnly(false);
      refreshResults({ status: 'in_transit', exceptionOnly: false, limit: PAGE_SIZE, offset: 0 });
    } else {
      setSelectedStatus(filter); setExceptionOnly(false);
      refreshResults({ status: filter, exceptionOnly: false, limit: PAGE_SIZE, offset: 0 });
    }
  };

  const runSearch = () => { setPage(0); refreshResults({ search, exceptionOnly, status: selectedStatus, limit: PAGE_SIZE, offset: 0 }); };

  const batchAvg = useMemo(() => {
    const vals = (results.items || []).map(r => r.match_confidence).filter(v => v != null && v > 0);
    if (vals.length < 3) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }, [results.items]);

  return (
    <section className="screen" style={{ position: 'relative' }}>
      {triageRunning && <AiTriageLoader />}
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
        onResolve={onResolve || setSelected}
        onRefresh={() => refreshResults({ search, exceptionOnly, status: selectedStatus, limit: PAGE_SIZE, offset: page * PAGE_SIZE })}
        rows={results.items || []}
        selectedIndex={(results.items || []).findIndex(r => r.result_id === selected?.result_id)}
        onPrev={() => { const idx = (results.items || []).findIndex(r => r.result_id === selected?.result_id); if (idx > 0) setSelected(results.items[idx - 1]); }}
        onNext={() => { const idx = (results.items || []).findIndex(r => r.result_id === selected?.result_id); if (idx < (results.items || []).length - 1) setSelected(results.items[idx + 1]); }}
        onSelect={setSelected}
        batchAvg={batchAvg}
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

function Assistant({ onNavigate }) {
  const [thread, setThread] = useState([]);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [briefing, setBriefing] = useState(null);
  const [briefingLoading, setBriefingLoading] = useState(true);
  const bottomRef = useRef(null);

  const prompts = [
    'Which exceptions should I prioritise?',
    'What is the current match rate?',
    'What is the total variance?',
    'Are there AI matches to review?',
  ];

  useEffect(() => {
    setBriefingLoading(true);
    api.assistantBriefing()
      .then(setBriefing)
      .catch(() => setBriefing(null))
      .finally(() => setBriefingLoading(false));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [thread]);

  const ask = async (q) => {
    if (!q.trim()) return;
    const userMsg = { role: 'user', text: q };
    setThread((t) => [...t, userMsg]);
    setQuestion('');
    setLoading(true);
    try {
      const res = await api.assistant(q);
      setThread((t) => [...t, { role: 'assistant', text: res.answer, actions: res.actions || [], source: res.source }]);
    } catch {
      setThread((t) => [...t, { role: 'assistant', text: 'Sorry, something went wrong. Please try again.', actions: [], source: 'error' }]);
    } finally {
      setLoading(false);
    }
  };

  const severityClass = { info: 'neutral', warning: 'warning', critical: 'danger' };

  return (
    <section className="screen">
      <div className="screen-title">
        <div>
          <div className="eyebrow">Recon Copilot</div>
          <h1>Interactive operations assistant</h1>
          <p>Ask reconciliation questions and trigger guided investigation from summary, workflow and learning state.</p>
        </div>
      </div>

      {/* Analyst Briefing */}
      <Panel title="Analyst briefing">
        {briefingLoading && (
          <div className="briefing-grid">
            {[1,2,3,4].map((i) => (
              <div key={i} className="briefing-card skeleton-card">
                <div className="skeleton skeleton-title" />
                <div className="skeleton skeleton-line" />
                <div className="skeleton skeleton-line short" />
                <div className="skeleton skeleton-btn" />
              </div>
            ))}
          </div>
        )}
        {!briefingLoading && !briefing && <p className="empty small">Briefing unavailable.</p>}
        {!briefingLoading && briefing && (
          <div className="briefing-grid">
            {(briefing.insights || []).map((ins, i) => (
              <div key={i} className={`briefing-card ${severityClass[ins.severity] || 'neutral'}`}>
                <div className="briefing-card-title">{ins.title}</div>
                <p className="briefing-card-body">{ins.body}</p>
                {ins.action_label && ins.action_tab && (
                  <button className="btn ghost small" onClick={() => onNavigate(ins.action_tab)}>
                    {ins.action_label} →
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </Panel>

      {/* Chat */}
      <div className="chat-panel">
        <div className="chat-panel-header">
          <div className="chat-panel-title">
            <span className="chat-icon">✦</span>
            Ask the assistant
          </div>
          <span className="chat-panel-hint">Answers are grounded in live reconciliation data</span>
        </div>

        <div className="chat-thread">
          {thread.length === 0 && (
            <div className="chat-empty">
              <p>Ask a question or pick a suggestion below to get started.</p>
            </div>
          )}
          {thread.map((msg, i) => (
            <div key={i} className={`chat-bubble ${msg.role}`}>
              <div className="chat-bubble-label">{msg.role === 'user' ? 'You' : 'Copilot'}</div>
              <p>{msg.text}</p>
              {msg.actions && msg.actions.length > 0 && (
                <div className="chat-actions">
                  {msg.actions.map((a, j) => (
                    <button key={j} className="btn ghost small" onClick={() => onNavigate(a.tab)}>
                      {a.label} →
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="chat-bubble assistant">
              <div className="chat-bubble-label">Copilot</div>
              <p className="thinking">Thinking…</p>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="chat-panel-footer">
          <div className="chat-prompts">
            {prompts.map((q) => (
              <button className="chat-prompt-chip" key={q} onClick={() => ask(q)} disabled={loading}>{q}</button>
            ))}
          </div>
          <div className="chat-input-bar">
            <input
              value={question}
              placeholder="Ask anything about the reconciliation run…"
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !loading && ask(question)}
              disabled={loading}
            />
            <button className="btn primary" onClick={() => ask(question)} disabled={loading || !question.trim()}>Ask</button>
          </div>
        </div>
      </div>
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
  const [batchRunResult, setBatchRunResult] = useState(null);
  const [validatedBatchId, setValidatedBatchId] = useState(null);
  const [exceptions, setExceptions] = useState({ items: [] });
  const [patterns, setPatterns] = useState([]);
  const [proposedPatterns, setProposedPatterns] = useState([]);
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
  const [loading, setLoading] = useState(false);
  const [triageRunning, setTriageRunning] = useState(false);
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
    setProposedPatterns([]);
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
      setBatchRunResult(null);
      setValidatedBatchId(null);
    }, `${fileType} file uploaded`);
  };

  const uploadBatch = async (psrFile, camtFile, batchName) => {
    await safe(async () => {
      const psrResp = await api.uploadFile(psrFile, 'PSR', '', batchName);
      const newBatchId = psrResp.batch.batch_id;
      setSelectedBatchId(newBatchId);
      await api.uploadFile(camtFile, 'CAMT', newBatchId, '');
      setQuality(null);
      setBatchRunResult(null);
      setValidatedBatchId(null);
    }, 'PSR and CAMT files uploaded — ready to validate');
  };

  const validateSelectedBatch = async (batchId) => {
    await safe(async () => {
      const report = await api.validateBatch(batchId);
      setQuality(report);
      setValidatedBatchId(batchId);
    }, 'Data quality validation completed');
  };

  const runSelectedBatch = async (batchId, amountDivisor = null, patternGroup = null) => {
    let result;
    await safe(async () => {
      result = await api.runBatch(batchId, amountDivisor, patternGroup);
      setBatchRunResult(result);
      setQuality(null);
      setValidatedBatchId(null);
    }, () => `Uploaded batch reconciled (divisor: ${result?.amount_divisor ?? 'default'}${patternGroup ? `, group: ${patternGroup}` : ''})`);
  };

  const generateRegexMapping = async (camtFile, otherFile) => {
    return api.generateMapping(camtFile, otherFile);
  };

  const generatePatternsFromFiles = async (camtFile, otherFile, providedRegexMap = null) => {
    return api.generateReconciliationPatterns(camtFile, otherFile, providedRegexMap);
  };

  const generatePatternSuggestions = async (camtFile, otherFile, maxExamples = 8) => {
    return api.patternSuggestions(camtFile, otherFile, maxExamples);
  };

  const createBulkPatterns = async (groupName, patterns) => {
    const result = await api.createBulkPatterns(groupName, patterns);
    // Refresh patterns immediately so the new group appears in the
    // Data Intake "Run batch with pattern group" dropdown without a page reload.
    const fresh = await api.patterns();
    setPatterns(fresh);
    return result;
  };

  const saveGeneratedPattern = async (patternPayload) => {
    await safe(() => api.createPattern(patternPayload), 'Pattern saved to registry');
  };

  const runAiTriage = async () => {
    let result;
    setTriageRunning(true);
    await safe(
      async () => {
        result = await api.aiTriage();
        await refreshResults({ search: '', exceptionOnly: false, status: '' });
      },
      () => {
        const inserted = result?.inserted_count ?? 0;
        const adjudicated = result?.llm_adjudicated_count ?? 0;
        return `AI triage complete — ${inserted} candidate${inserted !== 1 ? 's' : ''} found, ${adjudicated} LLM-reviewed`;
      },
    );
    setTriageRunning(false);
  };

  const tunePattern = async (patternId, draft) => {
    await safe(() => api.updatePattern(patternId, {
      pattern_name: draft.pattern_name,
      pattern_type: draft.pattern_type,
      pattern_version: draft.pattern_version,
      status: draft.status,
      execution_mode: draft.execution_mode,
      confidence_threshold: draft.confidence_threshold,
      approved_by: draft.approved_by,
      pattern_rule: draft.pattern_rule,
    }), 'Pattern configuration saved');
  };

  const togglePattern = async (pattern) => {
    await safe(() => pattern.status === 'ACTIVE' ? api.deactivatePattern(pattern.pattern_id) : api.activatePattern(pattern.pattern_id), 'Pattern status updated');
  };

  const createPattern = async (payloadOrName) => {
    const payload = typeof payloadOrName === 'string' ? {
      pattern_name: payloadOrName,
      pattern_type: 'LEARNED_DRAFT',
      pattern_version: '1.0',
      pattern_rule: { fields: ['invoice_suffix', 'amount', 'counterparty'], status: 'suggestion_only' },
      status: 'ACTIVE',
      execution_mode: 'SUGGESTION',
      confidence_threshold: 0.87,
      approved_by: 'prototype_user',
    } : payloadOrName;

    await safe(() => api.createPattern(payload), 'Pattern created');
  };

  const removePattern = async (patternId) => {
    await safe(() => api.deletePattern(patternId), 'Pattern deleted');
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
    }), 'Manually reviewed — resolution & learning signal recorded');
    setModalItem(null);
    setSelected(null);
    await refreshResults();
  };

  const exportCsv = () => {
    window.open(api.exportResultsUrl(), '_blank', 'noopener,noreferrer');
  };

  const screen = useMemo(() => {
    if (active === 'workspace') return <Workspace workspace={workspace} summary={summary} onLoad={() => safe(api.loadSampleData, 'Sample PSR/CAMT loaded')} onRun={() => safe(api.runRecon, 'Reconciliation completed')} onSnapshot={() => safe(api.createSnapshot, 'Snapshot created')} onExport={exportCsv} loading={loading} />;
    if (active === 'intake') return <DataIntake batches={batches} submissions={submissions} selectedBatchId={selectedBatchId} setSelectedBatchId={setSelectedBatchId} quality={quality} batchRunResult={batchRunResult} validatedBatchId={validatedBatchId} onUpload={uploadReconFile} onUploadBatch={uploadBatch} onValidate={validateSelectedBatch} onRunBatch={runSelectedBatch} onNavigate={setActive} loading={loading} patternGroups={[...new Set((patterns || []).map((p) => p.pattern_group || 'default').filter(Boolean))].sort()} />;
    if (active === 'dataprep') return <DataPrep preview={preview} predictions={predictions} />;
    if (active === 'matching') return <MatchingStudio patterns={patterns} rules={noCodeRules} onTunePattern={tunePattern} onTogglePattern={togglePattern} onCreatePattern={createPattern} />;
    if (active === 'pattern-builder') return <PatternBuilder onGenerateMapping={generateRegexMapping} onGeneratePatterns={generatePatternsFromFiles} onSuggestPatterns={generatePatternSuggestions} onSave={saveGeneratedPattern} onSaveBulk={createBulkPatterns} proposedPatterns={proposedPatterns} setProposedPatterns={setProposedPatterns} />;
    if (active === 'patterns') return <PatternManagement patterns={patterns} onCreate={createPattern} onUpdate={tunePattern} onDelete={removePattern} />;
    if (active === 'results') return <ResultsWorkbench results={results} summary={summary} selected={selected} setSelected={setSelected} refreshResults={refreshResults} onAiTriage={runAiTriage} onResolve={setModalItem} loading={loading} triageRunning={triageRunning} />;
    if (active === 'exceptions') return <Exceptions exceptions={exceptions} workflowRules={workflowRules} onResolveClick={setModalItem} onWorkflowUpdate={updateWorkflow} />;
    if (active === 'dashboards') return <Dashboards dashboard={dashboard} onExport={exportCsv} />;
    if (active === 'learning') return <Learning candidates={candidates} events={events} onSeed={() => safe(api.seedLearning, 'Demo learning signals seeded')} onDiscover={() => safe(api.discover, 'Pattern discovery completed')} onApprove={(id) => safe(() => api.approveCandidate(id), 'Candidate approved as learnt suggestion')} />;
    if (active === 'assistant') return <Assistant onNavigate={(tab) => setActive(tab)} />;
    if (active === 'governance') return <Governance events={events} workspace={workspace} onSnapshot={() => safe(api.createSnapshot, 'Snapshot created')} />;
    return null;
  }, [active, workspace, summary, results, exceptions, patterns, candidates, events, batches, submissions, selectedBatchId, quality, batchRunResult, preview, predictions, noCodeRules, workflowRules, dashboard, selected, loading]);

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
