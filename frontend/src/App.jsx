import { useEffect, useMemo, useRef, useState } from 'react';
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
  ['auto-pattern', 'Auto Pattern Recon'],
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
            <div className="bar-track">
              <span style={{ width: `${Math.max(4, (value / max) * 100)}%` }} />
            </div>
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
          <button className="btn secondary" onClick={onLoad} disabled={loading}>
            Load sample PSR/CAMT
          </button>
          <button className="btn primary" onClick={onRun} disabled={loading}>
            Run reconciliation
          </button>
          <button className="btn ghost" onClick={onSnapshot} disabled={loading}>
            Create snapshot
          </button>
          <button className="btn ghost" onClick={onExport}>
            Export CSV
          </button>
        </div>
      </div>

      <div className="metric-grid six">
        <Metric
          label="PSR records"
          value={summary?.psr_records || summary?.raw?.psr_count || 0}
          hint="Internal settlement rows"
          tone="info"
        />
        <Metric
          label="CAMT entries"
          value={summary?.camt_entries || summary?.raw?.camt_count || 0}
          hint="Bank statement entries"
          tone="info"
        />
        <Metric
          label="Auto-closed"
          value={summary?.auto_closed || 0}
          hint={`${pct(summary?.match_rate)} match rate`}
          tone="success"
        />
        <Metric
          label="Open exceptions"
          value={summary?.exceptions || 0}
          hint="Manual, ledger and in-transit"
          tone="warning"
        />
        <Metric
          label="Learning signals"
          value={summary?.manual_resolutions || 0}
          hint="Captured analyst decisions"
          tone="neutral"
        />
        <Metric
          label="Variance exposure"
          value={money(summary?.variance_total || 0)}
          hint="Internal less bank total"
          tone="danger"
        />
      </div>

      <div className="grid two">
        <Panel title="Process lifecycle" subtitle="End-to-end workflow from raw feed to downstream-ready output">
          <Stepper lifecycle={lifecycle} />
        </Panel>
        <Panel title="AI operator insights" subtitle="Prototype differentiators beyond static rule configuration">
          <div className="insight-list">
            {insights.map((i) => (
              <div className="insight" key={i}>
                <span>AI</span>
                <p>{i}</p>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel
        title="Capability matrix"
        subtitle="End-to-end operational coverage from ingestion to exception resolution and pattern learning"
      >
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

function DataIntake({
  batches,
  submissions,
  selectedBatchId,
  setSelectedBatchId,
  quality,
  batchRunResult,
  onUpload,
  onValidate,
  onRunBatch,
  onNavigate,
  loading,
}) {
  const [psrFile, setPsrFile] = useState(null);
  const [camtFile, setCamtFile] = useState(null);
  const [batchName, setBatchName] = useState('Treasury cash daily upload');
  const qualityTableRef = useRef(null);
  const selectedBatch =
    (batches.items || []).find((b) => b.batch_id === selectedBatchId) || (batches.items || [])[0];
  const batchId = selectedBatch?.batch_id || selectedBatchId || '';
  const issues = quality?.issues || [];
  const files = submissions?.items || [];

  const scrollToQualityTable = () =>
    qualityTableRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });

  return (
    <section className="screen">
      <div className="screen-title">
        <div>
          <div className="eyebrow">Data intake</div>
          <h1>Submissions, snapshots and feed readiness</h1>
          <p>
            Upload PSR and CAMT.053 feeds, inspect processing state, validate quality, and trigger reconciliation
            snapshots.
          </p>
        </div>
      </div>

      <div className="grid two intake-grid">
        <Panel
          title="Create upload batch"
          subtitle="Manual upload for the prototype; the same API can be connected to SFTP or bank feed later."
        >
          <div className="form-grid">
            <label>Batch name</label>
            <input value={batchName} onChange={(e) => setBatchName(e.target.value)} />
            <label>PSR payment settlement file</label>
            <input
              type="file"
              accept=".txt,.dat,.psr,text/plain"
              onChange={(e) => setPsrFile(e.target.files?.[0] || null)}
            />
            <button
              className="btn secondary"
              disabled={!psrFile || loading}
              onClick={() => onUpload('PSR', psrFile, '', batchName)}
            >
              Upload PSR to new batch
            </button>
            <label>Existing batch</label>
            <select value={batchId} onChange={(e) => setSelectedBatchId(e.target.value)}>
              <option value="">Select batch</option>
              {(batches.items || []).map((b) => (
                <option key={b.batch_id} value={b.batch_id}>
                  {b.batch_name} · {b.status}
                </option>
              ))}
            </select>
            <label>CAMT.053 bank statement</label>
            <input
              type="file"
              accept=".xml,application/xml,text/xml"
              onChange={(e) => setCamtFile(e.target.files?.[0] || null)}
            />
            <button
              className="btn secondary"
              disabled={!camtFile || !batchId || loading}
              onClick={() => onUpload('CAMT', camtFile, batchId, '')}
            >
              Upload CAMT to selected batch
            </button>
          </div>
        </Panel>

        <Panel
          title="Selected batch control"
          subtitle="Data quality validation should run before auto-close decisions are trusted."
        >
          {selectedBatch ? (
            <>
              <dl className="kv">
                <dt>Batch</dt>
                <dd>{selectedBatch.batch_name}</dd>
                <dt>Status</dt>
                <dd>
                  <Tag tone={classForStatus(selectedBatch.status)}>{selectedBatch.status}</Tag>
                </dd>
                <dt>PSR file</dt>
                <dd>{selectedBatch.psr_file_id || '-'}</dd>
                <dt>CAMT file</dt>
                <dd>{selectedBatch.camt_file_id || '-'}</dd>
              </dl>
              <div className="button-row">
                <button
                  className="btn secondary"
                  disabled={!batchId || loading}
                  onClick={() => onValidate(batchId)}
                >
                  Validate quality
                </button>
                <button
                  className="btn primary"
                  disabled={!batchId || loading}
                  onClick={() => onRunBatch(batchId)}
                >
                  Run uploaded batch
                </button>
              </div>

              {quality && (
                <div
                  style={{
                    marginTop: '1.25rem',
                    borderTop: '1px solid var(--border)',
                    paddingTop: '1rem',
                  }}
                >
                  <div
                    style={{
                      fontSize: '0.72rem',
                      fontWeight: 700,
                      letterSpacing: '0.06em',
                      textTransform: 'uppercase',
                      color: 'var(--muted)',
                      marginBottom: '0.6rem',
                    }}
                  >
                    Data quality
                  </div>
                  <div className="metric-grid three" style={{ marginBottom: '0.4rem' }}>
                    <div
                      style={{
                        cursor: (quality.error_count || 0) > 0 ? 'pointer' : 'default',
                      }}
                      onClick={
                        (quality.error_count || 0) > 0 ? scrollToQualityTable : undefined
                      }
                      title={
                        (quality.error_count || 0) > 0
                          ? 'Click to see issue details below'
                          : undefined
                      }
                    >
                      <Metric
                        label="Errors"
                        value={quality.error_count || 0}
                        hint={(quality.error_count || 0) > 0 ? '↓ See details' : 'None'}
                        tone="danger"
                      />
                    </div>
                    <div
                      style={{
                        cursor: (quality.warning_count || 0) > 0 ? 'pointer' : 'default',
                      }}
                      onClick={
                        (quality.warning_count || 0) > 0 ? scrollToQualityTable : undefined
                      }
                      title={
                        (quality.warning_count || 0) > 0
                          ? 'Click to see issue details below'
                          : undefined
                      }
                    >
                      <Metric
                        label="Warnings"
                        value={quality.warning_count || 0}
                        hint={(quality.warning_count || 0) > 0 ? '↓ See details' : 'None'}
                        tone="warning"
                      />
                    </div>
                    <Metric
                      label="Files checked"
                      value={(quality.files || []).length}
                      hint="PSR + CAMT"
                      tone="info"
                    />
                  </div>
                </div>
              )}

              {batchRunResult && (
                <div
                  style={{
                    marginTop: '1.25rem',
                    borderTop: '1px solid var(--border)',
                    paddingTop: '1rem',
                  }}
                >
                  <div
                    style={{
                      fontSize: '0.72rem',
                      fontWeight: 700,
                      letterSpacing: '0.06em',
                      textTransform: 'uppercase',
                      color: 'var(--muted)',
                      marginBottom: '0.6rem',
                    }}
                  >
                    Batch run results
                  </div>
                  <div className="metric-grid three" style={{ marginBottom: '0.75rem' }}>
                    <div
                      style={{ cursor: 'pointer' }}
                      onClick={() => onNavigate('results')}
                      title="Open Results Workbench"
                    >
                      <Metric
                        label="PSR transactions"
                        value={batchRunResult.psr_count || 0}
                        hint="→ Results Workbench"
                        tone="info"
                      />
                    </div>
                    <div
                      style={{ cursor: 'pointer' }}
                      onClick={() => onNavigate('results')}
                      title="Open Results Workbench"
                    >
                      <Metric
                        label="CAMT entries"
                        value={batchRunResult.camt_count || 0}
                        hint="→ Results Workbench"
                        tone="info"
                      />
                    </div>
                    <div
                      style={{ cursor: 'pointer' }}
                      onClick={() => onNavigate('results')}
                      title="Open Results Workbench"
                    >
                      <Metric
                        label="Cases created"
                        value={batchRunResult.case_count || 0}
                        hint="→ Results Workbench"
                        tone="good"
                      />
                    </div>
                  </div>
                  <div className="button-row" style={{ marginTop: '0.5rem' }}>
                    <button
                      className="btn secondary small"
                      onClick={() => onNavigate('results')}
                    >
                      View Results Workbench →
                    </button>
                    <button
                      className="btn secondary small"
                      onClick={() => onNavigate('exceptions')}
                    >
                      View Exceptions →
                    </button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <p className="empty small">Upload a PSR file to create a batch.</p>
          )}
        </Panel>
      </div>

      <Panel
        title="Submissions queue"
        subtitle="Equivalent operational view for uploaded files, processing status, document state and usage."
      >
        <div className="table-wrap" style={{ maxHeight: '300px', overflowY: 'auto' }}>
          <table>
            <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
              <tr>
                <th>File</th>
                <th>Type</th>
                <th>Batch</th>
                <th>Upload status</th>
                <th>Document status</th>
                <th>Used in</th>
                <th>Profile</th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.file_id}>
                  <td>
                    <strong>{f.original_filename}</strong>
                    <br />
                    <span className="muted">{f.file_id}</span>
                  </td>
                  <td>
                    <Tag tone="info">{f.file_type}</Tag>
                  </td>
                  <td>{f.batch_name || f.batch_id}</td>
                  <td>
                    <Tag tone={classForStatus(f.status)}>{f.status}</Tag>
                  </td>
                  <td>
                    <Tag tone={classForStatus(f.document_status)}>{f.document_status}</Tag>
                  </td>
                  <td>{f.used_in || '-'}</td>
                  <td>
                    <code>{JSON.stringify(f.profile || {})}</code>
                  </td>
                </tr>
              ))}
              {!files.length && (
                <tr>
                  <td colSpan="7" className="empty">
                    No submissions yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      {quality && (
        <div ref={qualityTableRef}>
          <Panel
            title="Data quality issue details"
            subtitle={`${issues.length} issue${issues.length !== 1 ? 's' : ''} found · ${
              quality.error_count || 0
            } error${(quality.error_count || 0) !== 1 ? 's' : ''}, ${
              quality.warning_count || 0
            } warning${(quality.warning_count || 0) !== 1 ? 's' : ''}`}
          >
            <div
              className="table-wrap compact"
              style={{ maxHeight: '340px', overflowY: 'auto' }}
            >
              <table>
                <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
                  <tr>
                    <th>Severity</th>
                    <th>Issue</th>
                    <th>Record</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {issues.map((i) => (
                    <tr key={i.issue_id}>
                      <td>
                        <Tag tone={classForStatus(i.severity)}>{i.severity}</Tag>
                      </td>
                      <td>{i.issue_code}</td>
                      <td>{i.record_id || '-'}</td>
                      <td>{i.message}</td>
                    </tr>
                  ))}
                  {!issues.length && (
                    <tr>
                      <td colSpan="4" className="empty">
                        No quality issues found.
                      </td>
                    </tr>
                  )}
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
          <p>
            Business-readable mapping and cleansing layer for PSR fixed-width and CAMT.053 XML before
            reconciliation runs.
          </p>
        </div>
      </div>

      <div className="grid two">
        <Panel
          title="Canonical output model"
          subtitle="Consolidated field set used by the match engine"
        >
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
        <Panel
          title="AI field prediction"
          subtitle="Suggested match-field pairing with confidence and rationale"
        >
          <div className="prediction-list">
            {predictionRows.map((p) => (
              <div className="prediction" key={`${p.left_field}-${p.right_field}`}>
                <div>
                  <strong>
                    {p.left_field} ↔ {p.right_field}
                  </strong>
                  <p>{p.rationale}</p>
                </div>
                <div className="confidence-ring">
                  <span>{p.confidence}%</span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel
        title="Transform and cleanse rules"
        subtitle="Prototype rules kept transparent for audit and operations sign-off"
      >
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
          <PreviewTable
            rows={psrRows}
            columns={[
              'id',
              'reference',
              'amount',
              'direction',
              'invoice',
              'counterparty',
              'currency',
            ]}
          />
        </Panel>
        <Panel title={`CAMT preview (${preview?.camt?.total || 0} rows)`}>
          <PreviewTable
            rows={camtRows}
            columns={[
              'ntry_id',
              'pmt_ref',
              'amount',
              'direction',
              'invoice',
              'counterparty',
              'currency',
            ]}
          />
        </Panel>
      </div>
    </section>
  );
}

function PreviewTable({ rows, columns }) {
  return (
    <div className="table-wrap compact tight">
      <table>
        <thead>
          <tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, idx) => (
            <tr key={idx}>
              {columns.map((c) => (
                <td key={c}>{String(r[c] ?? '-')}</td>
              ))}
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={columns.length} className="empty">
                No preview data.
              </td>
            </tr>
          )}
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
          <p>
            Operations-friendly rule text backed by configurable FastAPI pattern records and deterministic
            reconciliation logic.
          </p>
        </div>
      </div>

      <Panel
        title="Rule builder"
        subtitle="Add a controlled suggestion-only rule without writing code"
      >
        <div className="builder-row">
          <input value={newName} onChange={(e) => setNewName(e.target.value)} />
          <button className="btn primary" onClick={() => onCreatePattern(newName)}>
            Create suggestion pattern
          </button>
        </div>
      </Panel>

      <div className="grid two">
        <Panel
          title="Natural rule language view"
          subtitle="Readable rules equivalent to a business-owned recon configuration"
        >
          <div className="nrl-list">
            {(rules?.items || []).map((r) => (
              <div className="nrl-card" key={r.pattern_id}>
                <div>
                  <Tag tone={classForStatus(r.status)}>{r.status}</Tag>{' '}
                  <Tag tone="info">{r.execution_mode}</Tag>
                </div>
                <strong>{r.pattern_name}</strong>
                <p>{r.natural_rule}</p>
              </div>
            ))}
          </div>
        </Panel>
        <Panel
          title="Multi-pass execution order"
          subtitle="The same cases are evaluated through ordered passes, then routed by confidence"
        >
          <div className="pass-list">
            {(patterns || []).map((p, idx) => (
              <div className="pass" key={p.pattern_id}>
                <span>{idx + 1}</span>
                <div>
                  <strong>
                    {p.pattern_id} · {p.pattern_name}
                  </strong>
                  <p>
                    {p.execution_mode} · threshold {p.confidence_threshold}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel
        title="Pattern registry and tuning"
        subtitle="Tune thresholds or suspend risky rules for testing and governance"
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Status</th>
                <th>Mode</th>
                <th>Threshold</th>
                <th>Rule JSON</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {patterns.map((p) => {
                const draft = drafts[p.pattern_id] || {};
                return (
                  <tr key={p.pattern_id}>
                    <td>
                      <strong>{p.pattern_id}</strong>
                    </td>
                    <td>{p.pattern_name}</td>
                    <td>
                      <Tag tone={classForStatus(p.status)}>{p.status}</Tag>
                    </td>
                    <td>
                      <select
                        value={draft.execution_mode || p.execution_mode}
                        onChange={(e) => updateDraft(p.pattern_id, 'execution_mode', e.target.value)}
                      >
                        <option value="AUTO_CLOSE">AUTO_CLOSE</option>
                        <option value="SUGGESTION">SUGGESTION</option>
                        <option value="MANUAL">MANUAL</option>
                        <option value="LEDGER_OR_IN_TRANSIT">LEDGER_OR_IN_TRANSIT</option>
                      </select>
                    </td>
                    <td>
                      <input
                        className="small-input"
                        type="number"
                        step="0.01"
                        min="0"
                        max="1"
                        value={draft.confidence_threshold ?? p.confidence_threshold}
                        onChange={(e) =>
                          updateDraft(p.pattern_id, 'confidence_threshold', Number(e.target.value))
                        }
                      />
                    </td>
                    <td>
                      <code>{JSON.stringify(p.pattern_rule || {})}</code>
                    </td>
                    <td className="action-cell">
                      <button
                        className="btn secondary"
                        onClick={() => onTunePattern(p.pattern_id, draft)}
                      >
                        Save
                      </button>
                      <button className="btn ghost" onClick={() => onTogglePattern(p)}>
                        {p.status === 'ACTIVE' ? 'Suspend' : 'Activate'}
                      </button>
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

const MINOR_VARIANCE_TOLERANCE = 50;

const varianceTone = (v) => {
  if (v === null || v === undefined) return '';
  if (v === 0) return 'positive';
  if (Math.abs(v) <= MINOR_VARIANCE_TOLERANCE) return 'warning';
  return 'negative';
};

function AiPill({ rule }) {
  if (!rule || (!rule.startsWith('TIER2B') && !rule.startsWith('TIER2C'))) return null;
  const isNoMatch = rule === 'TIER2C_NO_MATCH';
  return (
    <span className={`ai-pill ${isNoMatch ? 'muted' : 'accent'}`} title={rule}>
      AI
    </span>
  );
}

function SortTh({ col, label, sortCol, sortDir, onSort }) {
  const active = sortCol === col;
  return (
    <th
      onClick={() => onSort(col)}
      style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}
    >
      {label}
      {active ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
    </th>
  );
}

function ResultTable({ rows, onSelect }) {
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState('asc');

  const onSort = (col) => {
    if (sortCol === col) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortCol(col);
      setSortDir('asc');
    }
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
            <tr
              key={r.result_id}
              onClick={() => onSelect?.(r)}
              className="clickable"
            >
              <td>
                <strong>{r.result_id}</strong>
                <AiPill rule={r.rule_applied} />
                <br />
                <span className="muted">
                  {r.psr_id || '-'} / {r.camt_id || '-'}
                </span>
              </td>
              <td>{money(r.internal_amount)}</td>
              <td>{money(r.bank_amount)}</td>
              <td>{r.reference || '-'}</td>
              <td>{r.counterparty || '-'}</td>
              <td className={varianceTone(r.variance)}>
                {r.variance != null ? money(r.variance) : '-'}
              </td>
              <td>
                <Tag tone={classForStatus(r.reconciliation_status)}>
                  {r.reconciliation_status}
                </Tag>
              </td>
              <td>{r.rule_applied || '-'}</td>
              <td>
                <div className="mini-score">
                  <span style={{ width: `${r.match_confidence || 0}%` }} />
                  {r.match_confidence}%
                </div>
              </td>
            </tr>
          ))}
          {!sorted.length && (
            <tr>
              <td colSpan="9" className="empty">
                No records to display.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function FieldDiff({ item }) {
  const fmt = (v) => (v == null || v === '' ? '\u2014' : String(v));
  const mismatch = (a, b) =>
    a != null &&
    a !== '' &&
    b != null &&
    b !== '' &&
    String(a).trim() !== String(b).trim();
  const isValidId = (id) =>
    Boolean(
      id &&
        id.trim() &&
        !['NOT FOUND', 'N/A', 'NONE', 'NULL'].includes(id.trim().toUpperCase()),
    );
  const hasPsr = Boolean(item.psr_id);
  const hasCamtData = item.bank_amount != null;
  const hasCamt = Boolean(item.camt_id || hasCamtData);
  const rows = [
    {
      label: 'Amount',
      psr: hasPsr ? item.internal_amount : null,
      camt: hasCamtData ? item.bank_amount : null,
    },
    {
      label: 'Direction',
      psr: hasPsr ? item.psr_direction : null,
      camt: hasCamtData ? item.camt_direction : null,
    },
    {
      label: 'Date',
      psr: hasPsr ? item.value_date : null,
      camt: hasCamtData ? item.booking_date : null,
    },
    {
      label: 'Reference',
      psr: hasPsr ? item.reference : null,
      camt: hasCamtData ? item.camt_pmt_ref : null,
    },
    {
      label: 'Counterparty',
      psr: hasPsr ? item.counterparty : null,
      camt: hasCamtData ? item.camt_counterparty : null,
    },
    {
      label: 'Invoice',
      psr: hasPsr ? item.invoice : null,
      camt: hasCamtData ? item.camt_invoice : null,
    },
    {
      label: 'Remittance',
      psr: null,
      camt: hasCamtData ? item.camt_remittance : null,
    },
  ];
  return (
    <div className="field-diff">
      <div className="field-diff-header">
        <span className="field-label"></span>
        <span>PSR (Internal)</span>
        <span>Bank (CAMT)</span>
      </div>
      <div className="field-diff-row field-diff-ids">
        <span className="field-label">ID</span>
        <span className="field-val">
          {hasPsr && isValidId(item.psr_id) ? (
            <a className="source-link" href={`#psr-${item.psr_id}`}>
              {item.psr_id}
            </a>
          ) : (
            fmt(hasPsr ? item.psr_id : null)
          )}
        </span>
        <span className="field-val">
          {hasCamtData && isValidId(item.camt_id) ? (
            <a className="source-link" href={`#camt-${item.camt_id}`}>
              {item.camt_id}
            </a>
          ) : (
            fmt(hasCamtData ? item.camt_id : null)
          )}
        </span>
      </div>
      {rows.map(({ label, psr, camt }) => (
        <div
          key={label}
          className={`field-diff-row${mismatch(psr, camt) ? ' mismatch' : ''}`}
        >
          <span className="field-label">{label}</span>
          <span className="field-val">{fmt(psr)}</span>
          <span className="field-val">{fmt(camt)}</span>
        </div>
      ))}
    </div>
  );
}

const ACTION_CONFIG = {
  CONFIRM_AI_MATCH: {
    label: 'Accept AI Match',
    desc: 'Mark this PSR as matched to the suggested bank entry.',
    tone: 'confirm',
  },
  CONFIRM_LEARNED_MATCH: {
    label: 'Accept Learned Match',
    desc: 'A learned pattern suggested this match — confirm to close.',
    tone: 'confirm',
  },
  REVIEW_FUZZY_CANDIDATE: {
    label: 'Review Fuzzy Match',
    desc: 'Counterparty similarity was high but not exact — verify before confirming.',
    tone: 'analyst',
  },
  POST_LEDGER_CANDIDATE: {
    label: 'Post to Short / Over Ledger',
    desc: 'Amount variance is within tolerance — recommend posting the difference to ledger.',
    tone: 'analyst',
  },
  ROUTE_TO_REVIEW: {
    label: 'Route for Variance Review',
    desc: 'Amount variance exceeds tolerance — escalate for manual review.',
    tone: 'analyst',
  },
  ROUTE_TO_EXCEPTION_QUEUE: {
    label: 'Route to Exception Queue',
    desc: 'No bank match found — monitor for next CAMT cycle.',
    tone: 'nomatch',
  },
  INVESTIGATE_BANK_ONLY: {
    label: 'Investigate Bank Entry',
    desc: 'Bank entry received with no matching internal payment — investigate source.',
    tone: 'nomatch',
  },
  ROUTE_TO_ANALYST: {
    label: 'Escalate for Review',
    desc: 'Send to analyst queue for manual verification.',
    tone: 'analyst',
  },
  NO_MATCH: {
    label: 'Mark as No Match',
    desc: 'Record this PSR as unmatched; no bank entry corresponds.',
    tone: 'nomatch',
  },
};
const actionConfig = (code) =>
  ACTION_CONFIG[code] ?? { label: code, desc: '', tone: 'neutral' };

const RULE_LABELS = {
  P1_EXACT_END_TO_END_ID: 'EndToEnd ID exact match',
  P2_PMT_REF_AMOUNT: 'PMT reference + amount match',
  P3_INVOICE_USTRD_AMOUNT: 'Invoice + amount match',
  P4_COUNTERPARTY_FUZZY: 'Counterparty fuzzy + amount match',
  P5_EXCEPTION_HANDLING: 'No match found',
  P7_AMOUNT_VARIANCE: 'Amount variance rule',
  P8_LEARNED_INVOICE_SUFFIX: 'Learned: invoice suffix match',
  P1: 'EndToEnd ID exact match',
  P2: 'PMT reference + amount match',
  P3: 'Invoice + amount match',
  P4: 'Counterparty fuzzy + amount match',
  P5: 'No match found',
  P6: 'One-to-many grouping match',
  P7: 'Amount variance rule',
  TIER2C_NO_MATCH: 'AI reviewed — no match found',
  TIER2C_LLM: 'AI reviewed — match suggested',
  TIER2B_CLEAR: 'Embedding match — high confidence',
  TIER2B_MAYBE: 'Embedding match — needs review',
  AI_MAYBE_ZONE: 'Embedding match — needs review',
};
const ruleLabel = (code) => RULE_LABELS[code] ?? code;

const PAGE_SIZE = 100;

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

function EvidenceDrawer({
  selected,
  onClose,
  onResolve,
  onRefresh,
  rows = [],
  selectedIndex = -1,
  onPrev,
  onNext,
  onSelect,
  batchAvg = null,
}) {
  const [detail, setDetail] = useState(null);
  const [overrideMode, setOverrideMode] = useState(false);
  const [overrideReason, setOverrideReason] = useState('');
  const [overrideNote, setOverrideNote] = useState('');
  const [overrideLoading, setOverrideLoading] = useState(false);
  const [similarCases, setSimilarCases] = useState(null);
  const [similarOpen, setSimilarOpen] = useState(false);
  const [noMatchLoading, setNoMatchLoading] = useState(null);
  const [drawerFilter, setDrawerFilter] = useState('all');
  const [shortcutsHidden, setShortcutsHidden] = useState(
    () => localStorage.getItem('hideDrawerShortcuts') === '1',
  );

  const filteredRows = useMemo(() => {
    switch (drawerFilter) {
      case 'low':
        return rows.filter(
          (r) => r.match_confidence != null && r.match_confidence < 60,
        );
      case 'ai':
        return rows.filter((r) => r.rule_applied?.startsWith('TIER2'));
      default:
        return rows;
    }
  }, [rows, drawerFilter]);

  const filteredIndex = filteredRows.findIndex(
    (r) => r.result_id === selected?.result_id,
  );

  const goTo = (delta) => {
    const next = filteredRows[filteredIndex + delta];
    if (next && onSelect) onSelect(next);
    else if (delta === -1) onPrev?.();
    else onNext?.();
  };

  useEffect(() => {
    if (!selected?.result_id) {
      setDetail(null);
      setOverrideMode(false);
      setOverrideReason('');
      setOverrideNote('');
      setSimilarCases(null);
      setSimilarOpen(false);
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
    api
      .caseDetail(selected.result_id)
      .then((d) => setDetail(d.case))
      .catch(() => {});
    api
      .similarCases(selected.result_id)
      .then(setSimilarCases)
      .catch(() => setSimilarCases({ items: [], count: 0 }));
  }, [selected?.result_id]);

  useEffect(() => {
    if (!selected) return;
    const MATCH_STATUSES_KB = [
      'Suggested Match - Analyst Review',
      'Suggested Match - Learned Pattern',
      'Exception - Amount Variance Review',
      'Post to Short or Over Ledger',
    ];
    const handler = (e) => {
      const tag = document.activeElement?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        goTo(-1);
      }
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        goTo(1);
      }
      if (e.key === 'Escape') {
        onClose();
      }
      if ((e.key === 'r' || e.key === 'R') && !overrideMode) {
        const item = detail ? { ...selected, ...detail } : selected;
        if (MATCH_STATUSES_KB.includes(item.reconciliation_status)) {
          e.preventDefault();
          onResolve(item);
        }
      }
      if ((e.key === 'o' || e.key === 'O') && !overrideMode) {
        const item = detail ? { ...selected, ...detail } : selected;
        if (MATCH_STATUSES_KB.includes(item.reconciliation_status)) {
          e.preventDefault();
          setOverrideMode(true);
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [
    selected,
    detail,
    overrideMode,
    filteredIndex,
    filteredRows,
    onSelect,
    onPrev,
    onNext,
    onClose,
    onResolve,
  ]);

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
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer">
        <div className="drawer-nav">
          <button
            className="btn ghost"
            disabled={filteredIndex <= 0}
            onClick={() => goTo(-1)}
          >
            ← Prev
          </button>
          <span className="drawer-nav-counter">
            {filteredIndex >= 0
              ? `${filteredIndex + 1} / ${filteredRows.length}`
              : `0 / ${filteredRows.length}`}
            {drawerFilter !== 'all' && (
              <span className="filter-badge">
                {drawerFilter === 'low' ? 'Low conf' : 'AI'}
              </span>
            )}
          </span>
          <div className="drawer-filter-pills">
            {['all', 'low', 'ai'].map((f) => (
              <button
                key={f}
                className={`filter-pill${drawerFilter === f ? ' active' : ''}`}
                onClick={() => {
                  setDrawerFilter(f);
                  const newFiltered =
                    f === 'low'
                      ? rows.filter(
                          (r) =>
                            r.match_confidence != null && r.match_confidence < 60,
                        )
                      : f === 'ai'
                        ? rows.filter((r) =>
                            r.rule_applied?.startsWith('TIER2'),
                          )
                        : rows;
                  if (
                    newFiltered.length > 0 &&
                    !newFiltered.find(
                      (r) => r.result_id === selected?.result_id,
                    )
                  ) {
                    onSelect?.(newFiltered[0]);
                  }
                }}
              >
                {f === 'all' ? 'All' : f === 'low' ? 'Low conf' : 'AI'}
                <span className="pill-count">
                  {(
                    f === 'low'
                      ? rows.filter(
                          (r) =>
                            r.match_confidence != null && r.match_confidence < 60,
                        )
                      : f === 'ai'
                        ? rows.filter((r) =>
                            r.rule_applied?.startsWith('TIER2'),
                          )
                        : rows
                  ).length}
                </span>
              </button>
            ))}
          </div>
          <button
            className="btn ghost"
            disabled={filteredIndex < 0 || filteredIndex >= filteredRows.length - 1}
            onClick={() => goTo(1)}
          >
            Next →
          </button>
          <button className="btn ghost" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="drawer-body">
          <div className="eyebrow">Match evidence</div>
          <h2>{selected.result_id}</h2>
          <p>{selected.explanation}</p>
          <dl className="kv drawer-kv">
            <dt>Status</dt>
            <dd>
              <Tag tone={classForStatus(item.reconciliation_status)}>
                {item.reconciliation_status}
              </Tag>
            </dd>
            <dt>Rule applied</dt>
            <dd>
              {ruleLabel(item.rule_applied) || '-'}
              {item.rule_applied && (
                <span className="rule-code">{item.rule_applied}</span>
              )}
            </dd>
            <dt>Reason</dt>
            <dd>{item.reason_code || '-'}</dd>
            {item.variance != null && (
              <>
                <dt>Variance</dt>
                <dd>{money(item.variance)}</dd>
              </>
            )}
          </dl>
          {hasMatch && <FieldDiff item={item} />}
          <Panel title="Why this decision?" className="nested-panel">
            {(() => {
              const NO_COMPARISON_STATUSES = [
                'Uncleared / In-Transit Payment',
                'Bank-only Item - Investigation',
              ];
              const isNoComparison = NO_COMPARISON_STATUSES.includes(
                item.reconciliation_status,
              );
              if (isNoComparison) {
                return (
                  <p className="no-match-explanation">
                    All matching rules were applied — no{' '}
                    {item.reconciliation_status ===
                    'Bank-only Item - Investigation'
                      ? 'PSR payment entry could be paired with this bank transaction'
                      : 'bank transaction could be paired with this PSR entry'}
                    .
                    {item.explanation
                      ? ` ${item.explanation}`
                      : ' The item has been queued for monitoring on the next CAMT cycle.'}
                  </p>
                );
              }
              return (
                <>
                  <div className="score-labelled">
                    <p className="score-label">
                      {ruleLabel(score.rule_applied || item.rule_applied) ||
                        'Rule decision confidence'}
                    </p>
                    <div className="score-bar-row">
                      <div className="score-large">
                        <span
                          style={{
                            width: `${score.engine_confidence ??
                              item.match_confidence ??
                              0}%`,
                          }}
                        />
                      </div>
                      <span className="score-pct">
                        {score.engine_confidence ??
                          item.match_confidence ??
                          0}
                        %
                      </span>
                    </div>
                    <p className="confidence-field-summary">
                      {(() => {
                        const passed = components.filter((c) => c.passed);
                        const total = components.length;
                        const fieldScore = total
                          ? Math.round(
                              passed.reduce((s, c) => s + c.weight, 0),
                            )
                          : null;
                        const engineConf =
                          score.engine_confidence ??
                          item.match_confidence ??
                          0;
                        const overridden =
                          total > 0 &&
                          fieldScore !== null &&
                          fieldScore !== engineConf;
                        if (total > 0) {
                          return overridden
                            ? `Field evidence: ${passed.length} / ${total} fields matched (${fieldScore}% weighted score — rule override to ${engineConf}% due to variance)`
                            : `Field evidence: ${passed.length} / ${total} fields matched (${fieldScore}% weighted score)`;
                        }
                        return (
                          score.decision_basis ||
                          'Evidence breakdown captured by the engine.'
                        );
                      })()}
                    </p>
                    {batchAvg != null && item.match_confidence != null && (
                      <p
                        className={`confidence-trend${
                          item.match_confidence < batchAvg - 20 ? ' outlier' : ''
                        }`}
                      >
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
                        <Tag
                          tone={
                            c.passed
                              ? 'success'
                              : c.weight >= 30
                                ? 'danger'
                                : 'warning'
                          }
                        >
                          {c.passed
                            ? 'Pass'
                            : c.weight >= 30
                              ? 'Fail'
                              : 'Low'}
                        </Tag>
                        <strong>{c.component}</strong>
                        <span
                          className="evidence-score"
                          title="Points scored / points available"
                        >
                          {c.passed ? c.weight : 0}
                          &nbsp;/&nbsp;
                          {c.weight}
                        </span>
                        <p>{c.evidence}</p>
                      </div>
                    ))}
                    {!components.length && (
                      <p className="empty small">No field-level evidence stored.</p>
                    )}
                  </div>
                </>
              );
            })()}
          </Panel>
          {suggestions.length > 0 && (
            <Panel title="Suggested actions" className="nested-panel">
              <div className="action-stack">
                {suggestions.map((s, idx) => {
                  const cfg = actionConfig(s.action);
                  return (
                    <div
                      className={`suggestion suggestion-${cfg.tone}`}
                      key={idx}
                    >
                      <strong>{cfg.label}</strong>
                      {cfg.desc && (
                        <p className="suggestion-desc">{cfg.desc}</p>
                      )}
                    </div>
                  );
                })}
              </div>
            </Panel>
          )}
          {similarCases?.count > 0 && (
            <div className="nested-panel similar-panel">
              <button
                className="similar-header"
                onClick={() => setSimilarOpen((o) => !o)}
              >
                <span>
                  {similarCases.count} similar resolved case
                  {similarCases.count !== 1 ? 's' : ''}
                </span>
                <span className="similar-chevron">
                  {similarOpen ? '▲' : '▼'}
                </span>
              </button>
              {similarOpen && (
                <div className="similar-list">
                  {similarCases.items.map((s) => (
                    <div className="similar-item" key={s.case_id}>
                      <span className="similar-rule">
                        {ruleLabel(s.rule_applied)}
                      </span>
                      <Tag tone={classForStatus(s.reconciliation_status)}>
                        {s.reconciliation_status}
                      </Tag>
                      <span className="similar-date">
                        {s.updated_at?.slice(0, 10) || ''}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
        {item.exception_flag === 'Y' &&
          (() => {
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
            const isNoMatch = NO_MATCH_STATUSES.includes(
              item.reconciliation_status,
            );
            const isBankOnly =
              item.reconciliation_status === 'Bank-only Item - Investigation';
            const isLedgerPost =
              item.reconciliation_status === 'Post to Short or Over Ledger';

            if (!isMatch && !isNoMatch && !overrideMode) return null;

            if (isNoMatch) {
              return (
                <div className="drawer-footer no-match-footer">
                  <p className="no-match-hint">
                    No bank match \u2014 choose how to action this item:
                  </p>
                  <button
                    className="btn secondary full"
                    disabled={noMatchLoading != null}
                    onClick={() =>
                      submitNoMatch('ROUTE_TO_EXCEPTION', 'NO_BANK_MATCH')
                    }
                  >
                    {noMatchLoading === 'ROUTE_TO_EXCEPTION'
                      ? 'Routing\u2026'
                      : 'Route to Exception Queue'}
                  </button>
                  {!isBankOnly && (
                    <button
                      className="btn ghost full"
                      disabled={noMatchLoading != null}
                      onClick={() =>
                        submitNoMatch(
                          'POST_TO_LEDGER',
                          'NO_ACCEPTABLE_CANDIDATES',
                        )
                      }
                    >
                      {noMatchLoading === 'POST_TO_LEDGER'
                        ? 'Posting\u2026'
                        : 'Post to Short / Over Ledger'}
                         </button>
                  )}
                </div>
              );
            }

            return (
              <div className="drawer-footer">
                {!overrideMode ? (
                  <>
                    <button
                      className="btn primary full"
                      onClick={() => onResolve(item)}
                    >
                      {isLedgerPost ? 'Confirm Ledger Post' : 'Confirm Resolution'}
                    </button>
                    <button
                      className="btn secondary full"
                      onClick={() => setOverrideMode(true)}
                    >
                      Override AI
                    </button>
                  </>
                ) : (
                  <div className="override-panel">
                    <label className="override-label">
                      Reason for override
                    </label>
                    <select
                      className="override-select"
                      value={overrideReason}
                      onChange={(e) => setOverrideReason(e.target.value)}
                    >
                      <option value="">— Select a reason —</option>
                      <option value="same_entity_diff_name">
                        Same entity, different name format
                      </option>
                      <option value="known_alias">
                        Known counterparty alias
                      </option>
                      <option value="data_entry_error">
                        Data entry error in source system
                      </option>
                      <option value="timing_difference">
                        Timing difference (split settlement)
                      </option>
                      <option value="other">Other</option>
                    </select>
                    {overrideReason === 'other' && (
                      <textarea
                        className="override-note"
                        placeholder="Describe the reason..."
                        value={overrideNote}
                        onChange={(e) => setOverrideNote(e.target.value)}
                        rows={3}
                      />
                    )}
                    <button
                      className="btn primary full"
                      onClick={submitOverride}
                      disabled={
                        !overrideReason ||
                        (overrideReason === 'other' &&
                          !overrideNote.trim()) ||
                        overrideLoading
                      }
                    >
                      {overrideLoading ? 'Submitting\u2026' : 'Submit Override'}
                    </button>
                    <button
                      className="btn link"
                      onClick={() => setOverrideMode(false)}
                    >
                      \u2190 Back
                    </button>
                  </div>
                )}
              </div>
            );
          })()}
        {!shortcutsHidden && (
          <div className="shortcut-legend">
            <span>
              ← → navigate &nbsp;·&nbsp; R confirm &nbsp;·&nbsp; O override
              &nbsp;·&nbsp; Esc close
            </span>
            <button
              className="btn link small"
              onClick={() => {
                setShortcutsHidden(true);
                localStorage.setItem('hideDrawerShortcuts', '1');
              }}
            >
              hide
            </button>
          </div>
        )}
      </aside>
    </>
  );
}

function SummaryBar({ summary = {}, total = 0, activeFilter, onFilter }) {
  const statuses = summary.statuses || [];
  const statusCount = (match) =>
    statuses
      .filter((s) => match(s.reconciliation_status || ''))
      .reduce((acc, s) => acc + (s.count || 0), 0);
  const exceptionCount = summary.raw?.kpi?.exception_count ?? 0;
  const aiSuggestedCount = statusCount(
    (s) => s === 'AI-Assisted Suggested Match',
  );
  const chips = [
    { label: 'Total', value: total, filter: '' },
    {
      label: 'Matched',
      value: statusCount(
        (s) => s.includes('Matched') || s.includes('Auto-Close'),
      ),
      filter: 'Matched & Settled (Auto-Close)',
    },
    {
      label: 'AI Suggested',
      value: aiSuggestedCount,
      filter: 'AI-Assisted Suggested Match',
    },
    {
      label: 'Exceptions',
      value: exceptionCount - aiSuggestedCount,
      filter: 'exceptions',
    },
    {
      label: 'In-Transit',
      value: statusCount(
        (s) => s.includes('In-Transit') || s.includes('Uncleared'),
      ),
      filter: 'Uncleared / In-Transit Payment',
    },
  ];
  return (
    <div className="summary-bar">
      {chips.map((c) => (
        <button
          key={c.label}
          className={`chip${activeFilter === c.filter ? ' active' : ''}`}
          onClick={() => onFilter(c.filter)}
        >
          <strong>{c.value}</strong>
          <span>{c.label}</span>
        </button>
      ))}
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
      setTimeout(() => setStepIdx(i + 1), s.duration),
    );
    const dotTimer = setInterval(
      () => setDots((d) => (d.length >= 3 ? '' : d + '.')),
      500,
    );
    return () => {
      timers.forEach(clearTimeout);
      clearInterval(dotTimer);
    };
  }, []);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(16,32,51,0.55)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 200,
      }}
    >
      <div
        style={{
          background: 'var(--panel)',
          borderRadius: '20px',
          padding: '2rem 2.5rem',
          maxWidth: '420px',
          width: '100%',
          boxShadow: '0 24px 60px rgba(0,0,0,0.25)',
          display: 'flex',
          flexDirection: 'column',
          gap: '1.25rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--primary)"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 2a10 10 0 1 0 10 10" />
            <path d="M12 6v6l4 2" />
          </svg>
          <strong style={{ fontSize: '1rem', color: 'var(--ink)' }}>
            AI triage running{dots}
          </strong>
        </div>
        <div
          style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}
        >
          {steps.map((s, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.6rem',
                opacity: i > stepIdx ? 0.35 : 1,
              }}
            >
              {i < stepIdx ? (
                <span
                  style={{
                    color: 'var(--good)',
                    fontSize: '1rem',
                    lineHeight: 1,
                  }}
                >
                  ✓
                </span>
              ) : i === stepIdx ? (
                <span
                  style={{
                    width: '14px',
                    height: '14px',
                    border: '2.5px solid var(--primary)',
                    borderTopColor: 'transparent',
                    borderRadius: '50%',
                    display: 'inline-block',
                    animation: 'spin 0.7s linear infinite',
                  }}
                />
              ) : (
                <span
                  style={{
                    width: '14px',
                    height: '14px',
                    border: '2px solid var(--line)',
                    borderRadius: '50%',
                    display: 'inline-block',
                  }}
                />
              )}
              <span
                style={{
                  fontSize: '0.85rem',
                  color:
                    i === stepIdx ? 'var(--ink)' : 'var(--muted)',
                  fontWeight: i === stepIdx ? 600 : 400,
                }}
              >
                {s.label}
              </span>
            </div>
          ))}
        </div>
        <p
          style={{
            fontSize: '0.75rem',
            color: 'var(--muted)',
            margin: 0,
          }}
        >
          LLM adjudication typically takes 10–30 seconds. Results will load
          automatically.
        </p>
      </div>
    </div>
  );
}

function ResultsWorkbench({
  results,
  summary,
  selected,
  setSelected,
  refreshResults,
  onAiTriage,
  loading,
  triageRunning,
}) {
  const [search, setSearch] = useState('');
  const [exceptionOnly, setExceptionOnly] = useState(false);
  const [selectedStatus, setSelectedStatus] = useState('');
  const [page, setPage] = useState(0);

  const total = results.total || 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);
  const from = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const to = Math.min((page + 1) * PAGE_SIZE, total);
  const countLabel =
    total === 0 ? 'No records' : `Showing ${from}\u2013${to} of ${total}`;

  const activeFilter = exceptionOnly ? 'exceptions' : selectedStatus;

  const onFilter = (filter) => {
    setPage(0);
    if (filter === '') {
      setSelectedStatus('');
      setExceptionOnly(false);
      refreshResults({
        status: '',
        exceptionOnly: false,
        limit: PAGE_SIZE,
        offset: 0,
      });
    } else if (filter === 'exceptions') {
      setExceptionOnly(true);
      setSelectedStatus('');
      refreshResults({
        exceptionOnly: true,
        status: '',
        limit: PAGE_SIZE,
        offset: 0,
      });
    } else {
      setSelectedStatus(filter);
      setExceptionOnly(false);
      refreshResults({
        status: filter,
        exceptionOnly: false,
        limit: PAGE_SIZE,
        offset: 0,
      });
    }
  };

  const runSearch = () => {
    setPage(0);
    refreshResults({
      search,
      exceptionOnly,
      status: selectedStatus,
      limit: PAGE_SIZE,
      offset: 0,
    });
  };

  const batchAvg = useMemo(() => {
    const vals = (results.items || [])
      .map((r) => r.match_confidence)
      .filter((v) => v != null && v > 0);
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
          <p>
            Drill into match evidence, failed fields, confidence and
            next-best action.
          </p>
        </div>
        <div
          className="toolbar"
          style={{
            flexWrap: 'nowrap',
            gap: '0.5rem',
            alignItems: 'center',
          }}
        >
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: '0.5rem',
              alignItems: 'center',
              flex: 1,
              minWidth: 0,
            }}
          >
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
                refreshResults({
                  search,
                  exceptionOnly,
                  status: val,
                  limit: PAGE_SIZE,
                  offset: 0,
                });
              }}
              style={{ minWidth: '160px' }}
            >
              <option value="">All statuses</option>
              {STATUS_OPTIONS.filter(Boolean).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
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
                  refreshResults({
                    search,
                    exceptionOnly: val,
                    status: selectedStatus,
                    limit: PAGE_SIZE,
                    offset: 0,
                  });
                }}
              />{' '}
              Exceptions only
            </label>
          </div>
          <span
            style={{
              borderLeft: '1px solid var(--border)',
              height: '1.5rem',
              flexShrink: 0,
            }}
          />
          <button
            className="btn primary"
            style={{ flexShrink: 0, whiteSpace: 'nowrap' }}
            disabled={loading}
            onClick={onAiTriage}
          >
            Run AI triage
          </button>
        </div>
      </div>
      <SummaryBar
        summary={summary}
        total={total}
        activeFilter={activeFilter}
        onFilter={onFilter}
      />
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.25rem 0',
        }}
      >
        <div
          style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}
        >
          <button
            className="btn secondary"
            disabled={page === 0}
            onClick={() => {
              const p = page - 1;
              setPage(p);
              refreshResults({
                search,
                exceptionOnly,
                status: selectedStatus,
                limit: PAGE_SIZE,
                offset: p * PAGE_SIZE,
              });
            }}
          >
            ← Prev
          </button>
          <span
            style={{
              fontSize: '0.85rem',
              color: 'var(--muted, #888)',
            }}
          >
            Page {page + 1} of {totalPages || 1}
          </span>
          <button
            className="btn secondary"
            disabled={page >= totalPages - 1}
            onClick={() => {
              const p = page + 1;
              setPage(p);
              refreshResults({
                search,
                exceptionOnly,
                status: selectedStatus,
                limit: PAGE_SIZE,
                offset: p * PAGE_SIZE,
              });
            }}
          >
            Next →
          </button>
        </div>
        <span
          style={{
            fontSize: '0.8rem',
            color: 'var(--muted, #888)',
          }}
        >
          {countLabel}
        </span>
      </div>
      <ResultTable rows={results.items || []} onSelect={setSelected} />
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.5rem 0',
          gap: '0.75rem',
        }}
      >
        <div
          style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}
        >
          <button
            className="btn secondary"
            disabled={page === 0}
            onClick={() => {
              const p = page - 1;
              setPage(p);
              refreshResults({
                search,
                exceptionOnly,
                status: selectedStatus,
                limit: PAGE_SIZE,
                offset: p * PAGE_SIZE,
              });
            }}
          >
            ← Prev
          </button>
          <span
            style={{
              fontSize: '0.85rem',
              color: 'var(--muted, #888)',
            }}
          >
            Page {page + 1} of {totalPages || 1}
          </span>
          <button
            className="btn secondary"
            disabled={page >= totalPages - 1}
            onClick={() => {
              const p = page + 1;
              setPage(p);
              refreshResults({
                search,
                exceptionOnly,
                status: selectedStatus,
                limit: PAGE_SIZE,
                offset: p * PAGE_SIZE,
              });
            }}
          >
            Next →
          </button>
        </div>
        <span
          style={{
            fontSize: '0.8rem',
            color: 'var(--muted, #888)',
          }}
        >
          {countLabel}
        </span>
      </div>
      <EvidenceDrawer
        selected={selected}
        onClose={() => setSelected(null)}
        onResolve={setSelected}
        onRefresh={() =>
          refreshResults({
            search,
            exceptionOnly,
            status: selectedStatus,
            limit: PAGE_SIZE,
            offset: page * PAGE_SIZE,
          })
        }
        rows={results.items || []}
        selectedIndex={(results.items || []).findIndex(
          (r) => r.result_id === selected?.result_id,
        )}
        onPrev={() => {
          const idx = (results.items || []).findIndex(
            (r) => r.result_id === selected?.result_id,
          );
          if (idx > 0) setSelected(results.items[idx - 1]);
        }}
        onNext={() => {
          const idx = (results.items || []).findIndex(
            (r) => r.result_id === selected?.result_id,
          );
          if (idx < (results.items || []).length - 1)
            setSelected(results.items[idx + 1]);
        }}
        onSelect={setSelected}
        batchAvg={batchAvg}
      />
    </section>
  );
}

function ManualResolveModal({ exceptionItem, onClose, onSubmit }) {
  const suggestions = exceptionItem?.suggestions || [];
  const aiSuggestion = suggestions.find(
    (s) => s.action === 'CONFIRM_AI_MATCH' || s.action === 'ROUTE_TO_ANALYST',
  );
  const isAiPreFilled = !!aiSuggestion;

  const defaultReason = isAiPreFilled
    ? 'AI_ASSISTED_MATCH'
    : 'REMITTANCE_FORMAT_MISMATCH';
  const defaultComment = isAiPreFilled
    ? `AI triage suggested this match (confidence ${Math.round(
        (aiSuggestion.confidence || 0) * 100,
      )}%). ${exceptionItem?.explanation || ''} Analyst reviewed and confirmed.`
    : 'Analyst confirmed this case after checking invoice, amount and counterparty evidence.';

  const [reason, setReason] = useState(defaultReason);
  const [resolutionType, setResolutionType] = useState('MATCHED_MANUAL');
  const [comment, setComment] = useState(defaultComment);
  const [fields, setFields] = useState([
    'invoice_suffix',
    'amount',
    'counterparty',
  ]);
  if (!exceptionItem) return null;
  const fieldOptions = [
    'reference',
    'invoice',
    'invoice_suffix',
    'amount',
    'currency',
    'counterparty',
    'booking_date',
    'remittance_text',
  ];
  const toggleField = (f) =>
    setFields((prev) =>
      prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f],
    );
  return (
    <div className="modal-backdrop">
      <div className="modal large">
        <div className="eyebrow">Human-in-loop learning</div>
        {isAiPreFilled && (
          <div
            className="eyebrow"
            style={{ color: '#7c3aed', marginBottom: '8px' }}
          >
            ✦ AI pre-filled · review before confirming
          </div>
        )}
        <h2>Resolve exception and record learning signal</h2>
        <p>
          Case {exceptionItem.result_id}. The engine records trusted fields,
          selected outcome and reason code as governed learning data.
        </p>
        <div className="grid two no-gap">
          <div className="form-grid">
            <label>Resolution type</label>
            <select
              value={resolutionType}
              onChange={(e) => setResolutionType(e.target.value)}
            >
              <option value="MATCHED_MANUAL">Manual match</option>
              <option value="LEDGER_ALLOCATION">Ledger allocation</option>
              <option value="IN_TRANSIT">In-transit / wait for next CAMT</option>
              <option value="BANK_ONLY_INVESTIGATION">
                Bank-only investigation
              </option>
            </select>
            <label>Reason code</label>
            <select
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            >
              {isAiPreFilled && (
                <option value="AI_ASSISTED_MATCH">
                  AI-assisted match (analyst confirmed)
                </option>
              )}
              <option value="REMITTANCE_FORMAT_MISMATCH">
                Remittance format mismatch
              </option>
              <option value="COUNTERPARTY_ALIAS">
                Counterparty alias issue
              </option>
              <option value="BATCH_SETTLEMENT">Batch settlement grouping</option>
              <option value="DELAYED_BANK_POSTING">
                Delayed bank posting
              </option>
              <option value="MINOR_AMOUNT_VARIANCE">
                Minor amount variance
              </option>
            </select>
          </div>
          <div>
            <label className="label">Fields trusted by analyst</label>
            <div className="chip-row">
              {fieldOptions.map((f) => (
                <button
                  key={f}
                  className={`chip${fields.includes(f) ? ' active' : ''}`}
                  onClick={() => toggleField(f)}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>
        </div>
        <label className="label">Comment</label>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn primary"
            onClick={() =>
              onSubmit(
                exceptionItem,
                resolutionType,
                reason,
                comment,
                fields,
              )
            }
          >
            Confirm and learn
          </button>
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
          <p>
            Automated workflow rules can label date breaks, assign owners, add
            comments, escalate aged items and capture learning signals.
          </p>
        </div>
      </div>

      <Panel title="Workflow rules" subtitle="Business-readable exception automation">
        <div className="workflow-grid">
          {(workflowRules?.items || []).map((r) => (
            <div className="workflow-card" key={r.rule_id}>
              <div>
                <Tag tone={r.enabled ? 'success' : 'neutral'}>
                  {r.enabled ? 'Enabled' : 'Off'}
                </Tag>
              </div>
              <strong>{r.name}</strong>
              <p>{r.condition}</p>
              <ul>
                {r.actions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Panel>

      <Panel
        title="Open exception queue"
        subtitle="Operational view with owner, SLA, priority, variance and match confidence"
      >
        <div className="table-wrap exception-table">
          <table>
            <thead>
              <tr>
                <th>Case</th>
                <th>Priority</th>
                <th>Owner</th>
                <th>Workflow</th>
                <th>SLA due</th>
                <th>Status</th>
                <th>Variance</th>
                <th>Confidence</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.case_id || r.result_id}>
                  <td>
                    <strong>{r.case_id || r.result_id}</strong>
                    <br />
                    <span className="muted">{r.psr_id || r.camt_id}</span>
                  </td>
                  <td>
                    <Tag tone={classForStatus(r.priority)}>
                      {r.priority || 'Medium'}
                    </Tag>
                  </td>
                  <td>{r.owner || 'Unassigned'}</td>
                  <td>{r.workflow_status || 'NEW'}</td>
                  <td>{r.sla_due_at || '-'}</td>
                  <td>
                    <Tag tone={classForStatus(r.reconciliation_status)}>
                      {r.reconciliation_status}
                    </Tag>
                  </td>
                  <td>{money(r.variance)}</td>
                  <td>{r.match_confidence}%</td>
                  <td className="action-cell">
                    <button
                      className="btn secondary"
                      onClick={() =>
                        onWorkflowUpdate(r.case_id || r.result_id, {
                          owner: 'analyst_01',
                          workflow_status: 'IN_REVIEW',
                          comment: 'Assigned from exception queue',
                        })
                      }
                    >
                      Assign
                    </button>
                    <button
                      className="btn ghost"
                      onClick={() =>
                        onWorkflowUpdate(r.case_id || r.result_id, {
                          priority: 'High',
                          comment: 'Escalated by analyst',
                        })
                      }
                    >
                      Escalate
                    </button>
                    <button
                      className="btn primary"
                      onClick={() => onResolveClick(r)}
                    >
                      Resolve
                    </button>
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan="9" className="empty">
                    No open exceptions.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </section>
  );
}

function AutoPatternRecon() {
  const [camtFile, setCamtFile] = useState(null);
  const [flatFile, setFlatFile] = useState(null);
  const [useLlm, setUseLlm] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [psrCount, setPsrCount] = useState(null);
  const [showConfDetail, setShowConfDetail] = useState(false);
  const [sampleDetail, setSampleDetail] = useState(null);

  const onSubmit = async () => {
    if (!camtFile || !flatFile) return;
    setError('');
    setLoading(true);
    try {
      const flatContent = await flatFile.text();
      const lines = flatContent
        .split(/\r?\n/)
        .filter((l) => l.trim().length > 0);
      setPsrCount(lines.length);

      const formData = new FormData();
      formData.append('camt_file', camtFile);
      formData.append('flat_file', flatFile);

      const data = useLlm
        ? await api.reverseEngineer.reconcileLlm(formData)
        : await api.reverseEngineer.reconcile(formData);

      setResult(data);
    } catch (e) {
      setError(e.message || 'Unexpected error');
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const regexPattern = result?.regex_pattern || '';
  const samples = Array.isArray(result?.samples) ? result.samples : [];
  const topMatches = Array.isArray(result?.top_matches) ? result.top_matches : [];
  const matchCount = samples.length;
  const breakdown = result?.confidence_breakdown || null;
  const overallConfidence =
    typeof result?.confidence_score === 'number'
      ? result.confidence_score
      : null;

  // Derived metrics for modal
  const avgPairConf = (() => {
    if (!samples.length) return 0;
    const vals = samples
      .map((s) => Number(s.pair_confidence || 0))
      .filter((v) => !Number.isNaN(v));
    if (!vals.length) return 0;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  })();

  const highCov = (() => {
    if (!samples.length) return 0;
    const vals = samples
      .map((s) => Number(s.pair_confidence || 0))
      .filter((v) => !Number.isNaN(v));
    if (!vals.length) return 0;
    const strong = vals.filter((v) => v >= 0.75).length;
    return strong / vals.length;
  })();

  // Overall confidence recomputed from components (for explanation only).
  const recomputedOverall = 0.5 * avgPairConf + 0.5 * highCov;

  // Per-sample details: how its pair_confidence contributes relative to avg and threshold
  const computeSampleNarrative = (pair) => {
    const v = Number(pair || 0);
    if (Number.isNaN(v)) return 'No confidence score available.';
    if (v >= 0.75) return 'High-confidence pair (≥ 0.75) — contributes positively to both average and coverage.';
    if (v >= avgPairConf) return 'Above average pair confidence — lifts the overall score but below the 0.75 coverage threshold.';
    if (v > 0) return 'Below average pair confidence — drags the overall score down.';
    return 'Very low confidence — treated as noise by the aggregation.';
  };

  // Per top_match details: same explanation logic on its pair_confidence
  const computeTopMatchNarrative = (pair) => computeSampleNarrative(pair);

  return (
    <section className="screen">
      <div className="screen-title">
        <div>
          <div className="eyebrow">Auto pattern reverse-engineering</div>
          <h1>Discover PSR flat-file patterns from CAMT.053 anchors</h1>
          <p>
            Upload a CAMT.053 XML and an unknown PSR flat file. The engine will
            reverse-engineer the pattern and propose a regex with confidence
            scoring. Optionally delegate pattern discovery to an LLM.
          </p>
        </div>
      </div>

      <div className="grid two">
        <Panel
          title="Upload files"
          subtitle="Provide a CAMT.053 XML and the corresponding PSR flat file"
        >
          <div className="form-grid">
            <label>CAMT.053 XML file</label>
            <input
              type="file"
              accept=".xml,application/xml,text/xml"
              onChange={(e) => setCamtFile(e.target.files?.[0] || null)}
            />

            <label>PSR / flat file</label>
            <input
              type="file"
              accept=".txt,.dat,.psr,text/plain"
              onChange={(e) => setFlatFile(e.target.files?.[0] || null)}
            />

            <label className="toggle">
              <input
                type="checkbox"
                checked={useLlm}
                onChange={(e) => setUseLlm(e.target.checked)}
              />
              AI-based pattern discovery
            </label>

            <button
              className="btn primary"
              disabled={!camtFile || !flatFile || loading}
              onClick={onSubmit}
            >
              {loading ? 'Running…' : 'Identify RegEx Pattern'}
            </button>

            {error && (
              <p
                className="error small"
                style={{ marginTop: '0.5rem' }}
              >
                {error}
              </p>
            )}
          </div>
        </Panel>

        <Panel
          title="Pattern summary"
          subtitle="Regex output, confidence and record counts"
        >
          <dl className="kv">
            <dt>Mode</dt>
            <dd>
              {useLlm
                ? 'AI-based discovery'
                : 'Heuristic reverse engineer'}
            </dd>

            <dt>PSR records (flat file)</dt>
            <dd>{psrCount != null ? psrCount : '—'}</dd>

            <dt>{useLlm ? 'LLM training samples' : 'Matched samples'}</dt>
            <dd>{matchCount}</dd>

            <dt>Confidence score</dt>
            <dd>
              {result ? (
                <button
                  type="button"
                  className="link-button"
                  onClick={() => setShowConfDetail(true)}
                  title="Click to see how this confidence was calculated"
                  style={{
                    padding: 0,
                    border: 'none',
                    background: 'none',
                    color: 'var(--primary)',
                    cursor: 'pointer',
                    font: 'inherit',
                  }}
                >
                  {overallConfidence != null
                    ? `${(overallConfidence * 100).toFixed(1)}%`
                    : '0%'}
                </button>
              ) : (
                '—'
              )}
            </dd>

            {useLlm && result?.confidence_explanation && (
              <>
                <dt>Confidence explanation</dt>
                <dd>{result.confidence_explanation}</dd>
              </>
            )}

            {!useLlm && breakdown && (
              <>
                <dt>Structural consistency</dt>
                <dd>
                  {`${(breakdown.structural_consistency ?? 0).toFixed(2)}%`}
                </dd>

                <dt>Data integrity</dt>
                <dd>
                  {`${(breakdown.data_integrity ?? 0).toFixed(2)}%`}
                </dd>

                <dt>Edge-case resilience</dt>
                <dd>
                  {`${(breakdown.edge_case_resilience ?? 0).toFixed(2)}%`}
                </dd>

                <dt>Financial reconciliation</dt>
                <dd>
                  {`${(breakdown.financial_reconciliation ?? 0).toFixed(2)}%`}
                </dd>
              </>
            )}
          </dl>
          <div style={{ marginTop: '1rem' }}>
            <label className="label">Regex pattern</label>
            <textarea
              readOnly
              value={regexPattern}
              rows={6}
              style={{
                width: '100%',
                fontFamily: 'monospace',
                fontSize: '0.8rem',
              }}
              placeholder="Run auto pattern recon to see the inferred regex pattern…"
            />
          </div>
        </Panel>
      </div>

      {useLlm && result && (
        <div style={{ marginTop: '2rem' }}>
          <div className="grid two">
            <Panel
              title="LLM training samples"
              subtitle="High-confidence CAMT ↔ PSR pairs sent to the LLM"
            >
              <div
                className="table-wrap compact tight"
                style={{ maxHeight: '360px', overflowY: 'auto' }}
              >
                <table>
                  <thead>
                    <tr>
                      <th>TX ID</th>
                      <th>Booking date</th>
                      <th>Amount</th>
                      <th>Flat line</th>
                      <th>Pair confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {samples.length > 0 ? (
                      samples.map((s, idx) => (
                        <tr key={idx}>
                          <td>{s.camt?.transaction_id}</td>
                          <td>{s.camt?.booking_date || '—'}</td>
                          <td>
                            {s.camt?.amount != null
                              ? `${s.camt.amount} ${s.camt?.currency || ''}`
                              : '—'}
                          </td>
                          <td>
                            <code>{s.flat_raw_line}</code>
                          </td>
                          <td>
                            <button
                              type="button"
                              className="link-button"
                              onClick={() => setSampleDetail(s)}
                              title="View detailed confidence breakdown for this pair"
                              style={{
                                padding: 0,
                                border: 'none',
                                background: 'none',
                                color: 'var(--primary)',
                                cursor: 'pointer',
                                font: 'inherit',
                                textDecoration: 'underline',
                              }}
                            >
                              {(Number(s.pair_confidence || 0) * 100).toFixed(1)}%
                            </button>
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={5} className="empty small">
                          No LLM samples returned. Run auto pattern recon to
                          generate training pairs.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Panel>

            <Panel
              title="Top matches per transaction"
              subtitle="Best flat-file line per CAMT transaction with matched signals"
            >
              <div
                className="table-wrap compact tight"
                style={{ maxHeight: '360px', overflowY: 'auto' }}
              >
                <table>
                  <thead>
                    <tr>
                      <th>TX ID</th>
                      <th>Flat line #</th>
                      <th>Flat line</th>
                      <th>Pair confidence</th>
                      <th>Signals</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topMatches.map((m, idx) => {
                      return (
                        <tr key={idx}>
                          <td>{m.camt_transaction_id}</td>
                          <td>{m.flat_line_number}</td>
                          <td>
                            <code>{m.flat_raw_line}</code>
                          </td>
                          <td>
                            <button
                              type="button"
                              className="link-button"
                              onClick={() =>
                                setSampleDetail({
                                  camt: { transaction_id: m.camt_transaction_id },
                                  flat_raw_line: m.flat_raw_line,
                                  pair_confidence: m.pair_confidence,
                                  pair_components: m.pair_components,
                                  pair_explanation: m.pair_explanation,
                                })
                              }
                              title="View detailed confidence breakdown for this pair"
                              style={{
                                padding: 0,
                                border: 'none',
                                background: 'none',
                                color: 'var(--primary)',
                                cursor: 'pointer',
                                font: 'inherit',
                                textDecoration: 'underline',
                              }}
                            >
                              {(Number(m.pair_confidence || 0) * 100).toFixed(1)}%
                            </button>
                          </td>
                          <td>
                            {Array.isArray(m.matched_signals)
                              ? m.matched_signals.join(', ')
                              : ''}
                          </td>
                        </tr>
                      );
                    })}
                    {!topMatches.length && (
                      <tr>
                        <td colSpan={5} className="empty small">
                          No top matches returned. Run auto pattern recon to see
                          CAMT ↔ PSR evidence.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>
        </div>
      )}

      {sampleDetail && (
        <div
          className="modal-backdrop"
          onClick={() => setSampleDetail(null)}
        >
          <div
            className="modal"
            style={{ maxWidth: '780px' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="eyebrow">Pair confidence breakdown</div>
            <h2>
              Why is this pair{' '}
              {(Number(sampleDetail.pair_confidence || 0) * 100).toFixed(1)}%
              ?
            </h2>

            <p
              className="small muted"
              style={{ maxWidth: '640px', marginTop: '0.5rem' }}
            >
              This score comes from the same matcher used in the Results
              Workbench. Each component below contributes weight based on how
              strongly PSR and CAMT values align.
            </p>

            <div className="kv compact" style={{ marginTop: '0.75rem' }}>
              <dl>
                <dt>Transaction</dt>
                <dd>
                  {sampleDetail.camt?.transaction_id || '—'} ↔{' '}
                  <code style={{ whiteSpace: 'pre-wrap' }}>
                    {sampleDetail.flat_raw_line}
                  </code>
                </dd>
                {sampleDetail.pair_explanation && (
                  <>
                    <dt>Summary</dt>
                    <dd>{sampleDetail.pair_explanation}</dd>
                  </>
                )}
              </dl>
            </div>

            <div
              className="table-wrap compact tight"
              style={{
                maxHeight: '260px',
                overflowY: 'auto',
                marginTop: '1rem',
              }}
            >
              <table>
                <thead>
                  <tr>
                    <th>Component</th>
                    <th>PSR value</th>
                    <th>CAMT value</th>
                    <th>Weight</th>
                    <th>Result</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {Array.isArray(sampleDetail.pair_components) &&
                  sampleDetail.pair_components.length ? (
                    sampleDetail.pair_components.map((c, idx) => (
                      <tr key={idx}>
                        <td>{c.component}</td>
                        <td>{c.raw_value_psr ?? '—'}</td>
                        <td>{c.raw_value_camt ?? '—'}</td>
                        <td>{c.weight}</td>
                        <td>
                          <span
                            className={
                              c.passed
                                ? 'tag success'
                                : c.weight >= 30
                                ? 'tag danger'
                                : 'tag warning'
                            }
                          >
                            {c.passed
                              ? 'Pass'
                              : c.weight >= 30
                              ? 'Fail'
                              : 'Low'}
                          </span>
                        </td>
                        <td>{c.evidence}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={6} className="empty small">
                        No per-field breakdown available for this pair.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <p className="small muted" style={{ marginTop: '0.75rem' }}>
              Overall pair confidence (
              {(Number(sampleDetail.pair_confidence || 0) * 100).toFixed(1)}%)
              is derived by combining the weighted component results above in
              the backend matcher.
            </p>

            <div className="modal-actions">
              <button
                className="btn ghost"
                onClick={() => setSampleDetail(null)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {showConfDetail && result && (
        <div
          className="modal-backdrop"
          onClick={() => setShowConfDetail(false)}
        >
          <div
            className="modal"
            style={{ maxWidth: '860px' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="eyebrow">Pattern confidence breakdown</div>
            <h2>
              How was the{' '}
              {overallConfidence != null
                ? `${(overallConfidence * 100).toFixed(1)}%`
                : 'overall'}
              {' '}score derived?
            </h2>

            <p
              className="small muted"
              style={{ marginTop: '0.5rem', maxWidth: '640px' }}
            >
              This score is computed on the backend from CAMT ↔ flat-file training
              pairs. The breakdown below surfaces the components the engine reports
              for this run.
            </p>

            <div
              className="kv compact"
              style={{
                marginTop: '0.9rem',
                display: 'grid',
                gridTemplateColumns: 'minmax(0, 1.1fr) minmax(0, 1.1fr)',
                gap: '1.25rem',
              }}
            >
              <dl>
                <dt>Backend overall score</dt>
                <dd style={{ fontSize: '0.95rem', fontWeight: 500 }}>
                  {overallConfidence != null
                    ? `${(overallConfidence * 100).toFixed(1)}%`
                    : '—'}
                </dd>

                <dt>Average pair confidence (samples)</dt>
                <dd>{(avgPairConf * 100).toFixed(1)}%</dd>

                <dt>High-confidence coverage (≥ 0.75, samples)</dt>
                <dd>{(highCov * 100).toFixed(1)}%</dd>
              </dl>

              {result.confidence_explanation && (
                <dl>
                  <dt>Narrative explanation</dt>
                  <dd>
                    <p
                      style={{
                        fontSize: '0.85rem',
                        lineHeight: 1.5,
                        margin: 0,
                      }}
                    >
                      {result.confidence_explanation}
                    </p>
                  </dd>
                </dl>
              )}
            </div>

            <hr
              style={{
                border: 'none',
                borderTop: '1px solid var(--border)',
                margin: '1.25rem 0 1rem',
              }}
            />

            <div className="modal-actions">
              <button
                className="btn ghost"
                onClick={() => setShowConfDetail(false)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
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
          <p>
            Role-based oversight for match rate, open exceptions, ageing,
            owners, root causes and rule performance.
          </p>
        </div>
        <button className="btn ghost" onClick={onExport}>
          Export results CSV
        </button>
      </div>

      <div className="metric-grid five">
        <Metric
          label="Total cases"
          value={summary.total_cases || 0}
          hint="Current run"
          tone="neutral"
        />
        <Metric
          label="Match rate"
          value={pct(summary.match_rate)}
          hint="Auto-closed cases"
          tone="success"
        />
        <Metric
          label="Open exceptions"
          value={summary.exceptions || 0}
          hint="Active workflow queue"
          tone="warning"
        />
        <Metric
          label="Avg confidence"
          value={pct(summary.average_confidence)}
          hint="Engine score"
          tone="info"
        />
        <Metric
          label="Abs variance"
          value={money(summary.absolute_variance || 0)}
          hint="Break exposure"
          tone="danger"
        />
      </div>

      <div className="grid two">
        <Panel title="Open cases by status">
          <BarList rows={charts.by_status || []} />
        </Panel>
        <Panel title="Open exceptions by ageing">
          <BarList rows={charts.by_age || []} />
        </Panel>
        <Panel title="Rule performance">
          <BarList rows={charts.by_rule || []} />
        </Panel>
        <Panel title="Root-cause categories">
          <BarList rows={charts.by_reason || []} />
        </Panel>
        <Panel title="Owner workload">
          <BarList rows={charts.by_owner || []} />
        </Panel>
        <Panel title="Priority distribution">
          <BarList rows={charts.by_priority || []} />
        </Panel>
      </div>

      <Panel
        title="Root-cause insight feed"
        subtitle="Actionable observations generated from current run and workflow state"
      >
        <div className="insight-list horizontal">
          {(dashboard?.root_cause_insights || []).map((i) => (
            <div className="insight" key={i}>
              <span>RC</span>
              <p>{i}</p>
            </div>
          ))}
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
          <p>
            Human-in-the-loop learning observes analyst behaviour and promotes
            candidate rules through approval gates.
          </p>
        </div>
        <div className="button-row">
          <button className="btn secondary" onClick={onSeed}>
            Seed demo learning
          </button>
          <button className="btn primary" onClick={onDiscover}>
            Discover patterns
          </button>
        </div>
      </div>

      <div className="grid two">
        <Panel
          title="Candidate pattern inbox"
          subtitle="New rules are suggestion-only until back-tested and approved"
        >
          <div className="candidate-list">
            {candidates.map((c) => (
              <div
                className="candidate"
                key={c.candidate_pattern_id}
              >
                <div>
                  <Tag tone={classForStatus(c.status)}>{c.status}</Tag>
                  <strong>{c.pattern_name}</strong>
                  <p>
                    {c.observed_case_count} observed cases ·{' '}
                    {c.backtest_precision}% prototype precision · false-positive
                    estimate {c.estimated_false_positive_rate}%
                  </p>
                </div>
                {c.status !== 'APPROVED' && (
                  <button
                    className="btn secondary"
                    onClick={() => onApprove(c.candidate_pattern_id)}
                  >
                    Approve suggestion
                  </button>
                )}
              </div>
            ))}
            {!candidates.length && (
              <p className="empty small">
                No learnt pattern candidates yet. Resolve exceptions or seed
                demo learning.
              </p>
            )}
          </div>
        </Panel>
        <Panel
          title="Learning event stream"
          subtitle="Structured analyst actions, not just audit text"
        >
          <div className="event-list">
            {events.slice(0, 8).map((e) => (
              <div className="event" key={e.event_id}>
                <strong>{e.event_type}</strong>
                <span>
                  {e.case_id} · {e.user_id} · {e.event_timestamp}
                </span>
              </div>
            ))}
            {!events.length && (
              <p className="empty small">No analyst actions captured yet.</p>
            )}
          </div>
        </Panel>
      </div>

      <Panel
        title="Promotion path"
        subtitle="Safety-first governance model for learned patterns"
      >
        <div className="promotion">
          {[
            'Manual resolution',
            'Feature extraction',
            'Candidate rule',
            'Back-test',
            'Lead approval',
            'Suggest only',
            'Auto-close eligible',
          ].map((s, idx) => (
            <div className="promo" key={s}>
              <span>{idx + 1}</span>
              {s}
            </div>
          ))}
        </div>
      </Panel>
    </section>
  );
}

function Assistant({ onAsk, answer }) {
  const [question, setQuestion] = useState(
    'Which exceptions should I prioritise today?',
  );
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
          <p>
            Ask reconciliation questions and trigger guided investigation from
            summary, workflow and learning state.
          </p>
        </div>
      </div>
      <Panel title="Ask the assistant">
        <div className="assistant-box">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <button className="btn primary" onClick={() => onAsk(question)}>
            Ask
          </button>
        </div>
        <div className="prompt-row">
          {prompts.map((q) => (
            <button
              className="btn ghost"
              key={q}
              onClick={() => {
                setQuestion(q);
                onAsk(q);
              }}
            >
              {q}
            </button>
          ))}
        </div>
        {answer && (
          <div className="assistant-answer">
            <strong>Assistant</strong>
            <p>{answer.answer}</p>
          </div>
        )}
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
          <p>
            Audit trail, snapshot governance, pattern approval and configuration
            evidence for regulated operations.
          </p>
        </div>
        <button className="btn primary" onClick={onSnapshot}>
          Create snapshot
        </button>
      </div>

      <div className="grid two">
        <Panel title="Process controls">
          <dl className="kv">
            <dt>Process ID</dt>
            <dd>{workspace?.process?.process_id || 'IRE-CASH-001'}</dd>
            <dt>Environment</dt>
            <dd>{workspace?.process?.environment || 'Prototype / UAT'}</dd>
            <dt>Owner</dt>
            <dd>{workspace?.process?.owner || 'Recon Ops Lead'}</dd>
            <dt>Last snapshot</dt>
            <dd>{workspace?.process?.last_snapshot || '-'}</dd>
          </dl>
        </Panel>
        <Panel title="Audit design">
          <div className="rule-grid">
            <div className="rule-card">
              <strong>Immutable user events</strong>
              <p>
                Manual resolutions and overrides are stored as append-only
                events.
              </p>
            </div>
            <div className="rule-card">
              <strong>Pattern approval</strong>
              <p>Learned rules require review before active use.</p>
            </div>
            <div className="rule-card">
              <strong>Suggestion-first learning</strong>
              <p>
                AI-derived logic does not auto-close until back-tested.
              </p>
            </div>
          </div>
        </Panel>
      </div>

      <Panel title="Audit trail">
        <div className="event-list audit-list">
          {events.map((e) => (
            <div className="event" key={e.event_id}>
              <strong>{e.event_type}</strong>
              <span>
                {e.event_timestamp} · {e.case_id} · {e.user_id}
              </span>
              <code>{JSON.stringify(e.event_payload)}</code>
            </div>
          ))}
          {!events.length && (
            <p className="empty small">No events recorded yet.</p>
          )}
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
  const [triageRunning, setTriageRunning] = useState(false);
  const [toast, setToast] = useState('');

  const refresh = async () => {
    const [
      summaryData,
      resultsData,
      exceptionsData,
      patternsData,
      candidatesData,
      eventsData,
      batchesData,
      workspaceData,
      submissionsData,
      previewData,
      predictionData,
      ruleData,
      workflowRuleData,
      dashboardData,
    ] = await Promise.all([
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

  useEffect(() => {
    refresh().catch(() => {});
  }, []);

  const refreshResults = async ({
    search = '',
    exceptionOnly = false,
    status = '',
    limit = PAGE_SIZE,
    offset = 0,
  } = {}) => {
    setResults(
      await api.results({ limit, offset, search, exceptionOnly, status }),
    );
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
    await safe(async () => {
      const result = await api.runBatch(batchId);
      setBatchRunResult(result);
    }, 'Uploaded batch reconciled');
  };

  const runAiTriage = async () => {
    let result;
    setTriageRunning(true);
    await safe(
      async () => {
        result = await api.aiTriage();
        await refreshResults({
          search: '',
          exceptionOnly: false,
          status: '',
        });
      },
      () => {
        const suggested =
          (result?.clear_count ?? 0) +
          (result?.llm_adjudicated_count ?? 0);
        const review =
          (result?.maybe_count ?? 0) -
          (result?.llm_adjudicated_count ?? 0);
        const parts = [];
        if (suggested) parts.push(`${suggested} suggested`);
        if (review > 0) parts.push(`${review} awaiting review`);
        return `AI triage complete — ${
          parts.length ? parts.join(', ') : '0 suggestions'
        }`;
      },
    );
    setTriageRunning(false);
  };

  const tunePattern = async (patternId, draft) => {
    await safe(
      () =>
        api.updatePattern(patternId, {
          execution_mode: draft.execution_mode,
          confidence_threshold: draft.confidence_threshold,
          pattern_rule: draft.pattern_rule,
        }),
      'Pattern configuration saved',
    );
  };

  const togglePattern = async (pattern) => {
    await safe(
      () =>
        pattern.status === 'ACTIVE'
          ? api.deactivatePattern(pattern.pattern_id)
          : api.activatePattern(pattern.pattern_id),
      'Pattern status updated',
    );
  };

  const createPattern = async (name) => {
    await safe(
      () =>
        api.createPattern
          ? api.createPattern({
              pattern_name: name,
              pattern_type: 'LEARNED_DRAFT',
              pattern_rule: {
                fields: ['invoice_suffix', 'amount', 'counterparty'],
                status: 'suggestion_only',
              },
              status: 'ACTIVE',
              execution_mode: 'SUGGESTION',
              confidence_threshold: 0.87,
              approved_by: 'prototype_user',
            })
          : Promise.resolve(),
      'Suggestion pattern created',
    );
  };

  const updateWorkflow = async (caseId, payload) => {
    await safe(
      () =>
        api.updateWorkflow(caseId, {
          ...payload,
          updated_by: 'analyst_01',
        }),
      'Exception workflow updated',
    );
  };

  const submitResolution = async (
    item,
    resolutionType,
    reason,
    comment,
    fields,
  ) => {
    await safe(
      () =>
        api.resolveException(item.result_id || item.case_id, {
          final_resolution_type: resolutionType,
          reason_code: reason,
          psr_transaction_ids: item.psr_id ? [item.psr_id] : [],
          bank_transaction_ids: item.camt_id ? [item.camt_id] : [],
          fields_used: fields,
          fields_ignored: ['exact_invoice_format', 'exact_pmt_ref'],
          user_comment: comment,
          learning_eligible: true,
        }),
      'Manual resolution captured as learning signal',
    );
    setModalItem(null);
  };

  const exportCsv = () => {
    window.open(api.exportResultsUrl(), '_blank', 'noopener,noreferrer');
  };

  const screen = useMemo(() => {
    if (active === 'workspace')
      return (
        <Workspace
          workspace={workspace}
          summary={summary}
          onLoad={() => safe(api.loadSampleData, 'Sample PSR/CAMT loaded')}
          onRun={() => safe(api.runRecon, 'Reconciliation completed')}
          onSnapshot={() => safe(api.createSnapshot, 'Snapshot created')}
          onExport={exportCsv}
          loading={loading}
        />
      );
    if (active === 'intake')
      return (
        <DataIntake
          batches={batches}
          submissions={submissions}
          selectedBatchId={selectedBatchId}
          setSelectedBatchId={setSelectedBatchId}
          quality={quality}
          batchRunResult={batchRunResult}
          onUpload={uploadReconFile}
          onValidate={validateSelectedBatch}
          onRunBatch={runSelectedBatch}
          onNavigate={setActive}
          loading={loading}
        />
      );
    if (active === 'dataprep')
      return <DataPrep preview={preview} predictions={predictions} />;
    if (active === 'matching')
      return (
        <MatchingStudio
          patterns={patterns}
          rules={noCodeRules}
          onTunePattern={tunePattern}
          onTogglePattern={togglePattern}
          onCreatePattern={createPattern}
        />
      );
    if (active === 'results')
      return (
        <ResultsWorkbench
          results={results}
          summary={summary}
          selected={selected}
          setSelected={setSelected}
          refreshResults={refreshResults}
          onAiTriage={runAiTriage}
          loading={loading}
          triageRunning={triageRunning}
        />
      );
    if (active === 'exceptions')
      return (
        <Exceptions
          exceptions={exceptions}
          workflowRules={workflowRules}
          onResolveClick={setModalItem}
          onWorkflowUpdate={updateWorkflow}
        />
      );
    if (active === 'dashboards')
      return <Dashboards dashboard={dashboard} onExport={exportCsv} />;
    if (active === 'learning')
      return (
        <Learning
          candidates={candidates}
          events={events}
          onSeed={() => safe(api.seedLearning, 'Demo learning signals seeded')}
          onDiscover={() =>
            safe(api.discover, 'Pattern discovery completed')
          }
          onApprove={(id) =>
            safe(() => api.approveCandidate(id), 'Candidate approved as learnt suggestion')
          }
        />
      );
    if (active === 'assistant')
      return (
        <Assistant
          answer={assistantAnswer}
          onAsk={async (q) => setAssistantAnswer(await api.assistant(q))}
        />
      );
    if (active === 'governance')
      return (
        <Governance
          events={events}
          workspace={workspace}
          onSnapshot={() => safe(api.createSnapshot, 'Snapshot created')}
        />
      );
    if (active === 'auto-pattern') return <AutoPatternRecon />;
    return null;
  }, [
    active,
    workspace,
    summary,
    results,
    exceptions,
    patterns,
    candidates,
    events,
    batches,
    submissions,
    selectedBatchId,
    quality,
    batchRunResult,
    preview,
    predictions,
    noCodeRules,
    workflowRules,
    dashboard,
    selected,
    assistantAnswer,
    loading,
    triageRunning,
  ]);

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
          {tabs.map(([key, label]) => (
            <button
              key={key}
              className={active === key ? 'active' : ''}
              onClick={() => setActive(key)}
            >
              {label}
            </button>
          ))}
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
            <span>
              Real-time reconciliation · exception automation · learning
            </span>
          </div>
          <div className="topbar-actions">
            {loading && <span className="loading">Working…</span>}
            <Tag tone="success">FastAPI 8090</Tag>
            <Tag tone="info">React 8181</Tag>
          </div>
        </header>
        {screen}
      </main>
      {modalItem && (
        <ManualResolveModal
          exceptionItem={modalItem}
          onClose={() => setModalItem(null)}
          onSubmit={submitResolution}
        />
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
