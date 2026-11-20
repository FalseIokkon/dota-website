// match.js -- match.html: one continuous scroll -- dashboard, draft board,
// player assignment, and live tracker, all driven off a single session
// object refetched/updated after every action.

const matchId = qsParam("m");
const errorEl = document.getElementById("error");
let session = null;
let heroNames = null;
let heroNamesById = {};
let assignmentView = null;
let dashboardData = null;
let clockSyncElapsed = null;
let clockSyncClientMs = null;

async function load() {
  [session, heroNames] = await Promise.all([Api.getMatch(matchId), getHeroNames()]);
  heroNamesById = {};
  heroNames.forEach(h => { heroNamesById[h.hero_id] = h.name; });
  window.HERO_NAMES_BY_ID = heroNamesById;

  assignmentView = await Api.getAssignment(matchId);
  dashboardData = await Api.getDashboard(matchId);

  wireStaticControls();
  renderAll(dashboardData);
  setInterval(tickClock, 1000);
}

function renderAll(dashboard) {
  renderHeader();
  if (dashboard) renderDashboard(dashboard);
  renderDraft();
  renderAssign();
  renderLive();
}

async function refresh(newSession) {
  session = newSession;
  assignmentView = await Api.getAssignment(matchId);
  renderAll(null);
}

// ---------------------------------------------------------------------------
// Header: title, clock, buttons, win-prob bar
// ---------------------------------------------------------------------------

const STATUS_LABELS = { pending: "Not Started", live: "Live", paused: "Paused", ended: "Ended" };

function renderHeader() {
  document.getElementById("matchTitle").textContent = `${session.team_a.label} vs ${session.team_b.label}`;

  const st = session.live.status;
  clockSyncElapsed = session.live.elapsed_seconds || 0;
  clockSyncClientMs = Date.now();
  document.getElementById("clockDisplay").textContent = fmtClock(clockSyncElapsed);
  document.getElementById("clockDisplay").classList.toggle("live", st === "live");
  document.getElementById("statusLabel").textContent = STATUS_LABELS[st] || st;

  document.getElementById("startClockBtn").disabled = !(session.phase === "live" && st === "pending");
  document.getElementById("pauseResumeBtn").disabled = !(session.phase === "live" && (st === "live" || st === "paused"));
  document.getElementById("pauseResumeBtn").textContent = st === "paused" ? "Resume" : "Pause";
  document.getElementById("endMatchBtn").disabled = !(session.phase === "live" && st !== "pending" && st !== "ended");

  const p = currentProb(session);
  const pctA = (p * 100).toFixed(0);
  const pctB = (100 - p * 100).toFixed(0);
  document.getElementById("wpRow").innerHTML = `
    <div class="wp-team">
      <div class="wp-swatch" style="background:var(--team-a)">${escapeHtml(teamInitials(session.team_a.label))}</div>
      <div><div class="name">${escapeHtml(session.team_a.label)}</div><div class="label">Team A</div></div>
    </div>
    <div class="wp-bar-track">
      <div class="seg seg-a" style="width:${pctA}%"><span>${pctA}%</span></div>
      <div class="seg seg-b" style="width:${pctB}%"><span>${pctB}%</span></div>
    </div>
    <div class="wp-team right">
      <div><div class="name">${escapeHtml(session.team_b.label)}</div><div class="label">Team B</div></div>
      <div class="wp-swatch" style="background:var(--team-b)">${escapeHtml(teamInitials(session.team_b.label))}</div>
    </div>`;
}

function tickClock() {
  if (!session || session.live.status !== "live") return;
  const elapsed = clockSyncElapsed + (Date.now() - clockSyncClientMs) / 1000;
  document.getElementById("clockDisplay").textContent = fmtClock(elapsed);
}

function wireStaticControls() {
  document.getElementById("startClockBtn").addEventListener("click", () => act(() => Api.markMatchStarting(matchId)));
  document.getElementById("pauseResumeBtn").addEventListener("click", () => {
    const fn = session.live.status === "paused" ? Api.resumeMatch : Api.pauseMatch;
    act(() => fn(matchId));
  });
  document.getElementById("endMatchBtn").addEventListener("click", () => {
    // "End Match" in the header is a shortcut for whichever side is currently losing the model's estimate -- confirm via the same modal as the map's ancient buttons.
    const losingTeam = currentProb(session) >= 0.5 ? "team_b" : "team_a";
    confirmAncient(losingTeam);
  });
  document.getElementById("undoDraftBtn").addEventListener("click", () => act(() => Api.undoDraft(matchId)));
  document.getElementById("autoFillBtn").addEventListener("click", autoFillDraft);
  document.getElementById("undoLiveBtn").addEventListener("click", () => act(() => Api.undoLiveEvent(matchId)));
  document.getElementById("applyGoldBtn").addEventListener("click", () => {
    const v = parseFloat(document.getElementById("goldInput").value || "0");
    act(() => Api.setGold(matchId, v));
  });
  document.getElementById("applyTimeBtn").addEventListener("click", () => {
    const v = parseFloat(document.getElementById("timeCorrectionInput").value || "0");
    act(() => Api.setTimeCorrection(matchId, v));
  });
  const nudgeSlider = document.getElementById("nudgeSlider");
  let nudgeDebounce = null;
  nudgeSlider.addEventListener("input", () => {
    document.getElementById("nudgeValue").textContent = `${parseFloat(nudgeSlider.value).toFixed(1)}pp`;
    clearTimeout(nudgeDebounce);
    nudgeDebounce = setTimeout(() => act(() => Api.setNudge(matchId, parseFloat(nudgeSlider.value) / 100)), 300);
  });
  document.getElementById("startMatchBtn").addEventListener("click", openRadiantPicker);
}

async function act(fn) {
  errorEl.innerHTML = "";
  try {
    const updated = await fn();
    await refresh(updated);
  } catch (e) {
    showError(errorEl, e);
  }
}

// ---------------------------------------------------------------------------
// Team Tendencies & Player Pool
// ---------------------------------------------------------------------------

function renderDashboard(dashboard) {
  document.getElementById("dashboardGrid").innerHTML = ["team_a", "team_b"].map(team => dashboardTeamCard(team, dashboard[team])).join("");
}

function dashboardTeamCard(team, data) {
  const label = session[team].label;
  const colorVar = team === "team_a" ? "var(--team-a)" : "var(--team-b)";
  const tendencyRow = h => `<div class="tendency-row"><div class="hero-swatch">${escapeHtml(heroCode(h.hero_name))}</div><div class="name">${escapeHtml(h.hero_name)}</div><div class="count">${h.count}x</div></div>`;
  const rosterRow = p => `
    <div class="roster-row">
      <div class="who"><div class="pname">${escapeHtml(p.name)}</div></div>
      <div class="heroes">${p.top_heroes.map(h => `
        <div class="roster-tile">
          <div class="code">${escapeHtml(heroCode(h.hero_name))}</div>
          <div class="wr ${winrateClass(h.win_rate * 100)}">${(h.win_rate * 100).toFixed(0)}%</div>
        </div>`).join("") || '<span class="faint">no data</span>'}
      </div>
    </div>`;

  return `
    <div class="panel team-card">
      <div class="team-card-head">
        <div class="team-card-bar" style="background:${colorVar}"></div>
        <div class="name">${escapeHtml(label)}</div>
        <div class="label">${team === "team_a" ? "Team A" : "Team B"}</div>
      </div>
      <div class="tendency-grid">
        <div>
          <div class="tendency-title">Most Picked</div>
          ${data.top_picks.slice(0, 3).map(tendencyRow).join("") || '<div class="faint">no draft history</div>'}
        </div>
        <div>
          <div class="tendency-title">Most Banned</div>
          ${data.top_bans.slice(0, 3).map(tendencyRow).join("") || '<div class="faint">no draft history</div>'}
        </div>
      </div>
      <div>
        <div class="tendency-title">Roster</div>
        <div class="roster-list">${data.players.map(rosterRow).join("")}</div>
      </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Draft
// ---------------------------------------------------------------------------

function usedHeroIds() {
  return new Set([...session.bans, ...session.picks].map(x => x.hero_id));
}

function renderDraft() {
  document.getElementById("autoFillBtn").style.display = session.phase === "draft" ? "inline-block" : "none";

  const step = session.draft_step;
  const banner = document.getElementById("turnBanner");
  if (!step) {
    banner.textContent = "DRAFT COMPLETE";
    banner.style.color = "var(--text-dim)";
  } else {
    const n = (step.type === "ban" ? session.bans : session.picks).filter(x => x.team === step.team).length + 1;
    const total = step.type === "ban" ? 7 : 5;
    banner.textContent = `${session[step.team].label.toUpperCase()} TO ${step.type.toUpperCase()} (${n}/${total})`;
    banner.style.color = step.team === "team_a" ? "var(--team-a)" : "var(--team-b)";
  }

  document.getElementById("banRows").innerHTML = ["team_a", "team_b"].map(team => banRowHtml(team)).join("");
  document.getElementById("pickRows").innerHTML = ["team_a", "team_b"].map(team => pickRowHtml(team)).join("");

  const used = usedHeroIds();
  const canAct = !!step;
  document.getElementById("heroGrid").innerHTML = heroNames.map(h => {
    const bannedBy = session.bans.find(b => b.hero_id === h.hero_id);
    const pickedBy = session.picks.find(p => p.hero_id === h.hero_id);
    const taken = used.has(h.hero_id);
    const clickable = canAct && !taken;
    let tagHtml = "";
    let borderStyle = "";
    if (bannedBy) tagHtml = `<div class="tag" style="color:var(--danger)">&#10005;</div>`;
    if (pickedBy) {
      const color = pickedBy.team === "team_a" ? "var(--team-a)" : "var(--team-b)";
      tagHtml = `<div class="tag" style="color:${color}">&#10003;</div>`;
      borderStyle = `border-color:${color};`;
    }
    return `<div class="hero-card ${clickable ? "clickable" : ""} ${taken ? "taken" : ""}" style="${borderStyle}" data-hero-id="${h.hero_id}" data-clickable="${clickable}">
      <div class="code">${escapeHtml(heroCode(h.name))}</div>
      <div class="name">${escapeHtml(h.name)}</div>
      ${tagHtml}
    </div>`;
  }).join("");

  document.getElementById("heroGrid").querySelectorAll('[data-clickable="true"]').forEach(el => {
    el.addEventListener("click", () => {
      const heroId = parseInt(el.dataset.heroId, 10);
      const s = session.draft_step;
      if (!s) return;
      const heroName = heroNamesById[heroId];
      const fn = s.type === "ban" ? Api.ban : Api.pick;
      act(() => fn(matchId, s.team, heroName));
    });
  });
}

function banRowHtml(team) {
  const label = session[team].label;
  const bans = session.bans.filter(b => b.team === team);
  const slots = Array.from({ length: 7 }, (_, i) => {
    const b = bans[i];
    if (!b) return `<div class="ban-slot"></div>`;
    return `<div class="ban-slot filled"><div class="code">${escapeHtml(heroCode(heroNamesById[b.hero_id] || ""))}</div><div class="x-mark">&#10005;</div></div>`;
  }).join("");
  return `<div><div class="tendency-title" style="color:${team === "team_a" ? "var(--team-a)" : "var(--team-b)"}">${escapeHtml(label)} Bans</div><div class="slot-row">${slots}</div></div>`;
}

function pickRowHtml(team) {
  const label = session[team].label;
  const picks = session.picks.filter(p => p.team === team);
  const color = team === "team_a" ? "var(--team-a)" : "var(--team-b)";
  const slots = Array.from({ length: 5 }, (_, i) => {
    const p = picks[i];
    if (!p) return `<div class="pick-slot" style="border:1px solid var(--border)"></div>`;
    const name = heroNamesById[p.hero_id] || "";
    return `<div class="pick-slot" style="border:1px solid ${color}"><div class="code">${escapeHtml(heroCode(name))}</div><div class="name">${escapeHtml(name)}</div></div>`;
  }).join("");
  return `<div><div class="tendency-title" style="color:${color}">${escapeHtml(label)} Picks</div><div class="slot-row">${slots}</div></div>`;
}

// ---------------------------------------------------------------------------
// Test helper: auto-fill the draft (random bans, each team's most-played
// heroes for picks) so manual testing doesn't require 24 individual clicks.
// ---------------------------------------------------------------------------

function pickRandomAvailableHero(used) {
  const pool = heroNames.filter(h => !used.has(h.hero_id));
  if (pool.length === 0) return null;
  return pool[Math.floor(Math.random() * pool.length)].name;
}

function pickMostPlayedAvailableHero(team, used) {
  const pickIndex = session.picks.filter(p => p.team === team).length;
  const player = dashboardData && dashboardData[team].players[pickIndex];
  if (player) {
    const candidate = player.top_heroes.find(h => !used.has(h.hero_id));
    if (candidate) return candidate.hero_name;
  }
  return pickRandomAvailableHero(used); // player has no cached top heroes left unused -- fall back
}

async function autoFillDraft() {
  errorEl.innerHTML = "";
  const btn = document.getElementById("autoFillBtn");
  btn.disabled = true;
  try {
    while (session.draft_step) {
      const step = session.draft_step;
      const used = usedHeroIds();
      const heroName = step.type === "ban" ? pickRandomAvailableHero(used) : pickMostPlayedAvailableHero(step.team, used);
      if (!heroName) throw new Error("Ran out of heroes to auto-fill with.");
      const fn = step.type === "ban" ? Api.ban : Api.pick;
      session = await fn(matchId, step.team, heroName);
    }
    assignmentView = await Api.getAssignment(matchId);
    renderAll(null);
  } catch (e) {
    showError(errorEl, e);
  } finally {
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Assignment
// ---------------------------------------------------------------------------

function renderAssign() {
  const visible = session.phase !== "draft";
  document.getElementById("assignSection").style.display = visible ? "block" : "none";
  if (!visible) return;

  document.getElementById("startMatchBtn").style.display = session.phase === "assignment" || session.phase === "ready" ? "inline-block" : "none";

  document.getElementById("assignGrid").innerHTML = ["team_a", "team_b"].map(team => assignTeamCard(team)).join("");

  document.getElementById("assignGrid").querySelectorAll("select[data-hero-id]").forEach(sel => {
    sel.addEventListener("change", () => {
      const heroId = parseInt(sel.dataset.heroId, 10);
      const team = sel.dataset.team;
      const accountId = sel.value ? parseInt(sel.value, 10) : null;
      act(() => Api.assign(matchId, team, heroId, accountId));
    });
  });
}

function assignTeamCard(team) {
  const label = session[team].label;
  const color = team === "team_a" ? "var(--team-a)" : "var(--team-b)";
  const view = assignmentView[team];
  const rows = view.drafted_heroes.map(h => `
    <div class="assign-row">
      <div class="code-box">${escapeHtml(heroCode(h.hero_name))}</div>
      <div class="hname">${escapeHtml(h.hero_name)}</div>
      <select data-hero-id="${h.hero_id}" data-team="${team}" ${session.phase === "draft" ? "disabled" : ""}>
        <option value="">-- assign player --</option>
        ${view.roster.map(p => `<option value="${p.account_id}" ${h.assigned_to === p.account_id ? "selected" : ""}>${escapeHtml(p.name)}</option>`).join("")}
      </select>
    </div>`).join("");
  return `
    <div class="panel" style="display:flex; flex-direction:column; gap:10px;">
      <div class="tendency-title" style="color:${color}; font-size:12px;">${escapeHtml(label)}</div>
      ${rows || '<div class="faint">no picks yet</div>'}
    </div>`;
}

function openRadiantPicker() {
  const modalRoot = document.getElementById("modalRoot");
  modalRoot.innerHTML = `
    <div class="modal-backdrop" id="modalBackdrop">
      <div class="modal">
        <h3>Which side is Radiant?</h3>
        <div class="confirm-row">
          <button data-team="team_a">${escapeHtml(session.team_a.label)} is Radiant</button>
          <button data-team="team_b">${escapeHtml(session.team_b.label)} is Radiant</button>
        </div>
      </div>
    </div>`;
  modalRoot.querySelectorAll("[data-team]").forEach(btn => {
    btn.addEventListener("click", () => {
      modalRoot.innerHTML = "";
      act(() => Api.startLive(matchId, btn.dataset.team));
    });
  });
  document.getElementById("modalBackdrop").addEventListener("click", (e) => {
    if (e.target.id === "modalBackdrop") modalRoot.innerHTML = "";
  });
}

// ---------------------------------------------------------------------------
// Live Match Tracker
// ---------------------------------------------------------------------------

function direTeam() { return session.radiant_team === "team_a" ? "team_b" : "team_a"; }

function renderLive() {
  const unlocked = session.phase === "live" || session.phase === "complete";
  document.getElementById("livePlaceholder").style.display = unlocked ? "none" : "block";
  document.getElementById("liveContent").style.display = unlocked ? "block" : "none";
  if (!unlocked) return;

  if (!window._ancientButtonsWired) {
    document.getElementById("goldLabel").textContent = `Gold lead (+${session.team_a.label})`;
    document.getElementById("radiantFellBtn").textContent = `${session[session.radiant_team].label}'s Ancient Fell`;
    document.getElementById("direFellBtn").textContent = `${session[direTeam()].label}'s Ancient Fell`;
    document.getElementById("radiantFellBtn").addEventListener("click", () => confirmAncient(session.radiant_team));
    document.getElementById("direFellBtn").addEventListener("click", () => confirmAncient(direTeam()));
    window._ancientButtonsWired = true;
  }

  document.getElementById("goldInput").value = session.live.gold_lead || "";
  const nudge = (session.live.manual_nudge_pp || 0) * 100;
  document.getElementById("nudgeSlider").value = nudge;
  document.getElementById("nudgeValue").textContent = `${nudge.toFixed(1)}pp`;

  const ended = session.phase === "complete";
  document.getElementById("radiantFellBtn").disabled = ended;
  document.getElementById("direFellBtn").disabled = ended;

  renderKillStrip();
  renderEventLog();
  Map2D.render(document.getElementById("mapContainer"), session, async (payload) => {
    const updated = await Api.liveEvent(matchId, payload);
    await refresh(updated);
    return updated;
  });
}

function renderKillStrip() {
  const el = document.getElementById("killStrip");
  const rows = [];
  for (const team of ["team_a", "team_b"]) {
    rows.push(`<div class="team-label" style="color:${team === "team_a" ? "var(--team-a)" : "var(--team-b)"}">${escapeHtml(session[team].label)}</div>`);
    for (const [heroId, accountId] of Object.entries(session.assignments[team])) {
      const name = heroNamesById[heroId] || `hero_${heroId}`;
      const kills = session.live.events.filter(e => e.event.event_type === "kill" && String(e.event.hero_id) === String(heroId)).length;
      const buybackActive = !!session.live.buybacks[heroId];
      rows.push(`
        <div class="kill-row">
          <button class="hero-btn" data-kill-hero="${heroId}" data-team="${team}">
            <span>${escapeHtml(name)}</span><span class="count">${kills} kills</span>
          </button>
          <button class="buyback-btn ${buybackActive ? "active" : ""}" data-buyback-hero="${heroId}">
            ${buybackActive ? "BB used" : "BB"}
          </button>
        </div>`);
    }
  }
  el.innerHTML = rows.join("");

  el.querySelectorAll("[data-kill-hero]").forEach(btn => {
    btn.addEventListener("click", () => act(() => Api.liveEvent(matchId, { event_type: "kill", hero_id: parseInt(btn.dataset.killHero, 10), credited_team: btn.dataset.team })));
  });
  el.querySelectorAll("[data-buyback-hero]").forEach(btn => {
    btn.addEventListener("click", () => act(() => Api.toggleBuyback(matchId, parseInt(btn.dataset.buybackHero, 10))));
  });
}

function renderEventLog() {
  const entries = session.prob_log.slice().reverse();
  const el = document.getElementById("eventLog");
  if (entries.length === 0) {
    el.innerHTML = `<div class="empty">No events logged yet -- click a button above once the match is live.</div>`;
    return;
  }
  el.innerHTML = entries.map(e => `
    <div class="entry">
      <span class="time">${fmtPct(e.prob_a)}</span>
      <span class="dot" style="background:${e.phase === "live" ? "var(--accent)" : "var(--text-faint)"}"></span>
      <span class="text">${escapeHtml(e.description)}</span>
    </div>`).join("");
}

function confirmAncient(losingTeam) {
  const modalRoot = document.getElementById("modalRoot");
  const losingLabel = session[losingTeam].label;
  modalRoot.innerHTML = `
    <div class="modal-backdrop" id="ancientModalBackdrop">
      <div class="modal">
        <h3>Confirm: ${escapeHtml(losingLabel)}'s Ancient fell?</h3>
        <p class="faint">This ends tracking and archives the match.</p>
        <div class="confirm-row">
          <button class="danger" id="ancientConfirmBtn">Confirm</button>
          <button id="ancientCancelBtn">Cancel</button>
        </div>
      </div>
    </div>`;
  document.getElementById("ancientConfirmBtn").addEventListener("click", () => {
    modalRoot.innerHTML = "";
    act(() => Api.endMatch(matchId, losingTeam));
  });
  document.getElementById("ancientCancelBtn").addEventListener("click", () => { modalRoot.innerHTML = ""; });
  modalRoot.querySelector("#ancientModalBackdrop").addEventListener("click", (e) => {
    if (e.target.id === "ancientModalBackdrop") modalRoot.innerHTML = "";
  });
}

load().catch(e => showError(errorEl, e));
