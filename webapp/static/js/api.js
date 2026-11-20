// api.js -- thin fetch wrapper shared by every page. Every mutating call
// returns the full updated session so callers just re-render from the
// response (no separate refetch step, no websockets).

const Api = (() => {
  async function request(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    let data = null;
    try { data = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) {
      const err = new Error((data && data.error) || `Request failed: ${res.status}`);
      err.status = res.status;
      err.candidates = data && data.candidates;
      throw err;
    }
    return data;
  }

  const get = (path) => request("GET", path);
  const post = (path, body) => request("POST", path, body || {});
  const del = (path) => request("DELETE", path);

  return {
    searchTeams: (q) => get(`/api/teams/search?q=${encodeURIComponent(q)}`),
    listHeroes: () => get("/api/heroes"),

    listMatches: () => get("/api/matches"),
    createMatch: (teamAQuery, teamBQuery, firstPickTeam) => post("/api/matches", { team_a_query: teamAQuery, team_b_query: teamBQuery, first_pick_team: firstPickTeam }),
    getMatch: (id) => get(`/api/matches/${id}`),
    deleteMatch: (id) => del(`/api/matches/${id}`),
    getDashboard: (id) => get(`/api/matches/${id}/dashboard`),

    ban: (id, team, heroQuery) => post(`/api/matches/${id}/bans`, { team, hero_query: heroQuery }),
    pick: (id, team, heroQuery) => post(`/api/matches/${id}/picks`, { team, hero_query: heroQuery }),
    undoDraft: (id) => post(`/api/matches/${id}/draft/undo`),
    finalizeDraft: (id) => post(`/api/matches/${id}/draft/finalize`),

    getAssignment: (id) => get(`/api/matches/${id}/assignment`),
    assign: (id, team, heroId, accountId) => post(`/api/matches/${id}/assignments`, { team, hero_id: heroId, account_id: accountId }),
    finalizeAssignment: (id) => post(`/api/matches/${id}/assignment/finalize`),

    startLive: (id, radiantTeam) => post(`/api/matches/${id}/live/start`, { radiant_team: radiantTeam }),
    markMatchStarting: (id) => post(`/api/matches/${id}/live/starting`),
    pauseMatch: (id) => post(`/api/matches/${id}/live/pause`),
    resumeMatch: (id) => post(`/api/matches/${id}/live/resume`),
    liveEvent: (id, event) => post(`/api/matches/${id}/live/events`, event),
    undoLiveEvent: (id) => post(`/api/matches/${id}/live/events/undo`),
    setGold: (id, goldLead) => post(`/api/matches/${id}/live/gold`, { gold_lead: goldLead }),
    setNudge: (id, nudgePp) => post(`/api/matches/${id}/live/nudge`, { manual_nudge_pp: nudgePp }),
    toggleBuyback: (id, heroId) => post(`/api/matches/${id}/live/buyback`, { hero_id: heroId }),
    setTimeCorrection: (id, seconds) => post(`/api/matches/${id}/live/time`, { seconds }),
    endMatch: (id, team) => post(`/api/matches/${id}/live/ancient`, { team }),

    refreshSystem: () => post("/api/system/refresh"),
  };
})();

function qsParam(name) {
  return new URLSearchParams(window.location.search).get(name);
}

function fmtPct(p) {
  return `${(p * 100).toFixed(1)}%`;
}

function showError(containerEl, err) {
  containerEl.innerHTML = "";
  const div = document.createElement("div");
  div.className = "error-banner";
  div.textContent = err.message + (err.candidates ? ` (${err.candidates.join(", ")})` : "");
  containerEl.appendChild(div);
}
