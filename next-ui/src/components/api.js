const BASE_URL = "";

// Set from main.jsx once Clerk loads — returns the current session token.
let tokenGetter = null;
export function setAuthTokenGetter(fn) {
  tokenGetter = fn;
}

async function authFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (tokenGetter) {
    const token = await tokenGetter();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  return fetch(`${BASE_URL}${path}`, { ...options, headers });
}

async function readJson(res, fallbackMessage) {
  if (res.ok) return res.json();
  let body = null;
  try {
    body = await res.json();
  } catch {
    // The API normally returns JSON, but keep a safe fallback for proxy errors.
  }
  const message = body?.details || body?.error || body?.detail || fallbackMessage;
  const error = new Error(message);
  error.status = res.status;
  error.payload = body;
  throw error;
}

export async function getMe() {
  const res = await authFetch(`/me`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listUsers() {
  const res = await authFetch(`/users`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listUserAccessHistory(limit = 100) {
  const res = await authFetch(`/users/access-history?limit=${limit}`);
  return readJson(res, "Could not load access history");
}

export async function getRoleAccess() {
  return readJson(await authFetch(`/roles`, { cache: "no-store" }), "Could not load role access metadata");
}

export async function createUser(user) {
  const res = await authFetch(`/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(user),
  });
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail; } catch { detail = await res.text(); }
    throw new Error(detail || "Failed to add user");
  }
  return res.json();
}

export async function updateUser(id, patch) {
  const res = await authFetch(`/users/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail; } catch { detail = await res.text(); }
    throw new Error(detail || "Failed to update user");
  }
  return res.json();
}

export async function getRecentPOs(limit = 50) {
  const res = await authFetch(`/recent?limit=${limit}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function searchPOs(q, mode = "or") {
  const res = await authFetch(`/search?q=${encodeURIComponent(q)}&mode=${mode}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getPartSummary(partNum) {
  const res = await authFetch(`/summary/${encodeURIComponent(partNum)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getPartHistory(partNum) {
  const res = await authFetch(`/parts/${encodeURIComponent(partNum)}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getBulkPartSummaries(partNumbers) {
  const promises = partNumbers.map(async (partNum) => {
    try {
      const summary = await getPartSummary(partNum);
      return { partNum, summary, error: null };
    } catch (error) {
      return { partNum, summary: null, error: error.message || "Lookup failed" };
    }
  });

  return Promise.all(promises);
}

export async function bulkLookupParts(partNumbers) {
  const res = await authFetch(`/bulk-lookup`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ part_numbers: partNumbers }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAllInventory() {
  const res = await authFetch(`/inventory`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function searchInventory(q) {
  const res = await authFetch(`/inventory/search?q=${encodeURIComponent(q)}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getInventoryByPart(partNum) {
  const res = await authFetch(`/inventory/parts/${encodeURIComponent(partNum)}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getInventoryWarehouses() {
  const res = await authFetch(`/inventory/warehouses`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getInventoryByWarehouse(whCode) {
  const res = await authFetch(`/inventory/warehouses/${encodeURIComponent(whCode)}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getKpis(asOf) {
  const query = asOf ? `?asOf=${encodeURIComponent(asOf)}` : "";
  return readJson(await authFetch(`/api/kpis${query}`, { cache: "no-store" }), "Could not load published KPI data");
}

export async function getKpiTrends(asOf) {
  const query = asOf ? `?asOf=${encodeURIComponent(asOf)}` : "";
  return readJson(await authFetch(`/api/kpis/trends${query}`, { cache: "no-store" }), "Could not load KPI trends");
}

export async function getKpiDetail(metricId, period) {
  const params = new URLSearchParams(period);
  return readJson(
    await authFetch(`/api/kpis/${encodeURIComponent(metricId)}/detail?${params}`, { cache: "no-store" }),
    "Could not load published KPI detail",
  );
}

export async function getKpiHealth() {
  return readJson(await authFetch("/api/health", { cache: "no-store" }), "Could not check KPI freshness");
}

const DATALAKE_PATHS = Object.freeze({
  health: "/api/datalake/health",
  freshness: "/api/datalake/freshness",
  catalog: "/api/datalake/catalog",
  tables: "/api/datalake/tables",
  queries: "/api/datalake/queries",
  shipping_logs: "/api/datalake/queries/shipping_logs",
  wow: "/api/datalake/wow",
  mom: "/api/datalake/mom",
});

export async function getDataLakeReport(report, params = null) {
  const path = DATALAKE_PATHS[report];
  if (!path) {
    throw new Error("Unknown DataLake report");
  }
  const query = params ? `?${new URLSearchParams(params)}` : "";
  return readJson(
    await authFetch(`${path}${query}`, { cache: "no-store" }),
    "Could not load DataLake report",
  );
}
