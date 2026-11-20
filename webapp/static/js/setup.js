// setup.js -- index.html: new-matchup form with team typeahead + past matches list.

const errorEl = document.getElementById("error");

function wireTypeahead(inputEl, suggestionsEl) {
  let debounceTimer = null;
  inputEl.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    const q = inputEl.value.trim();
    if (q.length < 2) { suggestionsEl.innerHTML = ""; return; }
    debounceTimer = setTimeout(async () => {
      try {
        const data = await Api.searchTeams(q);
        const names = data.results.map(r => r.name).concat(data.candidates || []);
        const unique = [...new Set(names)];
        suggestionsEl.innerHTML = unique.map(n => `<div>${escapeHtmlLite(n)}</div>`).join("");
        suggestionsEl.querySelectorAll("div").forEach(div => {
          div.addEventListener("click", () => {
            inputEl.value = div.textContent;
            suggestionsEl.innerHTML = "";
          });
        });
      } catch (e) { /* ignore typeahead errors */ }
    }, 200);
  });
  document.addEventListener("click", (e) => {
    if (!suggestionsEl.contains(e.target) && e.target !== inputEl) suggestionsEl.innerHTML = "";
  });
}

function escapeHtmlLite(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

wireTypeahead(document.getElementById("teamAInput"), document.getElementById("teamASuggestions"));
wireTypeahead(document.getElementById("teamBInput"), document.getElementById("teamBSuggestions"));

document.getElementById("createBtn").addEventListener("click", async () => {
  const teamA = document.getElementById("teamAInput").value.trim();
  const teamB = document.getElementById("teamBInput").value.trim();
  const firstPickTeam = document.getElementById("firstPickSelect").value;
  if (!teamA || !teamB) return;
  errorEl.innerHTML = "";
  try {
    const session = await Api.createMatch(teamA, teamB, firstPickTeam);
    window.location.href = `match.html?m=${session.match_session_id}`;
  } catch (e) {
    showError(errorEl, e);
  }
});

const PHASE_LABELS = { draft: "Draft", assignment: "Assign Players", ready: "Ready", live: "Live", complete: "Complete" };

async function loadMatches() {
  const listEl = document.getElementById("matchList");
  const data = await Api.listMatches();
  if (data.matches.length === 0) {
    listEl.innerHTML = `<div class="muted">No tracked matches yet.</div>`;
    return;
  }
  listEl.innerHTML = data.matches.map(m => `
    <div class="match-row">
      <div>
        <div class="matchup">${escapeHtmlLite(m.team_a_label)} vs ${escapeHtmlLite(m.team_b_label)}</div>
        <div class="faint">${new Date(m.updated_at * 1000).toLocaleString()}</div>
      </div>
      <div style="display:flex; align-items:center; gap:10px;">
        <span class="phase-badge">${PHASE_LABELS[m.phase] || m.phase}</span>
        <a class="btn" href="match.html?m=${m.match_session_id}">Open</a>
      </div>
    </div>`).join("");
}

loadMatches().catch(e => showError(errorEl, e));
