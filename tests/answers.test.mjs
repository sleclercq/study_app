// Tests of web/answers.js: the tolerance rules written on screen for the child.
// Run with: node --test tests/

import { test } from "node:test";
import assert from "node:assert/strict";
import { hintPrefix, keysFor, matches, normalize } from "../web/answers.js";

test("normalize: case, outer punctuation, inner spaces, ligatures", () => {
  assert.equal(normalize("  Der   Tisch. "), "der tisch");
  assert.equal(normalize("« l’œil »"), "l'oeil");
  assert.equal(normalize("Wie …?"), "wie");
  assert.equal(normalize("!!!"), "");
});

test("strict comparison when the exercise has no language code", () => {
  assert.ok(matches("Amare", "amare"));
  assert.ok(matches(" was/were ", "was/were"));
  assert.ok(!matches("amáre", "amare"));          // no accent tolerance
  assert.ok(!matches("", "amare"));
});

test("German: umlauts may be typed ae oe ue ss", () => {
  assert.ok(matches("fuer", "für", "de"));
  assert.ok(matches("Fussball", "Fußball", "de"));
  assert.ok(matches("die Maedchen", "die Mädchen", "de"));
  assert.ok(!matches("fur", "für", "de"));
});

test("German: the article is part of the answer", () => {
  assert.ok(matches("der Tisch", "der Tisch", "de"));
  assert.ok(!matches("Tisch", "der Tisch", "de"));
  assert.ok(!matches("die Tisch", "der Tisch", "de"));
});

test("French: accents and leading article optional", () => {
  assert.ok(matches("fenetre", "la fenêtre", "fr"));
  assert.ok(matches("la fenetre", "la fenêtre", "fr"));
  assert.ok(matches("ecole", "l'école", "fr"));
  assert.ok(matches("eau", "de l'eau", "fr"));
  assert.ok(!matches("porte", "la fenêtre", "fr"));
});

test("a parenthesis of the expected answer is never required", () => {
  assert.ok(matches("la fille", "la fille (de quelqu'un)", "fr"));
  assert.ok(matches("fille", "la fille (de quelqu'un)", "fr"));
  assert.ok(matches("la fille (de quelqu'un)", "la fille (de quelqu'un)", "fr"));
});

test("synonyms of the JSON seed are accepted", () => {
  assert.ok(matches("das Tennis", ["Tennis", "das Tennis"], "de"));
  assert.ok(matches("le papa", ["le père", "le papa"], "fr"));
});

test("keysFor never contains an empty key", () => {
  assert.ok(!keysFor("(rien)", "fr").has(""));
});

test("hints: 2 letters, then 4 (or len - 1), never the German article", () => {
  assert.equal(hintPrefix("amare", 1), "am");
  assert.equal(hintPrefix("amare", 2), "amar");
  assert.equal(hintPrefix("sum", 2), "su");
  assert.equal(hintPrefix("der Tisch", 1, "de"), "Ti");
  assert.equal(hintPrefix("der Tisch", 2, "de"), "Tisc");
  assert.equal(hintPrefix("der Bus", 2, "de"), "Bu");
  assert.equal(hintPrefix("die Mannschaft", 2, "de"), "Mann");
  assert.equal(hintPrefix("la fenêtre", 1, "fr"), "la");
  assert.equal(hintPrefix("a", 2), "a");
});
