/*
 * engine.js - Question builders and the progressive mode (Leitner boxes).
 *
 * Port of the query functions of db.py: same questions, same wording, same
 * rules. Pure functions, no DOM and no storage, so that they can be tested with
 * `node --test tests/` (the GitHub workflow refuses to publish when they fail).
 *
 * An exercise is the object built by tools/build_site.py from its JSON file in
 * data/: the metadata (kind, prompts, languages...) plus `words`, each word being
 * {source, canonical, theme, forms: [{label, value}], alt_source, alt_target}.
 * A word is identified by source + canonical, exactly like the desktop app's
 * seeding: correcting a word in its file starts it over as a new word.
 */

export const SESSION_LENGTH = 20;

export const DIRECTION_FORWARD = "forward";   // French -> foreign language (production)
export const DIRECTION_REVERSE = "reverse";   // foreign language -> French (comprehension)
export const DIRECTION_MIXED = "mixed";       // both, shuffled together

/** Stable identity of a word, used by the word selection and the progress. */
export function wordKey(word) {
  return `${word.source}\u001f${word.canonical}`;
}

/** Fisher-Yates, in place. `rng` is injectable for the tests. */
export function shuffle(items, rng = Math.random) {
  for (let i = items.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
}

/**
 * Render a prompt template from the JSON seed, e.g. "Traduis en allemand : « {source} »".
 * Falls back to `fallback` when the exercise defines no template, and returns
 * the template untouched when it names an unknown placeholder (like Python's
 * str.format raising KeyError in db._fill).
 */
export function fill(template, fallback, values) {
  const text = template || fallback;
  let unknown = false;
  const out = text.replace(/\{(\w*)\}/g, (match, name) => {
    if (Object.prototype.hasOwnProperty.call(values, name)) return values[name];
    unknown = true;
    return match;
  });
  return unknown ? text : out;
}

function selected(words, enabledKeys) {
  return enabledKeys ? words.filter((w) => enabledKeys.has(wordKey(w))) : words;
}

const isMeta = (label) => label.startsWith("__");

/** kind "forms": the canonical translation, then one question per form. */
export function buildFormsQuestions(exercise, enabledKeys = null) {
  const target = exercise.target_language ?? "";
  const questions = [];
  for (const word of selected(exercise.words, enabledKeys)) {
    const { source, canonical } = word;
    if (canonical) {
      questions.push({
        type: "canonical",
        prompt: fill(exercise.canonical_prompt,
          "Comment dit-on « {source} » en {target_language} ?",
          { source, canonical, target_language: target }),
        answer: canonical,
        word_source: source,
      });
    }
    for (const { label, value } of word.forms ?? []) {
      if (isMeta(label)) continue;
      questions.push({
        type: "form",
        prompt: fill(exercise.form_prompt, "« {source} » - {label}",
          { source, canonical, label, target_language: target }),
        answer: value,
        word_source: source,
      });
    }
  }
  return questions;
}

/** kind "triple": English irregular verbs, the three forms at once. */
export function buildTripleQuestions(exercise, enabledKeys = null) {
  return selected(exercise.words, enabledKeys).map((word) => {
    const forms = Object.fromEntries((word.forms ?? []).map((f) => [f.label, f.value]));
    return {
      type: "english_irregular",
      source: word.source,
      base: forms["base verbale"] ?? "",
      preterit: forms["prétérit"] ?? "",
      past_participle: forms["participe passé"] ?? "",
    };
  });
}

/**
 * One translation question for a vocabulary word, in the given direction.
 * Shared by the free mode and the progressive mode.
 */
export function vocabQuestion(exercise, word, direction) {
  const { source, canonical } = word;
  const args = {
    source, canonical,
    source_language: exercise.source_language ?? "français",
    target_language: exercise.target_language ?? "",
  };
  if (direction === DIRECTION_FORWARD) {
    return {
      type: "vocab",
      direction: DIRECTION_FORWARD,
      prompt: fill(exercise.canonical_prompt,
        "Traduis en {target_language} : « {source} »", args),
      answer: canonical,
      accepted: [canonical, ...(word.alt_target ?? [])],
      answer_lang: exercise.target_lang_code ?? "",
      word_source: source,
      theme: word.theme ?? "",
    };
  }
  return {
    type: "vocab",
    direction: DIRECTION_REVERSE,
    prompt: fill(exercise.reverse_prompt,
      "Traduis en {source_language} : « {canonical} »", args),
    answer: source,
    accepted: [source, ...(word.alt_source ?? [])],
    answer_lang: exercise.source_lang_code ?? "",
    word_source: source,
    theme: word.theme ?? "",
  };
}

/** kinds "vocab" and free "leitner": each word asked one way, the other, or both. */
export function buildVocabQuestions(exercise, enabledKeys = null, direction = DIRECTION_MIXED) {
  const wanted = direction === DIRECTION_FORWARD ? [DIRECTION_FORWARD]
    : direction === DIRECTION_REVERSE ? [DIRECTION_REVERSE]
      : [DIRECTION_FORWARD, DIRECTION_REVERSE];
  const questions = [];
  for (const word of selected(exercise.words, enabledKeys)) {
    if (!word.canonical) continue;
    for (const one of wanted) questions.push(vocabQuestion(exercise, word, one));
  }
  return questions;
}

/** kind "sentences": a bank of sentences with a blank. */
export function buildSentenceQuestions(exercise) {
  return exercise.words.map((word) => ({
    type: "fill_blank",
    prompt: word.source,
    answer: word.canonical,
  }));
}

/** kind "accord_pp": the sentence, the expected participle, its case and its COD. */
export function buildAccordQuestions(exercise) {
  return exercise.words.map((word) => {
    const meta = Object.fromEntries((word.forms ?? []).map((f) => [f.label, f.value]));
    return {
      type: "accord_pp",
      prompt: word.source,
      answer: word.canonical,
      case: meta.__case__ ?? "",
      cod: meta.__cod__ ?? "",
    };
  });
}

// ---------------------------------------------------------------------------
// Progressive mode (Leitner boxes) - see the long comment in db.py, same rules.
//
//   box 0  never asked     French -> German, as a test
//   box 1  to learn        German -> French, back the same day
//   box 2  recognised      French -> German from now on, back the next day
//   box 3  produced once   back in 3 days
//   box 4  produced twice  back in 7 days
//   box 5  acquis          back in 60 days, as a spot check
//
// Right at the 1st try: up one box (a new word goes straight to 5). Right at
// the 2nd or 3rd try: down one box, never below 2 (a new word starts at 2).
// Revealed: box 1. These numbers were tuned by simulating 980 words:
// re-simulate before changing a constant.
//
// The progress of a player on an exercise is a plain object
//   { [wordKey]: {box, due, seen, first_known, first_seen, last_seen} }
// No entry = never seen.
// ---------------------------------------------------------------------------

export const BOX_INTERVAL_DAYS = { 1: 0, 2: 1, 3: 3, 4: 7, 5: 60 };
export const BOX_TO_LEARN = 1;
export const BOX_PRODUCTION = 2;
export const BOX_ACQUIRED = 5;
export const RESULT_FIRST = "first";
export const RESULT_HINT = "hint";
export const RESULT_MISSED = "missed";
export const NEW_WORDS_MIN = 6;
export const NEW_WORDS_CAP = [8, 20];
export const NEW_WORDS_FIRST_CAP = 10;
export const NEW_WORDS_WINDOW = 20;

const pad = (n) => String(n).padStart(2, "0");

/** Today in local time, "YYYY-MM-DD" (like date.today().isoformat()). */
export function localDate(d = new Date()) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Local time to the second, "YYYY-MM-DDTHH:MM:SS" (like datetime.now().isoformat()). */
export function localStamp(d = new Date()) {
  return `${localDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function addDays(day, days) {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** Python's round(): halves go to the even neighbour. */
export function roundHalfEven(x) {
  const floor = Math.floor(x);
  const diff = x - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

/** Where a word goes after being asked, given its box before the question. */
export function nextBox(box, result) {
  if (box === 0) {
    if (result === RESULT_FIRST) return BOX_ACQUIRED;
    return result === RESULT_HINT ? BOX_PRODUCTION : BOX_TO_LEARN;
  }
  if (box === BOX_TO_LEARN) return result === RESULT_FIRST ? BOX_PRODUCTION : BOX_TO_LEARN;
  if (result === RESULT_FIRST) return Math.min(box + 1, BOX_ACQUIRED);
  if (result === RESULT_HINT) return Math.max(BOX_PRODUCTION, box - 1);
  return BOX_TO_LEARN;
}

/** Outcome of a question from the attempt that found it (or not). */
export function resultOf(attempts, found) {
  if (!found) return RESULT_MISSED;
  return attempts === 1 ? RESULT_FIRST : RESULT_HINT;
}

/** The words a progressive exercise is made of (a word needs a translation). */
function leitnerWords(exercise) {
  return exercise.words.filter((w) => w.canonical !== "");
}

/**
 * How many new words the next session may bring: the more of the recent new
 * words were already known, the faster the list is walked through. Like the
 * desktop query, words since retired from the file still count.
 */
export function newWordCap(exercise, progress) {
  const order = new Map(exercise.words.map((w, i) => [wordKey(w), i]));
  const recent = Object.entries(progress)
    .map(([key, row]) => ({ row, index: order.get(key) ?? -1 }))
    .sort((a, b) => {
      if (a.row.first_seen !== b.row.first_seen) return a.row.first_seen < b.row.first_seen ? 1 : -1;
      return b.index - a.index;
    })
    .slice(0, NEW_WORDS_WINDOW);
  if (recent.length < Math.floor(NEW_WORDS_WINDOW / 2)) return NEW_WORDS_FIRST_CAP;
  const knownRate = recent.reduce((sum, { row }) => sum + row.first_known, 0) / recent.length;
  const [low, high] = NEW_WORDS_CAP;
  return low + roundHalfEven((high - low) * knownRate);
}

/**
 * Today's progressive session: the words due for review, weakest box first,
 * then new words in file order (the textbook's order) at the pace set by
 * newWordCap(). Box 1 is asked German -> French, every other box French ->
 * German. Returns [] when nothing is due and every word has been introduced.
 */
export function buildProgressiveQuestions(exercise, progress, { today = localDate(), size = SESSION_LENGTH, rng = Math.random } = {}) {
  const words = leitnerWords(exercise).map((word, index) => {
    const row = progress[wordKey(word)];
    return { word, index, box: row ? row.box : 0, due: row ? row.due : "" };
  });
  const due = words
    .filter((w) => w.box >= 1 && w.due <= today)
    .sort((a, b) => a.box - b.box || (a.due < b.due ? -1 : a.due > b.due ? 1 : 0) || a.index - b.index);
  const unseen = words.filter((w) => w.box === 0);

  const cap = newWordCap(exercise, progress);
  const roomForNew = unseen.length ? Math.max(size - due.length, NEW_WORDS_MIN) : 0;
  const nNew = Math.min(cap, unseen.length, roomForNew);
  const chosen = [...due.slice(0, Math.max(0, size - nNew)), ...unseen.slice(0, nNew)];

  const questions = chosen.map(({ word, box }) => {
    const direction = box === BOX_TO_LEARN ? DIRECTION_REVERSE : DIRECTION_FORWARD;
    return { ...vocabQuestion(exercise, word, direction), progressive: true, word_key: wordKey(word), box };
  });
  return shuffle(questions, rng);
}

/** File the outcome of one progressive question (mutates `progress`), return the new box. */
export function recordProgress(progress, key, result, { today = localDate(), now = localStamp() } = {}) {
  const row = progress[key];
  const box = row ? row.box : 0;
  const newBox = nextBox(box, result);
  const due = addDays(today, BOX_INTERVAL_DAYS[newBox]);
  if (!row) {
    progress[key] = {
      box: newBox, due, seen: 1, first_known: result === RESULT_FIRST ? 1 : 0,
      first_seen: now, last_seen: now,
    };
  } else {
    Object.assign(row, { box: newBox, due, seen: row.seen + 1, last_seen: now });
  }
  return newBox;
}

/**
 * Where a player stands on a progressive exercise: total, acquired (box 5),
 * learning (boxes 1-4), unseen, due today, next_theme (where the new words come
 * from), tested and known_at_test (how many words met were already known).
 */
export function progressStats(exercise, progress, today = localDate()) {
  const stats = { total: 0, acquired: 0, learning: 0, due: 0, tested: 0, known_at_test: 0, next_theme: "" };
  let nextFound = false;
  for (const word of leitnerWords(exercise)) {
    stats.total++;
    const row = progress[wordKey(word)];
    if (!row) {
      if (!nextFound) {
        stats.next_theme = word.theme ?? "";
        nextFound = true;
      }
      continue;
    }
    stats.tested++;
    stats.known_at_test += row.first_known;
    if (row.box === BOX_ACQUIRED) stats.acquired++;
    else if (row.box >= 1) stats.learning++;
    if (row.box >= 1 && row.due <= today) stats.due++;
  }
  stats.unseen = stats.total - stats.acquired - stats.learning;
  return stats;
}
