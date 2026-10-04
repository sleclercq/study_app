/*
 * store.js - Players, scores and progress, kept in the browser (localStorage).
 *
 * Nothing leaves the device: no server, no account. Each player is one entry
 *   revisions.player.<name> = {
 *     sessions: [{slug, played_at, score, total}],      oldest first
 *     prefs:    {slug: {wordKey: false}},                unticked words only
 *     progress: {slug: {wordKey: {box, due, ...}}},      progressive mode
 *   }
 * The flip side: a phone keeps its own progress. exportAll() / importAll() move
 * it to another device or keep a copy (the "Sauvegarde" panel of the app).
 *
 * Every read goes through try/catch: private browsing or a full storage must
 * degrade to "not saved" (memory only), never to a blank screen.
 */

const PLAYERS_KEY = "revisions.players";
const LAST_PLAYER_KEY = "revisions.last_player";
const PLAYER_PREFIX = "revisions.player.";
const FORMAT = "revisions-sauvegarde";

// Values the browser refused to store: they live here for the rest of the visit.
const memory = new Map();

let available = null;

/** False when the browser refuses to store anything: progress lives in memory only. */
export function isPersistent() {
  if (available === null) {
    try {
      localStorage.setItem("revisions.probe", "1");
      localStorage.removeItem("revisions.probe");
      available = true;
    } catch {
      available = false;
    }
  }
  return available && memory.size === 0;
}

function read(key) {
  if (memory.has(key)) return memory.get(key);
  let raw;
  try {
    raw = localStorage.getItem(key);
  } catch {
    return null;
  }
  if (raw === null) return null;
  try {
    return JSON.parse(raw);
  } catch {
    // Never silently overwrite what cannot be read: keep it aside.
    try { localStorage.setItem(`${key}.illisible`, raw); } catch { /* nothing more to do */ }
    return null;
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    memory.delete(key);
  } catch {
    memory.set(key, value);
  }
}

/** Ask the browser not to evict our data under storage pressure (best effort). */
export async function requestPersistence() {
  try {
    if (navigator.storage && navigator.storage.persist) await navigator.storage.persist();
  } catch { /* not supported: nothing to do */ }
}

export function listPlayers() {
  const names = read(PLAYERS_KEY);
  return Array.isArray(names)
    ? [...names].sort((a, b) => a.localeCompare(b, "fr", { sensitivity: "base" }))
    : [];
}

/** Create the player if needed (names are trimmed, case kept). Returns the name. */
export function addPlayer(name) {
  const clean = name.trim();
  if (!clean) return "";
  const names = listPlayers();
  if (!names.includes(clean)) write(PLAYERS_KEY, [...names, clean]);
  return clean;
}

export function lastPlayer() {
  const name = read(LAST_PLAYER_KEY);
  return typeof name === "string" && listPlayers().includes(name) ? name : null;
}

export function setLastPlayer(name) {
  write(LAST_PLAYER_KEY, name);
}

function emptyPlayer() {
  return { sessions: [], prefs: {}, progress: {} };
}

export function loadPlayer(name) {
  const doc = read(PLAYER_PREFIX + name);
  return doc && typeof doc === "object" ? { ...emptyPlayer(), ...doc } : emptyPlayer();
}

/**
 * Read-modify-write of one player. Reading again before each change means a
 * second tab or the installed app cannot wipe out what the other one saved.
 */
export function updatePlayer(name, change) {
  const doc = loadPlayer(name);
  const result = change(doc);
  write(PLAYER_PREFIX + name, doc);
  return result;
}

// ---------------------------------------------------------------------------
// Backup: one JSON file holding every player of this device.
// ---------------------------------------------------------------------------

export function exportAll() {
  const players = {};
  for (const name of listPlayers()) players[name] = loadPlayer(name);
  return { format: FORMAT, version: 1, exported_at: new Date().toISOString(), players };
}

/** Names found in a backup file, or throws when the file is not one of ours. */
export function backupPlayers(data) {
  if (!data || data.format !== FORMAT || typeof data.players !== "object" || data.players === null) {
    throw new Error("Ce fichier n'est pas une sauvegarde de Révisions.");
  }
  return Object.keys(data.players);
}

/** Restore a backup: the players it contains replace the ones of the same name. */
export function importAll(data) {
  const names = backupPlayers(data);
  for (const name of names) {
    const clean = addPlayer(name);
    if (clean) write(PLAYER_PREFIX + clean, { ...emptyPlayer(), ...data.players[name] });
  }
  return names;
}
