// Support Portal UI bundle (staging)
// Note: This is a demo asset used for benchmark labs.

const API_BASE = "/api/v1";
const ENDPOINTS = {
  status: `${API_BASE}/status`,
  tickets: `${API_BASE}/tickets`,
};

async function ping() {
  const r = await fetch(ENDPOINTS.status, { credentials: "include" });
  return await r.json();
}

// eslint-disable-next-line no-unused-vars
async function loadTickets() {
  const r = await fetch(ENDPOINTS.tickets, { credentials: "include" });
  return await r.json();
}

