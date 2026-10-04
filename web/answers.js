/*
 * answers.js - Comparing what the child typed with what was expected.
 *
 * Same rules as answers.py (the desktop app), function for function:
 *
 *   no language code  strict historical comparison (Latin, English, French
 *                     grammar): lowercase, outer spaces and punctuation ignored.
 *   German ("de")     ä/ö/ü/ß may be typed ae/oe/ue/ss. The article stays
 *                     mandatory: "der Tisch" is not satisfied by "Tisch".
 *   French ("fr")     accents optional, leading article optional.
 *
 * A parenthesis in an expected answer is never required ("la fille (de
 * quelqu'un)" is answered "la fille"), and the synonyms of the JSON seed
 * (alt_source / alt_target) arrive here in `accepted`.
 *
 * Any change of tolerance here must be reflected in ANSWER_RULES (app.js):
 * the child reads those rules on screen.
 */

// ü -> ue etc. Applied after lowercasing, so only lowercase forms are needed.
const DE_SUBSTITUTIONS = [["ä", "ae"], ["ö", "oe"], ["ü", "ue"], ["ß", "ss"]];

// Dropped when they open a French answer ("l'école" -> "ecole"). Order matters.
const FR_LEADING_ARTICLES = [
  "le ", "la ", "les ", "l'", "un ", "une ", "des ",
  "du ", "de la ", "de l'", "de ", "d'",
];

const PAREN_RE = /\s*\([^)]*\)/g;

// Punctuation that never changes the answer, only the typing.
const TRIM_CHARS = " \t\n.,;:!?\"'«»";

// German articles that may open an answer (hints never spell them out).
const DE_ARTICLES = ["der", "die", "das", "den", "dem", "ein", "eine", "einen"];

/** Python's str.strip(chars): remove any of `chars` from both ends. */
export function stripChars(text, chars) {
  let start = 0;
  let end = text.length;
  while (start < end && chars.includes(text[start])) start++;
  while (end > start && chars.includes(text[end - 1])) end--;
  return text.slice(start, end);
}

/** Collapse every run of whitespace into one space (Python's " ".join(s.split())). */
export function collapseSpaces(text) {
  return text.split(/\s+/).filter(Boolean).join(" ");
}

/**
 * Lowercase, trim outer punctuation/spaces, collapse inner whitespace.
 * Ligatures are spelled out (œ -> oe), the curly apostrophe becomes a straight
 * one and an ellipsis marking a gap ("Wie …?") disappears.
 */
export function normalize(text) {
  let out = String(text).trim().toLowerCase()
    .replaceAll("œ", "oe").replaceAll("æ", "ae");
  out = out.replaceAll("’", "'").replaceAll("…", " ").replaceAll("...", " ");
  out = collapseSpaces(out);
  return stripChars(out, TRIM_CHARS).trim();
}

/** "élève" -> "eleve" (leaves ß alone, it is not an accent). */
function stripAccents(text) {
  return text.normalize("NFD").replace(/\p{Mn}/gu, "");
}

/** German comparison key: umlauts folded to their two-letter spelling. */
function deKey(text) {
  for (const [char, replacement] of DE_SUBSTITUTIONS) text = text.replaceAll(char, replacement);
  return text;
}

/** French comparison key: accents dropped, leading article optional. */
function frKey(text) {
  text = stripAccents(text);
  for (const article of FR_LEADING_ARTICLES) {
    if (text.startsWith(article)) return text.slice(article.length).trim();
  }
  return text;
}

/** Every spelling that counts as "this answer" in the given language. */
export function keysFor(text, lang = "") {
  const variants = new Set([normalize(text), normalize(String(text).replace(PAREN_RE, ""))]);
  const keys = new Set(variants);
  for (const variant of variants) {
    if (lang === "de") {
      keys.add(deKey(variant));
    } else if (lang === "fr") {
      keys.add(stripAccents(variant));   // accents optional
      keys.add(frKey(variant));          // accents + leading article optional
    }
  }
  keys.delete("");
  return keys;
}

/**
 * True when `given` is one of the `accepted` answers.
 * accepted: a string or a list of strings (expected answer + synonyms).
 */
export function matches(given, accepted, lang = "") {
  const candidates = typeof accepted === "string" ? [accepted] : accepted;
  const givenKeys = keysFor(given, lang);
  if (givenKeys.size === 0) return false;
  for (const candidate of candidates) {
    for (const key of keysFor(candidate, lang)) {
      if (givenKeys.has(key)) return true;
    }
  }
  return false;
}

/**
 * The part of the answer the hint letters are taken from. For a German noun the
 * article is stripped: hinting on "der Tisch" would hand over the gender.
 */
export function hintBase(answer, lang = "") {
  if (lang !== "de") return answer;
  const parts = answer.trim().split(/\s+/);
  if (parts.length >= 2 && DE_ARTICLES.includes(parts[0].toLowerCase())) {
    return parts.slice(1).join(" ");
  }
  return answer;
}

/**
 * The hint shown after a wrong attempt:
 *   attempt 1 -> first 2 letters
 *   attempt 2 -> first 4 letters, or len - 1 when the word is 4 letters or less
 */
export function hintPrefix(answer, attempt, lang = "") {
  const base = hintBase(answer, lang);
  if (!base) return "";
  const n = base.length;
  const length = attempt <= 1 ? 2 : (n <= 4 ? n - 1 : 4);
  return base.slice(0, Math.max(length, 1));
}
