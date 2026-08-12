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