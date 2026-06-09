import { useEffect, useMemo, useState } from 'react';
import { api } from './api/client';

const tabs = [
  ['command', 'Command Centre'],
  ['workbench', 'Recon Workbench'],
  ['exceptions', 'Exception Queue'],
  ['learning', 'Pattern Learning'],
  ['patterns', 'Pattern Registry'],
  ['assistant', 'Recon Assistant'],
  ['audit', 'Audit Trail'],
];

const money = (value) =>
  value === null || value === undefined
    ? '-'
    : new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 }).format(value);

function Card({ label, value, hint }) {
  return (
    <div className="card">
      <div className="card-label">{label}</div>
      <div className="card-value">{value}</div>
      <div className="card-hint">{hint}</div>
    </div>
  );
}

function StatusPills({ summary }) {
  const total = summary?.total_results || 1;
  return (
    <div className="status-stack">
      {(summary?.statuses || []).map((s) => (
        <div key={s.reconciliation_status} className="status-row">
          <div className="status-name">{s.reconciliation_status}</div>
          <div className="status-bar-wrap">
            <div className="status-bar" style={{ width: `${Math.max(4, (s.count / total) * 100)}%` }} />
          </div>
          <div className="status-count">{s.count}</div>
        </div>
      ))}
    </div>
  );
}

function ResultTable({ rows, onSelect, compact = false }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>PSR</th>
            <th>CAMT</th>
            <th>Reference</th>
            <th>Internal</th>
            <th>Bank</th>
            <th>Variance</th>
            <th>Status</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.result_id} onClick={() => onSelect?.(r)} className="clickable">
              <td>{r.result_id}</td>
              <td>{r.psr_id || '-'}</td>
              <td>{r.camt_id || '-'}</td>
              <td>{r.reference || '-'}</td>
              <td>{money(r.internal_amount)}</td>
              <td>{money(r.bank_amount)}</td>
              <td className={Number(r.variance) === 0 ? 'ok' : 'warn'}>{money(r.variance)}</td>
              <td><span className={`pill ${r.exception_flag === 'Y' ? 'pill-warn' : 'pill-ok'}`}>{r.reconciliation_status}</span></td>
              <td>{r.match_confidence}%</td>
            </tr>
          ))}
          {!rows.length && (
            <tr><td colSpan="9" className="empty">No records to display</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function DetailPanel({ selected, onClose, onResolve }) {
  if (!selected) return null;
  return (
    <aside className="detail-panel">
      <button className="ghost close" onClick={onClose}>Close</button>
      <h2>{selected.psr_id || selected.camt_id}</h2>
      <p className="muted">{selected.explanation}</p>
      <div className="detail-grid">
        <span>Status</span><strong>{selected.reconciliation_status}</strong>
        <span>Rule applied</span><strong>{selected.rule_applied}</strong>
        <span>Reason</span><strong>{selected.reason_code}</strong>
        <span>Suggested action</span><strong>{selected.suggested_action}</strong>
        <span>Invoice</span><strong>{selected.invoice || '-'}</strong>
        <span>Counterparty</span><strong>{selected.counterparty || '-'}</strong>
      </div>
      {selected.exception_flag === 'Y' && (
        <button className="primary full" onClick={() => onResolve(selected)}>Resolve and Capture Learning</button>
      )}
    </aside>
  );
}

function CommandCentre({ summary, counts, onLoad, onRun, loading }) {
  return (
    <section className="screen">
      <div className="hero">
        <div>
          <p className="eyebrow">Real-time reconciliation prototype</p>
          <h1>Intelligent Recon Engine</h1>
          <p>Automated bank-feed ingestion, rule-based reconciliation, exception routing, and analyst-driven pattern learning.</p>
        </div>
        <div className="hero-actions">
          <button className="secondary" onClick={onLoad} disabled={loading}>Load sample PSR/CAMT</button>
          <button className="primary" onClick={onRun} disabled={loading}>Run reconciliation</button>
        </div>
      </div>
      <div className="cards">
        <Card label="PSR records" value={counts.psr_transactions || 0} hint="Internal payment settlement rows" />
        <Card label="CAMT entries" value={counts.camt_transactions || 0} hint="Bank statement entries" />
        <Card label="Auto-closed" value={summary.auto_closed || 0} hint={`${summary.match_rate || 0}% match rate`} />
        <Card label="Exceptions" value={summary.exceptions || 0} hint="Manual, ledger, and in-transit queues" />
        <Card label="Learning signals" value={summary.manual_resolutions || 0} hint="Human-in-loop resolutions captured" />
        <Card label="Variance" value={money(summary.variance_total || 0)} hint="Internal less bank total" />
      </div>
      <div className="two-col">
        <div className="panel">
          <h3>Reconciliation Status</h3>
          <StatusPills summary={summary} />
        </div>
        <div className="panel">
          <h3>Operating Model</h3>
          <div className="flow">
            <span>PSR/CAMT ingestion</span><b>→</b><span>Data cleansing</span><b>→</b><span>Pattern engine</span><b>→</b><span>Exception routing</span><b>→</b><span>Learning loop</span>
          </div>
          <p className="muted">The prototype starts with seven seed patterns and promotes repeated manual decisions into candidate learnt patterns.</p>
        </div>
      </div>
    </section>
  );
}

function Workbench({ results, selected, setSelected, refreshResults }) {
  const [search, setSearch] = useState('');
  const runSearch = async () => refreshResults({ search });
  return (
    <section className="screen">
      <div className="screen-head">
        <div>
          <h1>Transaction Reconciliation Workbench</h1>
          <p>Review match evidence, rule applied, variance, confidence, and suggested action.</p>
        </div>
        <div className="search-box">
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search PSR, CAMT, invoice, party" />
          <button className="secondary" onClick={runSearch}>Search</button>
        </div>
      </div>
      <ResultTable rows={results.items || []} onSelect={setSelected} />
      <DetailPanel selected={selected} onClose={() => setSelected(null)} onResolve={setSelected} />
    </section>
  );
}

function ManualResolveModal({ exceptionItem, onClose, onSubmit }) {
  const [reason, setReason] = useState('REMITTANCE_FORMAT_MISMATCH');
  const [comment, setComment] = useState('Bank remittance uses shortened invoice or alias; analyst confirmed candidate.');
  if (!exceptionItem) return null;
  const fields = ['invoice_suffix', 'amount', 'counterparty'];
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h2>Resolve exception and capture learning</h2>
        <p className="muted">Case for {exceptionItem.psr_id || exceptionItem.camt_id}. This stores a manual-resolution label that the learning service can mine later.</p>
        <label>Resolution reason</label>
        <select value={reason} onChange={(e) => setReason(e.target.value)}>
          <option value="REMITTANCE_FORMAT_MISMATCH">Remittance format mismatch</option>
          <option value="COUNTERPARTY_ALIAS">Counterparty alias issue</option>
          <option value="BATCH_SETTLEMENT">Batch settlement grouping</option>
          <option value="DELAYED_BANK_POSTING">Delayed bank posting</option>
          <option value="MINOR_AMOUNT_VARIANCE">Minor amount variance</option>
        </select>
        <label>Fields used by analyst</label>
        <div className="chip-row">{fields.map((f) => <span key={f} className="chip active">{f}</span>)}</div>
        <label>Comment</label>
        <textarea value={comment} onChange={(e) => setComment(e.target.value)} />
        <div className="modal-actions">
          <button className="ghost" onClick={onClose}>Cancel</button>
          <button className="primary" onClick={() => onSubmit(exceptionItem, reason, comment)}>Confirm resolution</button>
        </div>
      </div>
    </div>
  );
}

function Exceptions({ exceptions, onResolveClick }) {
  return (
    <section className="screen">
      <div className="screen-head">
        <div>
          <h1>Exception Management Queue</h1>
          <p>Prioritise no-match, amount variance, ledger allocation, and in-transit scenarios.</p>
        </div>
      </div>
      <ResultTable rows={exceptions.items || []} onSelect={onResolveClick} />
    </section>
  );
}

function Learning({ candidates, events, onSeed, onDiscover, onApprove }) {
  return (
    <section className="screen">
      <div className="screen-head">
        <div>
          <h1>Human-in-the-Loop Pattern Learning</h1>
          <p>Manual exception decisions are recorded as labelled training data and promoted through governance.</p>
        </div>
        <div className="hero-actions">
          <button className="secondary" onClick={onSeed}>Seed demo learning</button>
          <button className="primary" onClick={onDiscover}>Discover patterns</button>
        </div>
      </div>
      <div className="two-col">
        <div className="panel">
          <h3>Candidate Pattern Inbox</h3>
          <div className="candidate-list">
            {candidates.map((c) => (
              <div className="candidate" key={c.candidate_pattern_id}>
                <div>
                  <strong>{c.pattern_name}</strong>
                  <p>{c.observed_case_count} observed cases · {c.backtest_precision}% prototype precision · {c.status}</p>
                </div>
                {c.status !== 'APPROVED' && <button className="secondary" onClick={() => onApprove(c.candidate_pattern_id)}>Approve as suggestion</button>}
              </div>
            ))}
            {!candidates.length && <p className="muted">No learnt pattern candidates yet. Resolve exceptions or seed demo learning.</p>}
          </div>
        </div>
        <div className="panel">
          <h3>Latest Learning Events</h3>
          <div className="event-list">
            {events.slice(0, 8).map((e) => (
              <div className="event" key={e.event_id}>
                <strong>{e.event_type}</strong>
                <span>{e.case_id} · {e.user_id}</span>
              </div>
            ))}
            {!events.length && <p className="muted">No analyst actions captured yet.</p>}
          </div>
        </div>
      </div>
      <div className="panel">
        <h3>Learning Promotion Path</h3>
        <div className="timeline">
          <span>Manual resolution</span><span>Feature extraction</span><span>Candidate pattern</span><span>Back-test</span><span>Lead approval</span><span>Suggest only</span><span>Future auto-close</span>
        </div>
      </div>
    </section>
  );
}

function PatternRegistry({ patterns }) {
  return (
    <section className="screen">
      <h1>Pattern Registry</h1>
      <p>Seed rules and approved learnt patterns used by the matching engine.</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Status</th><th>Mode</th><th>Threshold</th></tr></thead>
          <tbody>
            {patterns.map((p) => (
              <tr key={p.pattern_id}>
                <td>{p.pattern_id}</td><td>{p.pattern_name}</td><td>{p.pattern_type}</td><td>{p.status}</td><td>{p.execution_mode}</td><td>{p.confidence_threshold}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Assistant({ onAsk, answer }) {
  const [question, setQuestion] = useState('How many exceptions do we have?');
  return (
    <section className="screen">
      <h1>Interactive Reconciliation Assistant</h1>
      <p>Ask operational questions against reconciliation summary and learning state.</p>
      <div className="assistant-box">
        <input value={question} onChange={(e) => setQuestion(e.target.value)} />
        <button className="primary" onClick={() => onAsk(question)}>Ask</button>
      </div>
      {answer && <div className="answer"><strong>Assistant:</strong> {answer.answer}</div>}
      <div className="suggestions">
        {['Show auto-close match rate', 'What is the total variance?', 'How many learning patterns exist?'].map((q) => (
          <button className="ghost" key={q} onClick={() => { setQuestion(q); onAsk(q); }}>{q}</button>
        ))}
      </div>
    </section>
  );
}

function Audit({ events }) {
  return (
    <section className="screen">
      <h1>Audit Trail</h1>
      <p>Immutable event stream for user decisions, overrides, and learning signals.</p>
      <div className="event-list panel">
        {events.map((e) => (
          <div className="event" key={e.event_id}>
            <strong>{e.event_type}</strong>
            <span>{e.event_timestamp} · {e.case_id} · {e.user_id}</span>
            <code>{JSON.stringify(e.event_payload)}</code>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function App() {
  const [active, setActive] = useState('command');
  const [summary, setSummary] = useState({ statuses: [], reasons: [] });
  const [counts, setCounts] = useState({});
  const [results, setResults] = useState({ items: [] });
  const [exceptions, setExceptions] = useState({ items: [] });
  const [patterns, setPatterns] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [events, setEvents] = useState([]);
  const [selected, setSelected] = useState(null);
  const [modalItem, setModalItem] = useState(null);
  const [assistantAnswer, setAssistantAnswer] = useState(null);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState('');

  const refresh = async () => {
    const [summaryData, countsData, resultsData, exceptionsData, patternsData, candidatesData, eventsData] = await Promise.all([
      api.summary(), api.counts(), api.results({ limit: 100 }), api.exceptions({ limit: 100 }), api.patterns(), api.candidates(), api.events(),
    ]);
    setSummary(summaryData);
    setCounts(countsData);
    setResults(resultsData);
    setExceptions(exceptionsData);
    setPatterns(patternsData);
    setCandidates(candidatesData);
    setEvents(eventsData);
  };

  const safe = async (fn, message) => {
    try {
      setLoading(true);
      await fn();
      await refresh();
      setToast(message);
      setTimeout(() => setToast(''), 3000);
    } catch (err) {
      setToast(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh().catch(() => {}); }, []);

  const refreshResults = async ({ search = '' } = {}) => {
    setResults(await api.results({ limit: 100, search }));
  };

  const submitResolution = async (item, reason, comment) => {
    await safe(() => api.resolveException(item.result_id, {
      user_id: 'analyst_01',
      final_resolution_type: 'MATCHED_MANUAL',
      reason_code: reason,
      psr_transaction_ids: item.psr_id ? [item.psr_id] : [],
      bank_transaction_ids: item.camt_id ? [item.camt_id] : [],
      fields_used: ['invoice_suffix', 'amount', 'counterparty'],
      fields_ignored: ['exact_invoice_format', 'exact_pmt_ref'],
      user_comment: comment,
      learning_eligible: true,
    }), 'Manual resolution captured as learning signal');
    setModalItem(null);
  };

  const screen = useMemo(() => {
    if (active === 'command') return <CommandCentre summary={summary} counts={counts} onLoad={() => safe(api.loadSampleData, 'Sample PSR/CAMT loaded')} onRun={() => safe(api.runRecon, 'Reconciliation completed')} loading={loading} />;
    if (active === 'workbench') return <Workbench results={results} selected={selected} setSelected={setSelected} refreshResults={refreshResults} />;
    if (active === 'exceptions') return <Exceptions exceptions={exceptions} onResolveClick={setModalItem} />;
    if (active === 'learning') return <Learning candidates={candidates} events={events} onSeed={() => safe(api.seedLearning, 'Demo learning signals seeded')} onDiscover={() => safe(api.discover, 'Pattern discovery completed')} onApprove={(id) => safe(() => api.approveCandidate(id), 'Candidate approved as learnt suggestion')} />;
    if (active === 'patterns') return <PatternRegistry patterns={patterns} />;
    if (active === 'assistant') return <Assistant answer={assistantAnswer} onAsk={async (q) => setAssistantAnswer(await api.assistant(q))} />;
    if (active === 'audit') return <Audit events={events} />;
    return null;
  }, [active, summary, counts, results, exceptions, patterns, candidates, events, selected, assistantAnswer, loading]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span>IRE</span><strong>Intelligent<br/>Recon Engine</strong></div>
        <nav>
          {tabs.map(([key, label]) => <button key={key} className={active === key ? 'active' : ''} onClick={() => setActive(key)}>{label}</button>)}
        </nav>
        <div className="sidebar-foot">Prototype · FastAPI + React</div>
      </aside>
      <main>
        <header className="topbar">
          <div><strong>Cash Account Reconciliation</strong><span>Solution 2 · Real-time recon with learning loop</span></div>
          {loading && <span className="loading">Working…</span>}
        </header>
        {screen}
      </main>
      {modalItem && <ManualResolveModal exceptionItem={modalItem} onClose={() => setModalItem(null)} onSubmit={submitResolution} />}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
