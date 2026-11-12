let queue = Promise.resolve();

function request(method, path, body) {
  const run = () =>
    fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    }).then((res) => {
      if (!res.ok) throw new Error(`${method} ${path}: ${res.status}`);
      return res.json();
    });
  // Requests run in order so a rearrange always sees the latest save.
  queue = queue.then(run, run);
  return queue;
}

export const api = {
  week: (id) => request("GET", `/api/week/${id}`),
  save: (id, blocks) => request("PUT", `/api/week/${id}`, { blocks }),
  arrange: (id) => request("POST", `/api/arrange/${id}`),
  // Not queued: Claude can take a minute and the dialog blocks editing meanwhile.
  claude: (id, wish) =>
    fetch(`/api/claude/${id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ wish }) })
      .then((res) => res.json().then((data) => { if (!res.ok) throw new Error(data.error); return data; })),
  settings: () => request("GET", "/api/settings"),
  saveSettings: (data) => request("PUT", "/api/settings", data),
  resetWeek: (id) => request("POST", `/api/reset/${id}`),
  heartbeat: () => fetch("/api/heartbeat").then((res) => res.json()),
};
