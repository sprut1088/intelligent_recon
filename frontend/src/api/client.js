const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function mapCase(row) {
  const suggestions = row.suggestions || [];
  return {
    ...row,
    result_id: row.case_id,
    camt_id: row.camt_id || row.match_key,
    suggested_action: suggestions[0]?.action || row.explanation || '-',
  };
}

function mapCaseList(payload) {
  return { ...payload, items: (payload.items || []).map(mapCase) };
}

function mapSummary(payload) {
  const kpi = payload.kpi || {};
  const total = payload.total_cases || 0;
  const autoClosed = kpi.auto_matched_count || 0;
  return {
    total_results: total,
    auto_closed: autoClosed,
    exceptions: kpi.exception_count || 0,
    match_rate: total ? Math.round((autoClosed / total) * 10000) / 100 : 0,
    average_confidence: Math.round((kpi.average_confidence || 0) * 100) / 100,
    internal_total: kpi.internal_amount || 0,
    bank_total: kpi.bank_amount || 0,
    variance_total: (kpi.internal_amount || 0) - (kpi.bank_amount || 0),
    manual_resolutions: payload.manual_resolution_count || 0,
    learning_candidates: payload.learning_candidate_count || 0,
    statuses: payload.by_status || [],
    reasons: payload.by_reason || [],
    raw: payload,
  };
}

export const api = {
  health: () => request('/health'),
  counts: async () => {
    const s = await request('/api/reconcile/summary');
    return { psr_transactions: s.psr_count || 0, camt_transactions: s.camt_count || 0, reconciliation_results: s.total_cases || 0 };
  },
  loadSampleData: () => request('/api/load-sample', { method: 'POST', body: JSON.stringify({ reset: true }) }),
  runRecon: () => request('/api/reconcile/run', { method: 'POST' }),
  summary: async () => mapSummary(await request('/api/reconcile/summary')),
  results: async ({ limit = 100, offset = 0, exceptionOnly = false, search = '' } = {}) => {
    const qs = new URLSearchParams({ limit, offset, exception_only: exceptionOnly });
    if (search) qs.set('search', search);
    return mapCaseList(await request(`/api/reconcile/cases?${qs.toString()}`));
  },
  exceptions: async ({ limit = 100, offset = 0 } = {}) =>
    mapCaseList(await request(`/api/reconcile/cases?exception_only=true&limit=${limit}&offset=${offset}`)),
  resolveException: (caseId, payload) => request(`/api/reconcile/cases/${caseId}/resolve`, {
    method: 'POST',
    body: JSON.stringify({
      resolution_type: payload.final_resolution_type || 'MATCHED_MANUAL',
      reason_code: payload.reason_code || 'REMITTANCE_FORMAT_MISMATCH',
      selected_bank_ids: payload.bank_transaction_ids || [],
      selected_psr_ids: payload.psr_transaction_ids || [],
      fields_used: payload.fields_used || [],
      fields_ignored: payload.fields_ignored || [],
      accepted_variance: payload.accepted_variance ?? null,
      comment: payload.user_comment || '',
      learning_eligible: payload.learning_eligible ?? true,
    }),
  }),
  patterns: async () => (await request('/api/patterns')).items || [],
  candidates: async () => (await request('/api/pattern-candidates')).items || [],
  discover: () => request('/api/learning/run', { method: 'POST' }),
  approveCandidate: (id) => request(`/api/pattern-candidates/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved_by: 'recon_lead', execution_mode: 'SUGGESTION', confidence_threshold: 0.9 }),
  }),
  seedLearning: () => request('/api/learning/demo-signals', { method: 'POST' }),
  events: async () => (await request('/api/events?limit=50')).items || [],
  assistant: (question) => request(`/api/assistant/query?question=${encodeURIComponent(question)}`),
};
