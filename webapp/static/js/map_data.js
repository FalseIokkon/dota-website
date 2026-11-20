// map_data.js -- static, frontend-only objective layout for the live map.
// The backend (webapp/live_events.py) never sees any of this geometry --
// it only ever reasons about (event_type, credited_team, tier/rax_type).
//
// Coordinates are percentages (0-100) of the map image's width/height,
// Radiant base bottom-left, Dire base top-right (matches the standard
// minimap orientation). These are a reasonable first-pass approximation of
// real tower/barracks/Roshan positions, not a pixel-surveyed overlay --
// nudge x/y here once the real map image is in place and this is viewed
// live in-browser; every objective is a single row in this table.
//
// `side` is "radiant" | "dire" | "neutral" -- resolved to the session's
// actual team_a/team_b at render time via session.radiant_team (a team's
// historical rating-side has no bearing on which side they play tonight,
// see draft_engine.start_live_match).

const MAP_OBJECTIVES = [
  // ---- Radiant towers ----
  { id: "radiant_t1_top", side: "radiant", type: "tower", tier: 1, lane: "top", x: 35, y: 13, label: "Radiant T1 Top" },
  { id: "radiant_t2_top", side: "radiant", type: "tower", tier: 2, lane: "top", x: 22, y: 15, label: "Radiant T2 Top" },
  { id: "radiant_t3_top", side: "radiant", type: "tower", tier: 3, lane: "top", x: 13, y: 24, label: "Radiant T3 Top" },
  { id: "radiant_t1_mid", side: "radiant", type: "tower", tier: 1, lane: "mid", x: 34, y: 66, label: "Radiant T1 Mid" },
  { id: "radiant_t2_mid", side: "radiant", type: "tower", tier: 2, lane: "mid", x: 25, y: 75, label: "Radiant T2 Mid" },
  { id: "radiant_t3_mid", side: "radiant", type: "tower", tier: 3, lane: "mid", x: 19, y: 81, label: "Radiant T3 Mid" },
  { id: "radiant_t1_bot", side: "radiant", type: "tower", tier: 1, lane: "bot", x: 38, y: 91, label: "Radiant T1 Bot" },
  { id: "radiant_t2_bot", side: "radiant", type: "tower", tier: 2, lane: "bot", x: 25, y: 90, label: "Radiant T2 Bot" },
  { id: "radiant_t3_bot", side: "radiant", type: "tower", tier: 3, lane: "bot", x: 15, y: 85, label: "Radiant T3 Bot" },
  { id: "radiant_t4_1", side: "radiant", type: "tower", tier: 4, lane: null, x: 12, y: 87, label: "Radiant T4 (1)" },
  { id: "radiant_t4_2", side: "radiant", type: "tower", tier: 4, lane: null, x: 16, y: 93, label: "Radiant T4 (2)" },

  // ---- Dire towers ----
  { id: "dire_t1_top", side: "dire", type: "tower", tier: 1, lane: "top", x: 62, y: 9, label: "Dire T1 Top" },
  { id: "dire_t2_top", side: "dire", type: "tower", tier: 2, lane: "top", x: 74, y: 9, label: "Dire T2 Top" },
  { id: "dire_t3_top", side: "dire", type: "tower", tier: 3, lane: "top", x: 85, y: 15, label: "Dire T3 Top" },
  { id: "dire_t1_mid", side: "dire", type: "tower", tier: 1, lane: "mid", x: 62, y: 38, label: "Dire T1 Mid" },
  { id: "dire_t2_mid", side: "dire", type: "tower", tier: 2, lane: "mid", x: 72, y: 27, label: "Dire T2 Mid" },
  { id: "dire_t3_mid", side: "dire", type: "tower", tier: 3, lane: "mid", x: 79, y: 21, label: "Dire T3 Mid" },
  { id: "dire_t1_bot", side: "dire", type: "tower", tier: 1, lane: "bot", x: 62, y: 91, label: "Dire T1 Bot" },
  { id: "dire_t2_bot", side: "dire", type: "tower", tier: 2, lane: "bot", x: 75, y: 90, label: "Dire T2 Bot" },
  { id: "dire_t3_bot", side: "dire", type: "tower", tier: 3, lane: "bot", x: 85, y: 85, label: "Dire T3 Bot" },
  { id: "dire_t4_1", side: "dire", type: "tower", tier: 4, lane: null, x: 88, y: 13, label: "Dire T4 (1)" },
  { id: "dire_t4_2", side: "dire", type: "tower", tier: 4, lane: null, x: 84, y: 7, label: "Dire T4 (2)" },

  // ---- Radiant barracks (melee + ranged per lane) ----
  { id: "radiant_rax_top_melee", side: "radiant", type: "barracks", rax_type: "melee", lane: "top", x: 9, y: 27, label: "Radiant Top Melee Rax" },
  { id: "radiant_rax_top_ranged", side: "radiant", type: "barracks", rax_type: "ranged", lane: "top", x: 9, y: 31, label: "Radiant Top Ranged Rax" },
  { id: "radiant_rax_mid_melee", side: "radiant", type: "barracks", rax_type: "melee", lane: "mid", x: 14, y: 85, label: "Radiant Mid Melee Rax" },
  { id: "radiant_rax_mid_ranged", side: "radiant", type: "barracks", rax_type: "ranged", lane: "mid", x: 18, y: 88, label: "Radiant Mid Ranged Rax" },
  { id: "radiant_rax_bot_melee", side: "radiant", type: "barracks", rax_type: "melee", lane: "bot", x: 10, y: 80, label: "Radiant Bot Melee Rax" },
  { id: "radiant_rax_bot_ranged", side: "radiant", type: "barracks", rax_type: "ranged", lane: "bot", x: 10, y: 84, label: "Radiant Bot Ranged Rax" },

  // ---- Dire barracks ----
  { id: "dire_rax_top_melee", side: "dire", type: "barracks", rax_type: "melee", lane: "top", x: 90, y: 16, label: "Dire Top Melee Rax" },
  { id: "dire_rax_top_ranged", side: "dire", type: "barracks", rax_type: "ranged", lane: "top", x: 90, y: 20, label: "Dire Top Ranged Rax" },
  { id: "dire_rax_mid_melee", side: "dire", type: "barracks", rax_type: "melee", lane: "mid", x: 84, y: 17, label: "Dire Mid Melee Rax" },
  { id: "dire_rax_mid_ranged", side: "dire", type: "barracks", rax_type: "ranged", lane: "mid", x: 81, y: 14, label: "Dire Mid Ranged Rax" },
  { id: "dire_rax_bot_melee", side: "dire", type: "barracks", rax_type: "melee", lane: "bot", x: 90, y: 78, label: "Dire Bot Melee Rax" },
  { id: "dire_rax_bot_ranged", side: "dire", type: "barracks", rax_type: "ranged", lane: "bot", x: 90, y: 82, label: "Dire Bot Ranged Rax" },

  // ---- Neutral objectives ----
  { id: "roshan", side: "neutral", type: "roshan", x: 41, y: 61, label: "Roshan" },
  { id: "tormentor_radiant_side", side: "neutral", type: "tormentor", x: 24, y: 77, label: "Tormentor (Radiant jungle)" },
  { id: "tormentor_dire_side", side: "neutral", type: "tormentor", x: 76, y: 24, label: "Tormentor (Dire jungle)" },
];
