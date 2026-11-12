const base = "";

async function req(path, opts = {}) {
  const r = await fetch(base + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail || `${r.status} ${r.statusText}`);
  }
  return r.json();
}

export const api = {
  getConfig: () => req("/api/config"),
  putConfig: (cfg) => req("/api/config", { method: "PUT", body: JSON.stringify(cfg) }),
  getRules: () => req("/api/rules"),
  putRule: (field, rule) => req(`/api/rules/${field}`, { method: "PUT", body: JSON.stringify(rule) }),
  getSources: () => req("/api/sources"),
  getSourceRecords: () => req("/api/source-records"),
  getImpact: (recordId) => req(`/api/source-records/${recordId}/impact`),
  createRun: () => req("/api/runs", { method: "POST" }),
  getRuns: () => req("/api/runs"),
  getRun: (id) => req(`/api/runs/${id}`),
  decide: (runId, d) => req(`/api/runs/${runId}/decide`, { method: "POST", body: JSON.stringify(d) }),
  publish: (runId) => req(`/api/runs/${runId}/publish`, { method: "POST" }),
  getPublications: () => req("/api/publications"),
  getPublication: (v) => req(`/api/publications/${v}`),
  reset: () => req("/api/reset", { method: "POST" }),
};
