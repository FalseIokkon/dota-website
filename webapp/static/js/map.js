// map.js -- renders MAP_OBJECTIVES as an SVG overlay on top of the map
// image (webapp/static/img/dota_map.png -- falls back to a plain schematic
// background if that file isn't present yet). Clicking a tower/barracks
// posts a live event immediately (ownership is fixed, so the opposing team
// is credited automatically); clicking Roshan/a Tormentor opens a picker
// of the 10 assigned heroes first.

const Map2D = (() => {
  let session = null;
  let onEvent = null; // async (eventPayload) => updated session

  function sideToTeam(side) {
    if (side === "neutral") return null;
    const radiant = session.radiant_team; // "team_a" | "team_b"
    const dire = radiant === "team_a" ? "team_b" : "team_a";
    return side === "radiant" ? radiant : dire;
  }

  function owningTeamLabel(side) {
    const team = sideToTeam(side);
    return team ? session[team].label : "";
  }

  function creditedTeamForObjective(obj) {
    // A tower/barracks credits the team OPPOSITE its owner.
    const owner = sideToTeam(obj.side);
    return owner === "team_a" ? "team_b" : "team_a";
  }

  function render(containerEl, sessionData, onEventCb) {
    session = sessionData;
    onEvent = onEventCb;

    containerEl.innerHTML = `
      <div class="map-wrap" id="mapWrap">
        <img class="map-bg" id="mapBgImg" src="img/dota_map.jpg" alt=""
             onerror="this.style.display='none'; document.getElementById('mapWrap').style.background='linear-gradient(135deg, #24361f 0%, #24361f 45%, #2b3550 50%, #232838 55%, #232838 100%)';">
        <svg class="map-overlay" viewBox="0 0 100 100" preserveAspectRatio="none"></svg>
      </div>`;

    drawMarkers(containerEl.querySelector("svg"));
  }

  function drawMarkers(svg) {
    const destroyed = new Set(session.live.destroyed_objectives || []);
    svg.innerHTML = MAP_OBJECTIVES.map(obj => markerSvg(obj, destroyed.has(obj.id))).join("");

    MAP_OBJECTIVES.forEach(obj => {
      const el = svg.querySelector(`[data-obj="${obj.id}"]`);
      if (!el) return;
      el.addEventListener("click", () => handleClick(obj, destroyed.has(obj.id)));
    });
  }

  function markerSvg(obj, isDestroyed) {
    const sideClass = obj.side === "neutral" ? "neutral" : `side-${obj.side === sideOfTeamA() ? "a" : "b"}`;
    const classes = `obj-marker ${sideClass} ${isDestroyed ? "destroyed" : ""}`;
    if (obj.type === "tower") {
      const r = obj.tier === 4 ? 1.6 : 1.3;
      return `<g class="${classes}" data-obj="${obj.id}"><circle cx="${obj.x}" cy="${obj.y}" r="${r}" stroke-width="0.3"><title>${obj.label}</title></circle></g>`;
    }
    if (obj.type === "barracks") {
      return `<g class="${classes}" data-obj="${obj.id}"><rect x="${obj.x - 1.1}" y="${obj.y - 1.1}" width="2.2" height="2.2" stroke-width="0.3"><title>${obj.label}</title></rect></g>`;
    }
    // roshan / tormentor
    const r = obj.type === "roshan" ? 2.1 : 1.6;
    return `<g class="${classes}" data-obj="${obj.id}"><circle cx="${obj.x}" cy="${obj.y}" r="${r}" stroke-width="0.3"><title>${obj.label}</title></circle></g>`;
  }

  function sideOfTeamA() {
    return session.radiant_team === "team_a" ? "radiant" : "dire";
  }

  async function handleClick(obj, isDestroyed) {
    if (isDestroyed) return;

    if (obj.type === "tower" || obj.type === "barracks") {
      const payload = {
        event_type: "building",
        building_type: obj.type,
        tier: obj.tier || null,
        lane: obj.lane || null,
        rax_type: obj.rax_type || null,
        credited_team: creditedTeamForObjective(obj),
        objective_id: obj.id,
      };
      session = await onEvent(payload);
      drawMarkers(document.querySelector(".map-overlay"));
      return;
    }

    // roshan / tormentor -- open hero picker first
    openHeroPicker(obj);
  }

  function openHeroPicker(obj) {
    const heroes = allAssignedHeroes(session);
    const modalRoot = document.getElementById("modalRoot");
    modalRoot.innerHTML = `
      <div class="modal-backdrop" id="mapModalBackdrop">
        <div class="modal">
          <h3>Who got ${obj.label}?</h3>
          <div class="list-grid">
            ${heroes.map(h => `<button data-hero="${h.hero_id}" data-team="${h.team}">${escapeHtml(h.name)} <span class="faint">(${escapeHtml(session[h.team].label)})</span></button>`).join("") || '<span class="faint">No players assigned yet.</span>'}
          </div>
        </div>
      </div>`;
    modalRoot.querySelectorAll("[data-hero]").forEach(btn => {
      btn.addEventListener("click", async () => {
        modalRoot.innerHTML = "";
        const payload = {
          event_type: obj.type, // "roshan" | "tormentor"
          hero_id: parseInt(btn.dataset.hero, 10),
          credited_team: btn.dataset.team,
          objective_id: null, // repeatable objectives -- not tracked in destroyed_objectives
        };
        session = await onEvent(payload);
        drawMarkers(document.querySelector(".map-overlay"));
      });
    });
    document.getElementById("mapModalBackdrop").addEventListener("click", (e) => {
      if (e.target.id === "mapModalBackdrop") modalRoot.innerHTML = "";
    });
  }

  function allAssignedHeroes(sessionData) {
    const result = [];
    for (const team of ["team_a", "team_b"]) {
      for (const [heroId, accountId] of Object.entries(sessionData.assignments[team])) {
        const hero = window.HERO_NAMES_BY_ID ? window.HERO_NAMES_BY_ID[heroId] : null;
        result.push({ hero_id: parseInt(heroId, 10), team, name: hero || `hero_${heroId}` });
      }
    }
    return result;
  }

  function updateSession(sessionData) {
    session = sessionData;
    const svg = document.querySelector(".map-overlay");
    if (svg) drawMarkers(svg);
  }

  return { render, updateSession };
})();
