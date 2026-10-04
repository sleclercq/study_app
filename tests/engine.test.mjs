// Tests of web/engine.js: question builders on the real files of data/, and
// the rules of the progressive mode (same as db.py).
// Run with: node --test tests/

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import * as engine from "../web/engine.js";

const DATA = new URL("../data/", import.meta.url).pathname;

/** Every exercise file, with the rule of the build: folders starting with "_" skipped. */
function loadExercises(dir = DATA) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (name.startsWith("_")) return [];
    if (statSync(path).isDirectory()) return loadExercises(path);
    return name.endsWith(".json") ? [JSON.parse(readFileSync(path, "utf8"))] : [];
  });
}

const exercises = loadExercises();
const bySlug = (slug) => exercises.find((e) => e.slug === slug);

const BUILDERS = {
  forms: (ex) => engine.buildFormsQuestions(ex),
  triple: (ex) => engine.buildTripleQuestions(ex),
  vocab: (ex) => engine.buildVocabQuestions(ex),
  leitner: (ex) => engine.buildVocabQuestions(ex),
  sentences: (ex) => engine.buildSentenceQuestions(ex),
  accord_pp: (ex) => engine.buildAccordQuestions(ex),
};

test("fill: template, fallback, unknown placeholder", () => {
  assert.equal(engine.fill("« {source} »", "x", { source: "aimer" }), "« aimer »");
  assert.equal(engine.fill("", "Traduis {source}", { source: "le père" }), "Traduis le père");
  assert.equal(engine.fill("{oops} {source}", "x", { source: "a" }), "{oops} {source}");
});

test("every exercise of data/ gives complete questions", () => {
  assert.ok(exercises.length >= 7);
  for (const exercise of exercises) {
    const questions = BUILDERS[exercise.kind](exercise);
    assert.ok(questions.length > 0, exercise.slug);
    for (const q of questions) {
      if (q.type === "english_irregular") {
        assert.ok(q.source && q.base && q.preterit && q.past_participle, `${exercise.slug}: ${q.source}`);
      } else {
        assert.ok(q.prompt && q.answer, `${exercise.slug}: ${JSON.stringify(q)}`);
        assert.ok(!/\{\w*\}/.test(q.prompt), `${exercise.slug}: placeholder left in ${q.prompt}`);
      }
    }
  }
});

test("forms: the canonical question, then one per form", () => {
  const latin = bySlug("latin_verbs_present");
  const questions = engine.buildFormsQuestions(latin);
  assert.equal(questions.length, latin.words.length * 7);
  assert.equal(questions[0].prompt, "Comment dit-on « aimer » en latin ?");
  assert.equal(questions[0].answer, "amare");
  assert.equal(questions[1].prompt, "« aimer » - 1re pers. du singulier");
  assert.equal(questions[1].answer, "amo");
});

test("word selection: only the ticked words", () => {
  const latin = bySlug("latin_verbs_present");
  const keys = new Set([engine.wordKey(latin.words[2])]);
  const questions = engine.buildFormsQuestions(latin, keys);
  assert.equal(questions.length, 7);
  assert.ok(questions.every((q) => q.word_source === latin.words[2].source));
});

test("vocab: one way, the other, or both, with the synonyms", () => {
  const carnet = bySlug("allemand_carnet");
  const n = carnet.words.filter((w) => w.canonical).length;
  assert.equal(engine.buildVocabQuestions(carnet, null, engine.DIRECTION_FORWARD).length, n);
  assert.equal(engine.buildVocabQuestions(carnet, null, engine.DIRECTION_REVERSE).length, n);
  assert.equal(engine.buildVocabQuestions(carnet, null, engine.DIRECTION_MIXED).length, 2 * n);

  const [forward] = engine.buildVocabQuestions(carnet, null, engine.DIRECTION_FORWARD);
  assert.equal(forward.prompt, "Traduis en allemand : « le tennis »");
  assert.deepEqual(forward.accepted, ["Tennis", "das Tennis"]);
  assert.equal(forward.answer_lang, "de");
  const [reverse] = engine.buildVocabQuestions(carnet, null, engine.DIRECTION_REVERSE);
  assert.equal(reverse.answer, "le tennis");
  assert.equal(reverse.answer_lang, "fr");
});

test("triple and accord: the forms become fields and grammar", () => {
  const [be] = engine.buildTripleQuestions(bySlug("english_irregular_verbs"));
  assert.deepEqual([be.base, be.preterit, be.past_participle], ["be", "was/were", "been"]);

  const accord = engine.buildAccordQuestions(bySlug("accord_participe_passe"));
  assert.equal(accord.length, 200);
  const cases = new Set(accord.map((q) => q.case));
  assert.deepEqual([...cases].sort(), ["avec_etre", "avoir_cod_apres", "avoir_cod_avant", "sans_auxiliaire"]);
  assert.ok(accord.filter((q) => q.case === "avoir_cod_avant").every((q) => q.cod));
});

// ---------------------------------------------------------------------------
// Progressive mode
// ---------------------------------------------------------------------------

const { RESULT_FIRST: FIRST, RESULT_HINT: HINT, RESULT_MISSED: MISSED } = engine;

test("nextBox: the table of db.next_box", () => {
  const expected = {
    0: [5, 2, 1],
    1: [2, 1, 1],
    2: [3, 2, 1],
    3: [4, 2, 1],
    4: [5, 3, 1],
    5: [5, 4, 1],
  };
  for (const [box, [first, hint, missed]] of Object.entries(expected)) {
    assert.equal(engine.nextBox(Number(box), FIRST), first, `box ${box} first`);
    assert.equal(engine.nextBox(Number(box), HINT), hint, `box ${box} hint`);
    assert.equal(engine.nextBox(Number(box), MISSED), missed, `box ${box} missed`);
  }
  assert.equal(engine.resultOf(1, true), FIRST);
  assert.equal(engine.resultOf(3, true), HINT);
  assert.equal(engine.resultOf(3, false), MISSED);
});

test("dates: local day, days added across months and years", () => {
  assert.equal(engine.addDays("2026-12-31", 1), "2027-01-01");
  assert.equal(engine.addDays("2026-10-25", 60), "2026-12-24");
  const d = new Date(2026, 9, 4, 23, 30, 5);
  assert.equal(engine.localDate(d), "2026-10-04");
  assert.equal(engine.localStamp(d), "2026-10-04T23:30:05");
});

const rattrapage = bySlug("allemand_rattrapage");
const words = rattrapage.words.filter((w) => w.canonical);
const fixedRng = () => 0.5;

test("first session: 10 new words, in textbook order, asked as a test", () => {
  const questions = engine.buildProgressiveQuestions(rattrapage, {}, { today: "2026-10-04", rng: fixedRng });
  assert.equal(questions.length, engine.NEW_WORDS_FIRST_CAP);
  const firstTen = new Set(words.slice(0, 10).map(engine.wordKey));
  assert.ok(questions.every((q) => firstTen.has(q.word_key) && q.box === 0 && q.direction === engine.DIRECTION_FORWARD));
});

test("recordProgress: a new word found at once is acquired, otherwise learnt", () => {
  const progress = {};
  const at = { today: "2026-10-04", now: "2026-10-04T18:00:00" };
  const [a, b, c] = words.map(engine.wordKey);
  assert.equal(engine.recordProgress(progress, a, FIRST, at), 5);
  assert.equal(engine.recordProgress(progress, b, HINT, at), 2);
  assert.equal(engine.recordProgress(progress, c, MISSED, at), 1);
  assert.deepEqual(progress[a], { box: 5, due: "2026-12-03", seen: 1, first_known: 1, first_seen: at.now, last_seen: at.now });
  assert.equal(progress[b].due, "2026-10-05");
  assert.equal(progress[c].due, "2026-10-04");

  engine.recordProgress(progress, c, FIRST, { today: "2026-10-04", now: "2026-10-04T18:05:00" });
  assert.deepEqual(progress[c], { box: 2, due: "2026-10-05", seen: 2, first_known: 0, first_seen: at.now, last_seen: "2026-10-04T18:05:00" });
});

test("a session: due words first (weakest box first), then new ones; box 1 asked German -> French", () => {
  const progress = {};
  const stamp = (i) => `2026-10-01T10:00:${String(i).padStart(2, "0")}`;
  // 12 words met: 4 known at once (box 5, due in 60 days), 8 to learn (box 1, due now).
  words.slice(0, 12).forEach((w, i) => {
    engine.recordProgress(progress, engine.wordKey(w), i < 4 ? FIRST : MISSED, { today: "2026-10-01", now: stamp(i) });
  });
  const questions = engine.buildProgressiveQuestions(rattrapage, progress, { today: "2026-10-04", rng: fixedRng });
  const due = questions.filter((q) => q.box === 1);
  const fresh = questions.filter((q) => q.box === 0);
  assert.equal(due.length, 8);
  assert.ok(due.every((q) => q.direction === engine.DIRECTION_REVERSE));
  // 12 words met, 4 known: cap = 8 + round(12 * 4/12) = 12 new words.
  assert.equal(fresh.length, 12);
  assert.ok(fresh.every((q) => q.direction === engine.DIRECTION_FORWARD));
  assert.equal(questions.length, 20);
});

test("the pace of new words rounds like Python (halves to even)", () => {
  const progress = {};
  // 16 words met, 6 known at once: 12 * 6/16 = 4.5 -> 4 (Python) -> cap 12.
  words.slice(0, 16).forEach((w, i) => {
    engine.recordProgress(progress, engine.wordKey(w), i < 6 ? FIRST : HINT, {
      today: "2026-10-01", now: `2026-10-01T10:00:${String(i).padStart(2, "0")}`,
    });
  });
  assert.equal(engine.newWordCap(rattrapage, progress), 12);
  assert.equal(engine.roundHalfEven(4.5), 4);
  assert.equal(engine.roundHalfEven(5.5), 6);
  assert.equal(engine.roundHalfEven(4.4), 4);
});

test("progressStats: acquired, learning, unseen, due, next theme", () => {
  const progress = {};
  words.slice(0, 3).forEach((w, i) => {
    engine.recordProgress(progress, engine.wordKey(w), [FIRST, HINT, MISSED][i], { today: "2026-10-04", now: "2026-10-04T18:00:00" });
  });
  const stats = engine.progressStats(rattrapage, progress, "2026-10-04");
  assert.equal(stats.total, words.length);
  assert.equal(stats.acquired, 1);
  assert.equal(stats.learning, 2);
  assert.equal(stats.unseen, words.length - 3);
  assert.equal(stats.due, 1);              // the missed one comes back today
  assert.equal(stats.tested, 3);
  assert.equal(stats.known_at_test, 1);
  assert.equal(stats.next_theme, words[3].theme);
});

test("nothing due and every word met: no session", () => {
  const tiny = { ...rattrapage, words: words.slice(0, 3) };
  const progress = {};
  for (const w of tiny.words) engine.recordProgress(progress, engine.wordKey(w), FIRST, { today: "2026-10-04", now: "2026-10-04T18:00:00" });
  assert.deepEqual(engine.buildProgressiveQuestions(tiny, progress, { today: "2026-10-05" }), []);
});
