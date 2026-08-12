const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8090';

async function request(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    headers: isFormData ? (options.headers || {}) : { 'Content-Type': 'application/json', ...(options.headers || {}) },
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
    by_rule: payload.by_rule || [],
    ai_verified_count: (payload.kpi || {}).ai_verified_count || 0,
    raw: payload,
  };
}

export const api = {
  health: () => request('/health'),

  workspaceOverview: () => request('/api/workspace/overview'),
  workspaceSubmissions: () => request('/api/workspace/submissions'),
  dataPreview: () => request('/api/workspace/data-preview?limit=12'),
  fieldPredictions: () => request('/api/workspace/match-field-predictions'),
  noCodeRules: () => request('/api/workspace/no-code-rules'),
  workflowRules: () => request('/api/workspace/workflow-rules'),
  dashboardModel: () => request('/api/workspace/dashboard'),
  createSnapshot: () => request('/api/workspace/snapshot', { method: 'POST' }),
  exportResultsUrl: () => `${API_BASE}/api/workspace/export/reconciliation-results`,
  exportCasesUrl: ({ search = '', status = '', exceptionOnly = false, filename = 'recon_report' } = {}) => {
    const qs = new URLSearchParams({ exception_only: exceptionOnly, filename });
    if (search) qs.set('search', search);
    if (status) qs.set('status', status);
    return `${API_BASE}/api/reconcile/cases/export?${qs.toString()}`;
  },
  counts: async () => {
    const s = await request('/api/reconcile/summary');
    return { psr_transactions: s.psr_count || 0, camt_transactions: s.camt_count || 0, reconciliation_results: s.total_cases || 0 };
  },

  batches: async () => request('/api/files/batches?limit=50'),
  uploadFile: (file, fileType, batchId = '', batchName = '') => {
    const form = new FormData();
    form.append('file', file);
    form.append('file_type', fileType);
    if (batchId) form.append('batch_id', batchId);
    if (batchName) form.append('batch_name', batchName);
    return request('/api/files/upload', { method: 'POST', body: form });
  },
  generateMapping: (camtFile, otherFile, maxExamples = 10) => {
    const form = new FormData();
    form.append('camt_file', camtFile);
    form.append('other_file', otherFile);
    form.append('max_examples', String(maxExamples));
    return request('/api/files/generate-mapping', { method: 'POST', body: form });
  },
  patternSuggestions: (camtFile, otherFile, maxExamples = 8) => {
    const form = new FormData();
    form.append('camt_file', camtFile);
    form.append('other_file', otherFile);
    form.append('max_examples', String(maxExamples));
    return request('/api/files/pattern-suggestions', { method: 'POST', body: form });
  },
  generateReconciliationPatterns: (camtFile, otherFile, providedRegexMap = null) => {
    const form = new FormData();
    form.append('camt_file', camtFile);
    form.append('other_file', otherFile);
    if (providedRegexMap != null) form.append('provided_regex_map', JSON.stringify(providedRegexMap));
    return request('/api/files/reconcile-patterns', { method: 'POST', body: form });
  },
  validateBatch: (batchId) => request(`/api/data-quality/batches/${batchId}/validate`, { method: 'POST' }),
  quality: (batchId) => request(`/api/data-quality/batches/${batchId}`),
  runBatch: (batchId, amountDivisor = null, patternGroup = null) => request(`/api/files/batches/${batchId}/run`, { method: 'POST', body: JSON.stringify({ reset: true, ...(amountDivisor != null ? { amount_divisor: amountDivisor } : {}), ...(patternGroup ? { pattern_group: patternGroup } : {}) }) }),
  loadSampleData: (amountDivisor = null) => request('/api/load-sample', { method: 'POST', body: JSON.stringify({ reset: true, ...(amountDivisor != null ? { amount_divisor: amountDivisor } : {}) }) }),
  runRecon: () => request('/api/reconcile/run', { method: 'POST' }),
  aiTriage: () => request('/api/reconcile/ai-triage', { method: 'POST' }),
  aiVerify: (caseIds = null) => request('/api/reconcile/ai-verify', {
    method: 'POST',
    body: JSON.stringify(caseIds ? { case_ids: caseIds } : {}),
  }),
  aiPass: () => request('/api/reconcile/ai-pass', { method: 'POST' }),
  summary: async () => mapSummary(await request('/api/reconcile/summary')),
  results: async ({ limit = 100, offset = 0, exceptionOnly = false, search = '', status = '' } = {}) => {
    const qs = new URLSearchParams({ limit, offset, exception_only: exceptionOnly });
    if (search) qs.set('search', search);
    if (status) qs.set('status', status);
    return mapCaseList(await request(`/api/reconcile/cases?${qs.toString()}`));
  },
  caseDetail: async (caseId) => {
    const data = await request(`/api/reconcile/cases/${caseId}`);
    return { ...data, case: mapCase(data.case || {}) };
  },
  similarCases: (caseId) => request(`/api/reconcile/cases/${caseId}/similar?limit=5`),
  exceptions: async ({ limit = 100, offset = 0 } = {}) =>
    mapCaseList(await request(`/api/exceptions/workflow?limit=${limit}&offset=${offset}`)),
  updateWorkflow: (caseId, payload) => request(`/api/exceptions/${caseId}/workflow`, { method: 'PATCH', body: JSON.stringify(payload) }),
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
  overrideResolve: (caseId, overrideReason, overrideNote) => request(`/api/reconcile/cases/${caseId}/resolve`, {
    method: 'POST',
    body: JSON.stringify({
      resolution_type: 'OVERRIDE_AI',
      reason_code: overrideReason,
      override_reason: overrideReason,
      override_note: overrideNote || '',
      learning_eligible: false,
    }),
  }),
  noMatchResolve: (caseId, resolutionType, reasonCode) => request(`/api/reconcile/cases/${caseId}/resolve`, {
    method: 'POST',
    body: JSON.stringify({
      resolution_type: resolutionType,
      reason_code: reasonCode,
      selected_psr_ids: [],
      selected_bank_ids: [],
      fields_used: [],
      fields_ignored: [],
      learning_eligible: false,
    }),
  }),
  patterns: async () => (await request('/api/patterns')).items || [],
  createPattern: (payload) => request('/api/patterns', { method: 'POST', body: JSON.stringify(payload) }),
  createBulkPatterns: (groupName, patterns) =>
    request('/api/patterns/bulk', { method: 'POST', body: JSON.stringify({ group_name: groupName, patterns }) }),
  comparePatterns: (identifiedPatterns, compareGroup) =>
    request('/api/patterns/compare', { method: 'POST', body: JSON.stringify({ identified_patterns: identifiedPatterns, compare_group: compareGroup }) }),
  deletePattern: (patternId) => request(`/api/patterns/${patternId}`, { method: 'DELETE' }),
  deletePatternGroup: (groupName) => request(`/api/patterns/groups/${encodeURIComponent(groupName)}`, { method: 'DELETE' }),

  updatePattern: (patternId, payload) => request(`/api/patterns/${patternId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  activatePattern: (patternId) => request(`/api/patterns/${patternId}/activate`, { method: 'POST' }),
  deactivatePattern: (patternId) => request(`/api/patterns/${patternId}/deactivate`, { method: 'POST' }),
  candidates: async () => (await request('/api/pattern-candidates')).items || [],
  discover: () => request('/api/learning/run', { method: 'POST' }),
  approveCandidate: (id) => request(`/api/pattern-candidates/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved_by: 'recon_lead', execution_mode: 'SUGGESTION', confidence_threshold: 0.9 }),
  }),
  seedLearning: () => request('/api/learning/demo-signals', { method: 'POST' }),
  events: async () => (await request('/api/events?limit=50')).items || [],
  assistant: (question) => request(`/api/assistant/query?question=${encodeURIComponent(question)}`),
  assistantBriefing: () => request('/api/assistant/briefing'),
};
