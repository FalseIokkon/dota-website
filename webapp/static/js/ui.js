// ui.js -- small render helpers shared across match.html's sections.

let _heroNamesCache = null;
async function getHeroNames() {
  if (_heroNamesCache) return _heroNamesCache;
  const data = await Api.listHeroes();
  _heroNamesCache = data.heroes; // [{hero_id, name}], sorted by name
  return _heroNamesCache;
}

function currentProb(session) {
  // Whichever anchor is live right now, in phase order.
  if (session.phase === "live" || session.phase === "complete") return session.live_prob_a;
  if (session.phase === "assignment" || session.phase === "ready") return session.assigned_prob_a;
  return session.draft_prob_a;
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function fmtClock(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

// A short (<=4 char) code from a hero's real name, for the compact grid/slot
// tiles -- e.g. "Anti-Mage" -> "AM", "Keeper of the Light" -> "KOTL"
// (short filler words dropped), "Ogre Magi" -> "OGMA". Not a curated
// abbreviation table -- purely derived, good enough for a dense grid label.
const _CODE_SKIP_WORDS = new Set(["of", "the", "and"]);
function heroCode(name) {
  const words = name.split(/[\s'-]+/).filter(w => w && !_CODE_SKIP_WORDS.has(w.toLowerCase()));
  if (words.length >= 2) {
    return words.map(w => w[0]).join("").toUpperCase().slice(0, 4);
  }
  return (words[0] || name).slice(0, 4).toUpperCase();
}

function teamInitials(label) {
  const words = label.split(/\s+/).filter(Boolean);
  if (words.length >= 2) return words.map(w => w[0]).join("").toUpperCase().slice(0, 3);
  return label.slice(0, 3).toUpperCase();
}

function winrateClass(wr) {
  if (wr >= 55) return "wr-good";
  if (wr >= 48) return "wr-mid";
  return "wr-bad";
}
