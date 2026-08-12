const BASE_URL = "";

export async function getRecentPOs(limit = 50) {
  const res = await fetch(`${BASE_URL}/recent?limit=${limit}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function searchPOs(q, mode = "or") {
  const res = await fetch(`${BASE_URL}/search?q=${encodeURIComponent(q)}&mode=${mode}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getPartSummary(partNum) {
  const res = await fetch(`${BASE_URL}/summary/${encodeURIComponent(partNum)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getPartHistory(partNum) {
  const res = await fetch(`${BASE_URL}/parts/${encodeURIComponent(partNum)}`);
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
  const res = await fetch(`${BASE_URL}/bulk-lookup`, {
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
  const res = await fetch(`${BASE_URL}/inventory`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function searchInventory(q) {
  const res = await fetch(`${BASE_URL}/inventory/search?q=${encodeURIComponent(q)}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getInventoryByPart(partNum) {
  const res = await fetch(`${BASE_URL}/inventory/parts/${encodeURIComponent(partNum)}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getInventoryWarehouses() {
  const res = await fetch(`${BASE_URL}/inventory/warehouses`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getInventoryByWarehouse(whCode) {
  const res = await fetch(`${BASE_URL}/inventory/warehouses/${encodeURIComponent(whCode)}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}