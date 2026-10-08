/*
 * app.js - The screens of the site and the navigation between them.
 *
 * Same flow as the desktop app (main.py), adapted to a phone:
 *
 *   players -> menu -+-> selection -+-> quiz / triple       -> results
 *                    |              +-> direction -> quiz   -> results
 *                    +-> mode -+-> quiz (progressive)       -> results
 *                    |         +-> selection (free, as above)
 *                    +-> quiz / accord                      -> results
 *
 * Which path an exercise takes is decided by its `kind` (KINDS below), read
 * from its JSON file in data/. Nothing about a given exercise is hardcoded here.
 *
 * The answer flow and the scoring are those of the desktop app (see CLAUDE.md,
 * "Core rules"): 3 attempts, hints after each miss, 1 / 0.5 / 0.25 points.
 * Players, scores and progress are kept on the device by store.js.
 */

import * as answers from "./answers.js";
import * as engine from "./engine.js";
import * as store from "./store.js";

// School year being revised right now. Its exercises open the menu; previous
// years are grouped underneath as "Révisions". Bump this every September.
const CURRENT_LEVEL = "4e";

const KINDS = {
  // French -> Latin infinitive + conjugated forms, one answer field.
  forms: { select: true, direction: false, screen: "quiz", build: (ex, keys) => engine.buildFormsQuestions(ex, keys) },
  // English irregular verbs: three fields at once.
  triple: { select: true, direction: false, screen: "triple", build: (ex, keys) => engine.buildTripleQuestions(ex, keys) },
  // Vocabulary list, translated either way.
  vocab: { select: true, direction: true, screen: "quiz", build: (ex, keys, d) => engine.buildVocabQuestions(ex, keys, d) },
  // Big catch-up list: free practice like "vocab", plus the progressive session.
  leitner: { select: true, direction: true, progressive: true, screen: "quiz", build: (ex, keys, d) => engine.buildVocabQuestions(ex, keys, d) },
  // A bank of sentences with a blank: no selection, random draw.
  sentences: { select: false, direction: false, screen: "quiz", build: (ex) => engine.buildSentenceQuestions(ex) },
  // Accord du participe passé: its own screen (tap the COD, then answer).
  accord_pp: { select: false, direction: false, screen: "accord", build: (ex) => engine.buildAccordQuestions(ex) },
};

const kindSpec = (exercise) => KINDS[exercise.kind] ?? KINDS.forms;

// What counts as a correct answer, written for the child in the language of the
// expected answer. Must follow every change of tolerance in answers.js.
// A line common to both languages is shown once when both are listed.
const HYPHEN_RULE = "Les tirets ne comptent pas : jeux-vidéo = jeux vidéo, T-Shirt = TShirt.";
const ANSWER_RULES = {
  de: [
    "ä ö ü ß : tu peux taper ae oe ue ss (für = fuer, mais fur est faux).",
    "L'article fait partie de la réponse : der Tisch, pas Tisch.",
    HYPHEN_RULE,
  ],
  fr: [
    "Les accents ne sont pas obligatoires (fenetre = fenêtre), l'article non plus (fenêtre = la fenêtre).",
    HYPHEN_RULE,
  ],
};

const HOW_IT_WORKS = [
  "Chaque séance reprend les mots à revoir aujourd'hui, puis ajoute des mots nouveaux dans l'ordre du manuel : plus tu en connais, plus il en arrive.",
  "Un mot nouveau est un petit test, en allemand. Trouvé du premier coup : il est acquis, tu ne le reverras que dans 2 mois pour vérifier.",
  "Pas trouvé : tu l'apprends, d'abord dans le sens allemand → français, puis dans l'autre, de plus en plus espacé (le lendemain, 3 jours, 7 jours).",
  "Trouvé grâce à l'indice : il recule d'une case. Raté : il repart au début.",
];

const CASE_LABELS = {
  sans_auxiliaire: "Cas : sans auxiliaire. Le participe passé s'accorde comme un adjectif avec le nom qu'il qualifie.",
  avec_etre: "Cas : auxiliaire ÊTRE. Le participe passé s'accorde toujours avec le sujet.",
  avoir_cod_apres: "Cas : auxiliaire AVOIR, le COD est placé après le verbe : pas d'accord.",
  avoir_cod_avant: "Cas : auxiliaire AVOIR, le COD est placé avant le verbe : le participe passé s'accorde avec le COD.",
};

const RESULT_MESSAGES = [
  [100, "Parfait !"],
  [90, "Excellent travail !"],
  [75, "Très bien !"],
  [60, "Bien, continue comme ça !"],
  [40, "Pas mal, mais on peut faire mieux !"],
  [0, "Courage, tu vas progresser !"],
];

// Shared state, the equivalent of app_state in main.py.
const state = {
  exercises: [],
  player: null,
  exercise: null,
  enabledKeys: null,          // Set of word keys, null = every word
  direction: engine.DIRECTION_MIXED,
  mode: "free",               // "free" or "progressive"
  questions: [],
  progressBefore: null,
  lastScore: 0,
  lastTotal: 0,
};

const root = document.getElementById("app");
const finePointer = window.matchMedia("(pointer: fine)").matches;

// ---------------------------------------------------------------------------
// Small DOM helpers
// ---------------------------------------------------------------------------

const PROPS = new Set(["checked", "disabled", "value", "hidden", "open", "readOnly", "indeterminate"]);

/** h("button", {class: "btn", onclick: fn}, "Texte") - text is always inserted as text. */
function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "style") for (const [k, v] of Object.entries(value)) el.style.setProperty(k, v);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (PROPS.has(key)) el[key] = value;
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

// Text fields where the child types an answer: no autocorrect, no capital
// letter added by the phone, no suggestions. 18px avoids the zoom of iOS.
const ANSWER_FIELD = {
  type: "text", autocomplete: "off", autocorrect: "off", autocapitalize: "off",
  spellcheck: "false", enterkeyhint: "go",
};

/** 17.5 -> "17,5", 13.3333 -> "13,33", 20 -> "20". */
function formatScore(score) {
  return score.toFixed(2).replace(/0+$/, "").replace(/\.$/, "").replace(".", ",");
}

function toast(message) {
  document.querySelector(".toast")?.remove();
  const el = h("div", { class: "toast", role: "status" }, message);
  document.body.append(el);
  setTimeout(() => el.classList.add("leaving"), 4000);
  setTimeout(() => el.remove(), 4500);
}

// ---------------------------------------------------------------------------
// Screen switching, and the phone's back gesture
// ---------------------------------------------------------------------------
//
// The back button / swipe of the phone does what the "Retour" of the current
// screen does, instead of leaving the site. One spare history entry is kept
// for that ("back trap"); on the first screen there is none, so back leaves.

let screenId = 0;
let backAction = null;
let leaveScreen = null;
let trapArmed = false;
let ignoreNextPop = false;

function show(node, { back = null, onLeave = null } = {}) {
  if (leaveScreen) leaveScreen();
  leaveScreen = onLeave;
  backAction = back;
  screenId++;
  root.replaceChildren(node);
  window.scrollTo(0, 0);
  if (back && !trapArmed) {
    history.pushState({ revisions: true }, "");
    trapArmed = true;
  } else if (!back && trapArmed) {
    // First screen reached through a button: drop the spare entry, so that
    // the next back gesture leaves the site instead of doing nothing.
    trapArmed = false;
    ignoreNextPop = true;
    history.back();
  }
}

window.addEventListener("popstate", () => {
  trapArmed = false;
  if (ignoreNextPop) {
    ignoreNextPop = false;
    return;
  }
  if (!backAction) return;
  const before = screenId;
  backAction();
  if (screenId === before && backAction) {   // stayed (e.g. "keep playing"): re-arm
    history.pushState({ revisions: true }, "");
    trapArmed = true;
  }
});

function topBar({ title, back, right }) {
  return h("header", { class: "topbar" },
    back
      ? h("button", { class: "icon-btn", type: "button", "aria-label": "Retour", onclick: back }, "←")
      : h("span", { class: "icon-spacer" }),
    h("h1", { class: "topbar-title" }, title),
    right ?? h("span", { class: "icon-spacer" }));
}

function rulesBox(langs, { title = null } = {}) {
  const lines = [...new Set(langs.flatMap((lang) => ANSWER_RULES[lang] ?? []))];
  if (!lines.length) return null;
  return h("div", { class: "rules" },
    title ? h("p", { class: "rules-title" }, title) : null,
    lines.map((line) => h("p", {}, line)));
}

// ---------------------------------------------------------------------------
// Banners: storage refused, and how to put the site on the home screen
// ---------------------------------------------------------------------------

let installPrompt = null;
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPrompt = event;
  document.querySelectorAll(".install-slot").forEach((slot) => slot.replaceChildren(installHint()));
});

const isStandalone = () =>
  window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;

const isIOS = () =>
  /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

function installHint() {
  if (isStandalone() || !window.matchMedia("(pointer: coarse)").matches) return "";
  try {
    if (localStorage.getItem("revisions.install_hint") === "masqué") return "";
  } catch { /* storage refused: show it */ }

  const hide = () => {
    try { localStorage.setItem("revisions.install_hint", "masqué"); } catch { /* ignore */ }
    document.querySelectorAll(".install-slot").forEach((slot) => slot.replaceChildren());
  };
  let body;
  if (installPrompt) {
    body = [h("p", {}, "Installe Révisions sur ton téléphone pour l'ouvrir comme une appli."),
      h("button", {
        class: "btn primary small", type: "button",
        onclick: async () => {
          installPrompt.prompt();
          await installPrompt.userChoice.catch(() => null);
          installPrompt = null;
          hide();
        },
      }, "Installer l'appli")];
  } else if (isIOS()) {
    body = [h("p", {}, "Pour l'ouvrir comme une appli : bouton Partager ", h("span", { class: "share-icon", "aria-hidden": "true" }, "⬆︎"),
      " puis « Sur l'écran d'accueil ». Fais-le avant de commencer, pour que ta progression soit dans l'appli.")];
  } else {
    body = [h("p", {}, "Pour l'ouvrir comme une appli : menu du navigateur, puis « Ajouter à l'écran d'accueil ». Fais-le avant de commencer, pour que ta progression soit dans l'appli.")];
  }
  return h("div", { class: "banner" }, body,
    h("button", { class: "link", type: "button", onclick: hide }, "Masquer"));
}

function banners() {
  return [
    store.isPersistent() ? null : h("div", { class: "banner warning" },
      h("p", {}, "Ce navigateur ne garde pas la progression (navigation privée ?). Les scores de cette visite seront perdus.")),
    h("div", { class: "install-slot" }, installHint()),
  ];
}

// ---------------------------------------------------------------------------
// Players
// ---------------------------------------------------------------------------

function choosePlayer(name) {
  state.player = name;
  store.setLastPlayer(name);
  showMenu();
}

function showPlayers() {
  const players = store.listPlayers();
  const nameInput = h("input", {
    type: "text", class: "text-field", placeholder: "Ton prénom", maxlength: "30",
    autocomplete: "off", autocorrect: "off", autocapitalize: "words", spellcheck: "false",
    enterkeyhint: "go", "aria-label": "Prénom du nouveau joueur",
  });
  const form = h("form", {
    class: "inline-form",
    onsubmit: (event) => {
      event.preventDefault();
      const name = store.addPlayer(nameInput.value);
      if (name) choosePlayer(name);
    },
  }, nameInput, h("button", { class: "btn", type: "submit" }, "Ajouter"));

  show(h("div", { class: "screen" },
    h("div", { class: "hero" },
      h("img", { src: "icons/icon.svg", alt: "", class: "hero-icon", width: "64", height: "64" }),
      h("h1", { class: "hero-title" }, "Révisions")),
    banners(),
    players.length
      ? [h("p", { class: "lead" }, "Qui révise ?"),
        h("div", { class: "player-list" },
          players.map((name) => h("button", { class: "player", type: "button", onclick: () => choosePlayer(name) }, name))),
        h("p", { class: "label" }, "Nouveau joueur")]
      : h("p", { class: "lead" }, "Pour commencer, écris ton prénom :"),
    form,
    backupPanel()));
}

// ---------------------------------------------------------------------------
// Backup: the progress lives on the device, this moves it elsewhere
// ---------------------------------------------------------------------------

function backupPanel() {
  const fileInput = h("input", { type: "file", accept: "application/json,.json", class: "visually-hidden", onchange: importBackup });
  return h("details", { class: "backup" },
    h("summary", {}, "Sauvegarde de la progression"),
    h("p", {}, "Les scores et la progression restent sur cet appareil. Pour les copier sur un autre appareil, ou en garder une copie : « Exporter » ici, puis « Importer » là-bas."),
    h("div", { class: "button-row" },
      h("button", { class: "btn secondary", type: "button", onclick: exportBackup }, "Exporter"),
      h("label", { class: "btn secondary" }, "Importer", fileInput)));
}

async function exportBackup() {
  const file = new File([JSON.stringify(store.exportAll())],
    `revisions-sauvegarde-${engine.localDate()}.json`, { type: "application/json" });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: "Sauvegarde Révisions" });
      return;
    } catch (error) {
      if (error.name === "AbortError") return;
    }
  }
  const url = URL.createObjectURL(file);
  const link = h("a", { href: url, download: file.name, hidden: true });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

async function importBackup(event) {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  let data;
  let names;
  try {
    data = JSON.parse(await file.text());
    names = store.backupPlayers(data);
  } catch {
    toast("Ce fichier n'est pas une sauvegarde de Révisions.");
    return;
  }
  if (!names.length) {
    toast("Cette sauvegarde est vide.");
    return;
  }
  if (!window.confirm(`Remplacer la progression de ${names.join(", ")} sur cet appareil ?`)) return;
  store.importAll(data);
  toast(`Progression importée : ${names.join(", ")}.`);
  showPlayers();
}

// ---------------------------------------------------------------------------
// Menu
// ---------------------------------------------------------------------------

function levelSortKey(level) {
  if (level === CURRENT_LEVEL) return [0, ""];
  if (!level) return [2, ""];
  return [1, level];               // "4e" < "5e" < "6e" = most recent first
}

function levelHeading(level) {
  if (!level) return "Autres exercices";
  return level === CURRENT_LEVEL ? `Programme de ${level}` : `Révisions de ${level}`;
}

function exerciseBadge(exercise, doc) {
  if (kindSpec(exercise).progressive) {
    const stats = engine.progressStats(exercise, doc.progress[exercise.slug] ?? {});
    if (!stats.tested) return `${stats.total} mots`;
    return `${stats.acquired} acquis sur ${stats.total}` + (stats.due ? ` · ${stats.due} à revoir` : "");
  }
  const last = doc.sessions.filter((s) => s.slug === exercise.slug).at(-1);
  return last ? `Dernière série : ${formatScore(last.score)} / ${last.total}` : "";
}

function showMenu() {
  const doc = store.loadPlayer(state.player);
  const byLevel = new Map();
  for (const exercise of state.exercises) {
    const level = exercise.level ?? "";
    if (!byLevel.has(level)) byLevel.set(level, []);
    byLevel.get(level).push(exercise);
  }
  const levels = [...byLevel.keys()].sort((a, b) => {
    const [ka, kb] = [levelSortKey(a), levelSortKey(b)];
    return ka[0] - kb[0] || ka[1].localeCompare(kb[1]);
  });

  const sections = levels.map((level) => {
    const current = level === CURRENT_LEVEL;
    return h("section", { class: "menu-section" },
      h("h2", { class: "section-title" }, levelHeading(level)),
      byLevel.get(level).map((exercise) => {
        const [title, ...rest] = (exercise.button_label || exercise.name).split("\n");
        const badge = exerciseBadge(exercise, doc);
        return h("button", {
          class: `exercise ${current ? "current" : "compact"}`, type: "button",
          style: { "--accent": exercise.color || "#4a7c59" },
          onclick: () => openExercise(exercise),
        },
        h("span", { class: "exercise-title" }, current ? title : [title, ...rest].join(" ")),
        current && rest.length ? h("span", { class: "exercise-sub" }, rest.join(" ")) : null,
        badge ? h("span", { class: "exercise-badge" }, badge) : null);
      }));
  });

  show(h("div", { class: "screen" },
    h("header", { class: "menu-head" },
      h("h1", { class: "menu-title" }, `Bonjour ${state.player} !`),
      h("button", { class: "link", type: "button", onclick: showPlayers }, "Changer de joueur")),
    banners(),
    state.exercises.length
      ? [h("p", { class: "lead" }, "Quel exercice ?"), sections]
      : h("p", { class: "error" }, "Aucun exercice. Vérifie les fichiers data/.")),
  { back: showPlayers });
}

function openExercise(exercise) {
  state.exercise = exercise;
  state.enabledKeys = null;
  const spec = kindSpec(exercise);
  if (spec.progressive) showMode();
  else if (spec.select) showSelection();
  else startSession(engine.DIRECTION_MIXED);
}

// ---------------------------------------------------------------------------
// Starting a series
// ---------------------------------------------------------------------------

/** Draw up to 20 questions and open the right screen (menu, selection, direction, replay). */
function startSession(direction) {
  const exercise = state.exercise;
  const spec = kindSpec(exercise);
  const questions = spec.build(exercise, state.enabledKeys, direction);
  if (!questions.length) {
    toast("Aucune question pour cette sélection. Coche au moins un mot.");
    return;
  }
  engine.shuffle(questions);
  state.questions = questions.slice(0, engine.SESSION_LENGTH);
  state.direction = direction;
  state.mode = "free";
  openQuiz(spec.screen);
}

/** Today's progressive series: the words due, topped up with new ones. */
function startProgressiveSession() {
  const exercise = state.exercise;
  const progress = store.loadPlayer(state.player).progress[exercise.slug] ?? {};
  const questions = engine.buildProgressiveQuestions(exercise, progress);
  if (!questions.length) {
    toast("Rien pour aujourd'hui : tous les mots ont été présentés et aucun n'est à revoir. Reviens demain !");
    return;
  }
  state.questions = questions;
  state.mode = "progressive";
  state.progressBefore = engine.progressStats(exercise, progress);
  openQuiz("quiz");
}

function openQuiz(screen) {
  if (screen === "triple") showTripleQuiz();
  else if (screen === "accord") showAccordQuiz();
  else showQuiz();
}

/** Where "Arrêter" leads: the screen the series was started from. */
function leaveSeries() {
  if (state.mode === "progressive") showMode();
  else showMenu();
}

function confirmLeave() {
  if (window.confirm("Arrêter cette série ? Elle ne sera pas comptée.")) leaveSeries();
}

function saveSession(score, total) {
  const slug = state.exercise.slug;
  store.updatePlayer(state.player, (doc) => {
    doc.sessions.push({ slug, played_at: new Date().toISOString(), score, total });
  });
  state.lastScore = score;
  state.lastTotal = total;
  store.requestPersistence();
}

function quizBar(context, counter) {
  return h("header", { class: "quiz-bar" },
    h("button", { class: "icon-btn", type: "button", "aria-label": "Arrêter la série", onclick: confirmLeave }, "✕"),
    h("span", { class: "quiz-context" }, context),
    counter);
}

function progressLine() {
  const fill = h("span", { class: "quiz-progress-fill" });
  return [h("div", { class: "quiz-progress", "aria-hidden": "true" }, fill), fill];
}

/** "Lou · Français → Allemand" for a one-way vocabulary series. */
function quizContext() {
  const exercise = state.exercise;
  let suffix = "";
  if (state.mode === "progressive") {
    suffix = " · séance progressive";
  } else if (kindSpec(exercise).direction) {
    const source = exercise.source_language ?? "";
    const target = exercise.target_language ?? "";
    suffix = state.direction === engine.DIRECTION_FORWARD ? ` · ${source} → ${target}`
      : state.direction === engine.DIRECTION_REVERSE ? ` · ${target} → ${source}`
        : " · les deux sens";
  }
  return `${state.player}${suffix}`;
}

// ---------------------------------------------------------------------------
// Mode (progressive exercises only)
// ---------------------------------------------------------------------------

function showMode() {
  const exercise = state.exercise;
  const stats = engine.progressStats(exercise, store.loadPlayer(state.player).progress[exercise.slug] ?? {});
  const total = stats.total || 1;
  const parts = [];
  if (stats.tested >= 20) parts.push(`${engine.roundHalfEven((100 * stats.known_at_test) / stats.tested)} % des mots testés étaient déjà sus`);
  if (stats.due) parts.push(`${stats.due} mot${stats.due > 1 ? "s" : ""} à revoir aujourd'hui`);
  if (stats.next_theme) parts.push(`prochains mots nouveaux : ${stats.next_theme}`);

  show(h("div", { class: "screen" },
    topBar({ title: exercise.name, back: showMenu }),
    h("div", { class: "stats" },
      [["acquired", stats.acquired, "acquis"], ["learning", stats.learning, "en cours"], ["unseen", stats.unseen, "à découvrir"]]
        .map(([kind, value, label]) => h("div", { class: `stat ${kind}` },
          h("span", { class: "stat-value" }, value), h("span", { class: "stat-label" }, label)))),
    h("div", { class: "bar", role: "img", "aria-label": `${stats.acquired} acquis, ${stats.learning} en cours, ${stats.unseen} à découvrir` },
      h("span", { class: "bar-acquired", style: { width: `${(100 * stats.acquired) / total}%` } }),
      h("span", { class: "bar-learning", style: { width: `${(100 * stats.learning) / total}%` } })),
    h("ul", { class: "stats-notes" },
      parts.length ? parts.map((part) => h("li", {}, part)) : h("li", {}, "Tous les mots ont été présentés.")),
    h("button", { class: "btn primary big", type: "button", onclick: startProgressiveSession }, "Séance du jour ▶"),
    h("p", { class: "under-button" }, "L'appli choisit les mots : ceux à revoir, puis des nouveaux."),
    h("button", { class: "btn secondary", type: "button", onclick: showSelection }, "Réviser des unités au choix"),
    h("div", { class: "explain" },
      h("p", { class: "explain-title" }, "Comment ça marche"),
      HOW_IT_WORKS.map((text) => h("p", {}, text)))),
  { back: showMenu });
}

// ---------------------------------------------------------------------------
// Word selection (per player, remembered)
// ---------------------------------------------------------------------------

function showSelection() {
  const exercise = state.exercise;
  const spec = kindSpec(exercise);
  const unticked = store.loadPlayer(state.player).prefs[exercise.slug] ?? {};
  const back = spec.progressive ? showMode : showMenu;
  const checks = new Map();          // word key -> checkbox
  const themes = [];                 // {box, keys, count}

  const counter = h("span", { class: "selection-count" });
  const startButton = h("button", { class: "btn primary", type: "button", onclick: begin }, "Commencer ▶");

  function refresh() {
    for (const theme of themes) {
      const ticked = theme.keys.filter((key) => checks.get(key).checked).length;
      theme.box.checked = ticked === theme.keys.length;
      theme.box.indeterminate = ticked > 0 && ticked < theme.keys.length;
      theme.count.textContent = `${ticked}/${theme.keys.length}`;
    }
    const ticked = [...checks.values()].filter((box) => box.checked).length;
    counter.textContent = `${ticked} / ${checks.size} sélectionnés`;
    startButton.disabled = ticked === 0;
  }

  function wordCheckbox(word) {
    const key = engine.wordKey(word);
    const box = h("input", { type: "checkbox", checked: unticked[key] !== false, onchange: refresh });
    checks.set(key, box);
    return h("label", { class: "word" }, box, h("span", {}, word.source));
  }

  // Group in file order; "" is the single group of an exercise without themes.
  const groups = [];
  for (const word of exercise.words) {
    const theme = word.theme ?? "";
    if (!groups.length || groups.at(-1).theme !== theme) groups.push({ theme, words: [] });
    groups.at(-1).words.push(word);
  }
  const openThemes = exercise.words.length <= 100;
  const list = groups.map(({ theme, words }) => {
    const grid = h("div", { class: "word-grid" }, words.map(wordCheckbox));
    if (!theme) return grid;
    const keys = words.map(engine.wordKey);
    const box = h("input", {
      type: "checkbox", "aria-label": `Tout le thème ${theme}`,
      onchange: () => {
        for (const key of keys) checks.get(key).checked = box.checked;
        refresh();
      },
    });
    const count = h("span", { class: "theme-count" });
    themes.push({ box, keys, count });
    return h("details", { class: "theme", open: openThemes },
      h("summary", {}, box, h("span", { class: "theme-name" }, theme), count), grid);
  });

  function setAll(value) {
    for (const box of checks.values()) box.checked = value;
    refresh();
  }

  function begin() {
    const keys = [...checks].filter(([, box]) => box.checked).map(([key]) => key);
    store.updatePlayer(state.player, (doc) => {
      doc.prefs[exercise.slug] = Object.fromEntries(
        [...checks].filter(([, box]) => !box.checked).map(([key]) => [key, false]));
    });
    state.enabledKeys = new Set(keys);
    if (spec.direction) showDirection();
    else startSession(engine.DIRECTION_MIXED);
  }

  refresh();
  show(h("div", { class: "screen with-footer" },
    topBar({ title: spec.direction ? "Choisir les mots à réviser" : "Choisir les verbes à réviser", back }),
    h("div", { class: "button-row" },
      h("button", { class: "btn secondary small", type: "button", onclick: () => setAll(true) }, "Tout cocher"),
      h("button", { class: "btn secondary small", type: "button", onclick: () => setAll(false) }, "Tout décocher")),
    themes.length && !openThemes ? h("p", { class: "hint-text" }, "Touche le nom d'une unité pour voir ses mots, la case pour la cocher en entier.") : null,
    h("div", { class: "selection" }, list),
    h("footer", { class: "sticky-footer" }, counter, startButton)),
  { back });
}

// ---------------------------------------------------------------------------
// Direction (vocabulary only)
// ---------------------------------------------------------------------------

function showDirection() {
  const exercise = state.exercise;
  const source = exercise.source_language || "Français";
  const target = exercise.target_language || "Langue étrangère";
  const selected = state.enabledKeys ? state.enabledKeys.size : 0;
  const choices = [
    [engine.DIRECTION_FORWARD, `${source} → ${target}`, "#8a6a2a"],
    [engine.DIRECTION_REVERSE, `${target} → ${source}`, "#4a6a9c"],
    [engine.DIRECTION_MIXED, "Les deux mélangés", "#4a7c59"],
  ];
  show(h("div", { class: "screen" },
    topBar({ title: "Dans quel sens ?", back: showSelection }),
    h("p", { class: "lead center" }, `${selected} mot${selected > 1 ? "s" : ""} sélectionné${selected > 1 ? "s" : ""}`),
    choices.map(([direction, label, color]) => h("button", {
      class: "btn big colored", type: "button", style: { "--accent": color },
      onclick: () => startSession(direction),
    }, label)),
    // Both directions are reachable from here, so both sets of rules are shown.
    rulesBox([exercise.target_lang_code, exercise.source_lang_code], { title: "Comment écrire tes réponses" })),
  { back: showSelection });
}

// ---------------------------------------------------------------------------
// Quiz: one answer field (forms, vocabulary, sentences, progressive)
// ---------------------------------------------------------------------------
//
//   Up to 3 attempts. Wrong: red, the field is NOT cleared, a hint appears
//   (2 letters, then 4). After 3 misses the answer is revealed in blue.
//   1 point at the first attempt, 0.5 at the second, 0.25 at the third.
//   Enter / Space / button to continue after the feedback.
//
// On a phone the keyboard stays open from one question to the next: the
// keyboard's Enter key validates, then continues.

function showQuiz() {
  const questions = state.questions;
  let index = 0;
  let attempts = 0;
  let score = 0;
  let answered = false;

  const counter = h("span", { class: "quiz-counter" });
  const [progress, progressFill] = progressLine();
  const prompt = h("p", { class: "prompt" });
  const input = h("input", { ...ANSWER_FIELD, class: "answer", "aria-label": "Ta réponse" });
  const submit = h("button", { class: "btn", type: "submit" }, "Valider");
  const feedback = h("p", { class: "feedback", role: "status" });
  const hint = h("p", { class: "hint" });
  const next = h("button", { class: "btn primary continue", type: "button", hidden: true, onclick: goNext }, "Continuer →");
  const rules = h("div", { class: "rules-slot" });

  const form = h("form", {
    class: "answer-row",
    onsubmit: (event) => {
      event.preventDefault();
      if (answered) goNext();
      else check();
    },
  }, input, submit);

  // Enter validates, then continues. Once answered, the field is frozen but
  // keeps the focus, so the phone keyboard stays open for the next question.
  input.addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    if (event.key === "Enter") {
      event.preventDefault();
      if (answered) goNext();
      else check();
    } else if (answered && event.key === " ") {
      event.preventDefault();
      goNext();
    }
  });
  // Android keyboards do not name their keys: the typed text is what arrives.
  input.addEventListener("beforeinput", (event) => {
    if (!answered || event.inputType === "insertLineBreak") return;
    event.preventDefault();
    if (event.data === " ") goNext();
  });

  function load() {
    attempts = 0;
    answered = false;
    const q = questions[index];
    counter.textContent = `${index + 1} / ${questions.length}`;
    progressFill.style.width = `${(100 * index) / questions.length}%`;
    prompt.textContent = q.prompt;
    feedback.textContent = "";
    feedback.className = "feedback";
    hint.textContent = "";
    hint.className = "hint";
    // In a mixed series the language changes from one question to the next.
    rules.replaceChildren(rulesBox([q.answer_lang ?? ""]) ?? "");
    input.value = "";
    input.lang = q.answer_lang || "";
    input.className = "answer";
    submit.disabled = false;
    next.hidden = true;
    input.focus();
  }

  function check() {
    if (answered) return;
    const q = questions[index];
    const expected = q.answer.trim();
    // Vocabulary questions carry every accepted answer and the language of the
    // expected one; the others keep the strict comparison (see answers.js).
    const accepted = q.accepted?.length ? q.accepted : [expected];
    const lang = q.answer_lang ?? "";
    attempts++;

    if (answers.matches(input.value, accepted, lang)) {
      const [points, message] = attempts === 1 ? [1, "Excellent !"]
        : attempts === 2 ? [0.5, "Bien rattrapé !"] : [0.25, "Bien joué !"];
      score += points;
      record(q, engine.resultOf(attempts, true));
      feedback.textContent = `✓  ${message}`;
      feedback.className = "feedback right";
      hint.textContent = "";
      input.className = "answer right";
      finish();
    } else if (attempts >= 3) {
      record(q, engine.resultOf(attempts, false));
      feedback.textContent = "✗  Pas cette fois…";
      feedback.className = "feedback wrong";
      hint.textContent = `La bonne réponse était : ${expected}`;
      hint.className = "hint reveal";
      input.className = "answer wrong";
      finish();
    } else {
      const remaining = 3 - attempts;
      feedback.textContent = `✗  Pas tout à fait… encore ${remaining} ${remaining === 1 ? "essai" : "essais"}.`;
      feedback.className = "feedback wrong";
      hint.textContent = `Indice : ${answers.hintPrefix(expected, attempts, lang)}…`;
      hint.className = "hint";
      input.className = "answer wrong";
      input.focus();
      if (finePointer) input.select();
    }
  }

  /** Progressive mode only: file the outcome, the word moves to its next box. */
  function record(q, result) {
    if (!q.progressive) return;
    const slug = state.exercise.slug;
    store.updatePlayer(state.player, (doc) => {
      doc.progress[slug] ??= {};
      engine.recordProgress(doc.progress[slug], q.word_key, result);
    });
  }

  function finish() {
    answered = true;
    submit.disabled = true;
    next.hidden = false;
    progressFill.style.width = `${(100 * (index + 1)) / questions.length}%`;
  }

  function goNext() {
    if (!answered) return;
    index++;
    if (index >= questions.length) {
      saveSession(score, questions.length);
      showResults();
    } else {
      load();
    }
  }

  // Enter / Space anywhere on the page (desktop), as the Tk version did.
  const onKey = (event) => {
    if (event.target === input || event.target.closest?.("button")) return;
    if (event.key === "Enter" || (event.key === " " && answered)) {
      event.preventDefault();
      if (answered) goNext();
      else check();
    }
  };
  document.addEventListener("keydown", onKey);

  show(h("div", { class: "screen quiz" },
    quizBar(quizContext(), counter),
    progress,
    prompt,
    form,
    feedback,
    hint,
    next,
    rules),
  { back: confirmLeave, onLeave: () => document.removeEventListener("keydown", onKey) });
  load();
}

// ---------------------------------------------------------------------------
// Quiz: English irregular verbs, three fields at once
// ---------------------------------------------------------------------------
//
//   Each field is scored on its own (1 / 0.5 / 0.25 at the attempt where the
//   child gets it right, 0 when the app revealed it); question = sum / 3.
//   Right fields lock green. A wrong field turns red, keeps what was typed and
//   gets the hint of the other quizzes under it (2 letters, then 4): nothing is
//   revealed before the third attempt, which reveals every remaining field.
//   The Tk version revealed one wrong field per miss, which gave the answers
//   away (reported by the twins, 2026-10-08).

/** Lowercase, spaces collapsed, "was / were" = "was/were": the comparison of the Tk version. */
const tripleKey = (text) => answers.collapseSpaces(text.trim().toLowerCase().replace(/\s*\/\s*/g, "/"));

function showTripleQuiz() {
  const questions = state.questions;
  const labels = ["Base verbale", "Prétérit", "Participe passé"];
  let index = 0;
  let attempts = 0;
  let score = 0;
  let answered = false;
  let fieldScores = [null, null, null];

  /** A field still to fill, or still holding the miss of the last attempt. */
  const pending = (field) => !field.disabled && (!field.value.trim() || field.classList.contains("wrong"));

  const counter = h("span", { class: "quiz-counter" });
  const [progress, progressFill] = progressLine();
  const prompt = h("p", { class: "prompt" });
  const inputs = labels.map((label, i) => h("input", {
    ...ANSWER_FIELD, class: "answer", lang: "en", "aria-label": label,
    enterkeyhint: i < 2 ? "next" : "go",
    // Enter goes to the next field still empty or red (after this one, then
    // from the top) rather than validating a half-done question, which would
    // burn an attempt. The button validates.
    onkeydown: (event) => {
      if (event.key !== "Enter" || answered) return;
      const target = [i + 1, i + 2].map((j) => inputs[j % 3]).find(pending);
      if (target) {
        event.preventDefault();
        target.focus();
        if (finePointer) target.select();
      }
    },
    // Once retyped, a red field no longer holds the miss.
    oninput: () => inputs[i].classList.remove("wrong"),
  }));
  const hints = labels.map(() => h("span", { class: "field-hint" }));
  const submit = h("button", { class: "btn wide", type: "submit" }, "Valider");
  const feedback = h("p", { class: "feedback", role: "status" });
  const next = h("button", { class: "btn primary continue", type: "button", hidden: true, onclick: goNext }, "Continuer →");

  const form = h("form", {
    class: "triple-form",
    onsubmit: (event) => {
      event.preventDefault();
      if (answered) goNext();
      else check();
    },
  },
  labels.map((label, i) => h("label", { class: "field" },
    h("span", { class: "field-label" }, label), inputs[i], hints[i])),
  submit);

  function load() {
    attempts = 0;
    answered = false;
    fieldScores = [null, null, null];
    for (const hint of hints) hint.textContent = "";
    const q = questions[index];
    counter.textContent = `${index + 1} / ${questions.length}`;
    progressFill.style.width = `${(100 * index) / questions.length}%`;
    prompt.textContent = `Traduis en anglais : « ${q.source} »`;
    feedback.textContent = "";
    feedback.className = "feedback";
    for (const field of inputs) {
      field.value = "";
      field.disabled = false;
      field.className = "answer";
    }
    submit.disabled = false;
    next.hidden = true;
    inputs[0].focus();
  }

  function lock(i, kind) {
    inputs[i].disabled = true;
    inputs[i].className = `answer ${kind}`;
  }

  function check() {
    if (answered) return;
    const q = questions[index];
    attempts++;
    const points = { 1: 1, 2: 0.5, 3: 0.25 }[attempts] ?? 0;
    const values = [q.base, q.preterit, q.past_participle];
    const ok = inputs.map((field, i) => tripleKey(field.value) === tripleKey(values[i]));

    ok.forEach((good, i) => {
      if (good && fieldScores[i] === null) {
        fieldScores[i] = points;
        lock(i, "right");
        hints[i].textContent = "";
      }
    });
    const questionScore = () => fieldScores.reduce((sum, s) => sum + (s ?? 0), 0) / 3;

    if (ok.every(Boolean)) {
      score += questionScore();
      const message = attempts === 1 ? "Excellent !" : attempts === 2 ? "Bien rattrapé !" : "Bien joué !";
      feedback.textContent = `✓  ${message}`;
      feedback.className = "feedback right";
      finish();
    } else if (attempts >= 3) {
      score += questionScore();
      ok.forEach((good, i) => {
        if (!good) {
          inputs[i].value = values[i];
          lock(i, "revealed");
          hints[i].textContent = "";
        }
      });
      feedback.textContent = "✗  Pas cette fois…";
      feedback.className = "feedback wrong";
      finish();
    } else {
      const remaining = 3 - attempts;
      feedback.textContent = `✗  Pas tout à fait… encore ${remaining} ${remaining === 1 ? "essai" : "essais"}.`;
      feedback.className = "feedback wrong";
      // Nothing is revealed yet: each wrong field turns red with its hint, and
      // the first one takes the focus.
      const wrong = [0, 1, 2].filter((i) => !ok[i]);
      for (const i of wrong) {
        inputs[i].className = "answer wrong";
        hints[i].textContent = `Indice : ${answers.hintPrefix(values[i], attempts)}…`;
      }
      inputs[wrong[0]].focus();
      if (finePointer) inputs[wrong[0]].select();
    }
  }

  function finish() {
    answered = true;
    inputs.forEach((field) => { field.disabled = true; });
    submit.disabled = true;
    next.hidden = false;
    progressFill.style.width = `${(100 * (index + 1)) / questions.length}%`;
    next.focus();
  }

  function goNext() {
    if (!answered) return;
    index++;
    if (index >= questions.length) {
      saveSession(score, questions.length);
      showResults();
    } else {
      load();
    }
  }

  const onKey = (event) => {
    if (event.target.closest?.("input, button")) return;
    if (event.key === "Enter" || (event.key === " " && answered)) {
      event.preventDefault();
      if (answered) goNext();
      else check();
    }
  };
  document.addEventListener("keydown", onKey);

  show(h("div", { class: "screen quiz" },
    quizBar(quizContext(), counter),
    progress,
    prompt,
    form,
    feedback,
    next),
  { back: confirmLeave, onLeave: () => document.removeEventListener("keydown", onKey) });
  load();
}

// ---------------------------------------------------------------------------
// Quiz: accord du participe passé
// ---------------------------------------------------------------------------
//
//   One attempt per sentence. For "avoir_cod_avant" the child must also tap
//   the word(s) of the COD in the sentence.
//   Participle wrong: 0. Right but COD wrong: 0.5. Right (and COD right): 1.
//   After answering: green = right, red = wrong, gold = COD word missed.
//   The COD is judged on positions (engine.codIndices): the article "les" of
//   "Ces jouets, les enfants les ont _____" is not the pronoun "les".

/** Lowercase, punctuation stripped word by word: the participle comparison. */
const accordKey = (text) => engine.stripPunct(text).toLowerCase();

function showAccordQuiz() {
  const questions = state.questions;
  let index = 0;
  let score = 0;
  let submitted = false;
  let tokens = [];
  let picked = new Set();

  const counter = h("span", { class: "quiz-counter" });
  const [progress, progressFill] = progressLine();
  const codTitle = h("p", { class: "cod-title" }, "Identifie le COD : touche le ou les mots de la phrase.");
  const sentence = h("div", { class: "sentence" });
  const input = h("input", { ...ANSWER_FIELD, class: "answer", lang: "fr", "aria-label": "Participe passé" });
  const submit = h("button", { class: "btn", type: "submit" }, "Valider");
  const feedback = h("div", { class: "feedback-block", role: "status" });
  const caseLabel = h("p", { class: "case-label" });
  const next = h("button", { class: "btn primary continue", type: "button", hidden: true, onclick: goNext });

  const form = h("form", {
    class: "answer-row",
    onsubmit: (event) => {
      event.preventDefault();
      if (submitted) goNext();
      else check();
    },
  }, input, submit);

  function load() {
    const q = questions[index];
    submitted = false;
    picked = new Set();
    counter.textContent = `${index + 1} / ${questions.length}`;
    progressFill.style.width = `${(100 * index) / questions.length}%`;

    const withCod = q.case === "avoir_cod_avant";
    codTitle.hidden = !withCod;
    if (withCod) {
      tokens = engine.accordTokens(q.prompt).map((token, i) => ({
        ...token,
        el: token.selectable
          ? h("button", { class: "token", type: "button", "aria-pressed": "false", onclick: () => toggle(i) }, token.display)
          : h("span", { class: "token-muted" }, token.display),
      }));
      sentence.replaceChildren(...tokens.flatMap((token) => [token.el, " "]));
      sentence.className = "sentence tokens";
    } else {
      tokens = [];
      sentence.replaceChildren(q.prompt);
      sentence.className = "sentence";
    }
    input.value = "";
    input.readOnly = false;
    input.className = "answer";
    submit.disabled = false;
    feedback.replaceChildren();
    caseLabel.textContent = "";
    next.hidden = true;
    input.focus();
  }

  function toggle(i) {
    if (submitted) return;
    const token = tokens[i];
    if (picked.has(i)) picked.delete(i);
    else picked.add(i);
    token.el.classList.toggle("picked", picked.has(i));
    token.el.setAttribute("aria-pressed", String(picked.has(i)));
  }

  function check() {
    if (submitted) return;
    submitted = true;
    const q = questions[index];
    const typed = input.value.trim();
    const ppOk = accordKey(typed) === accordKey(q.answer);

    let codOk = true;
    let pickedCod = "";
    let expected = [];
    if (q.case === "avoir_cod_avant") {
      pickedCod = [...picked].sort((a, b) => a - b).map((i) => tokens[i].raw).join(" ");
      expected = engine.codIndices(tokens, q.cod);
      const verdict = engine.checkCod(expected, picked);
      codOk = verdict.ok;
      for (const [i, mark] of verdict.marks) tokens[i].el.classList.add(mark);
    }

    score += !ppOk ? 0 : (q.case === "avoir_cod_avant" && !codOk ? 0.5 : 1);

    const lines = [ppOk
      ? h("p", { class: "right" }, `✓  Participe passé : ${q.answer}`)
      : h("p", { class: "wrong" }, `✗  Participe passé : ${typed || "(vide)"}  →  ${q.answer}`)];
    if (q.case === "avoir_cod_avant") {
      const shown = pickedCod ? `« ${pickedCod} »` : "(aucun mot touché)";
      // Spelt like the COD but taken elsewhere in the sentence (the article "les").
      const misplaced = pickedCod !== "" && engine.stripPunct(pickedCod) === engine.stripPunct(q.cod);
      lines.push(codOk
        ? h("p", { class: "right" }, `✓  COD identifié : « ${q.cod} »`)
        : h("p", { class: "wrong" }, misplaced
          ? `✗  COD : ${shown}, mais pas au bon endroit  →  ${expected.length > 1 ? "les mots" : "le mot"} en jaune`
          : `✗  COD : ${shown}  →  « ${q.cod} »`));
    }
    feedback.replaceChildren(...lines);
    caseLabel.textContent = CASE_LABELS[q.case] ?? "";
    input.className = `answer ${ppOk ? "right" : "wrong"}`;
    input.readOnly = true;
    submit.disabled = true;
    next.textContent = index + 1 >= questions.length ? "Voir les résultats ▶" : "Phrase suivante →";
    next.hidden = false;
    progressFill.style.width = `${(100 * (index + 1)) / questions.length}%`;
    next.focus();       // closes the phone keyboard: the explanation is worth reading
  }

  function goNext() {
    if (!submitted) return;
    index++;
    if (index >= questions.length) {
      saveSession(score, questions.length);
      showResults();
    } else {
      load();
    }
  }

  const onKey = (event) => {
    if (event.target.closest?.("input, button")) return;
    if (event.key === "Enter" || (event.key === " " && submitted)) {
      event.preventDefault();
      if (submitted) goNext();
      else check();
    }
  };
  document.addEventListener("keydown", onKey);

  show(h("div", { class: "screen quiz" },
    quizBar(state.player, counter),
    progress,
    h("p", { class: "quiz-title" }, "Accord du participe passé"),
    codTitle,
    sentence,
    h("label", { class: "field-label" }, "Participe passé :"),
    form,
    feedback,
    caseLabel,
    next),
  { back: confirmLeave, onLeave: () => document.removeEventListener("keydown", onKey) });
  load();
}

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

function showResults() {
  const exercise = state.exercise;
  const score = state.lastScore;
  const total = state.lastTotal;
  const percent = total ? engine.roundHalfEven((score / total) * 100) : 0;
  const message = RESULT_MESSAGES.find(([threshold]) => percent >= threshold)[1];
  const doc = store.loadPlayer(state.player);

  let progressText = null;
  if (state.mode === "progressive") {
    const now = engine.progressStats(exercise, doc.progress[exercise.slug] ?? {});
    const gained = now.acquired - (state.progressBefore ?? now).acquired;
    progressText = `Mots acquis\u00a0: ${now.acquired}${gained > 0 ? `\u00a0(+${gained})` : ""} · en cours\u00a0: ${now.learning} · à découvrir\u00a0: ${now.unseen}`;
  }

  const history = doc.sessions.filter((s) => s.slug === exercise.slug).reverse();
  const dateFormat = new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" });

  show(h("div", { class: "screen" },
    topBar({ title: exercise.name, back: showMenu }),
    h("div", { class: "score-card" },
      h("p", { class: "score" }, `${formatScore(score)} / ${total}`),
      h("p", { class: "score-message" }, message),
      progressText ? h("p", { class: "score-progress" }, progressText) : null),
    h("div", { class: "button-stack" },
      h("button", { class: "btn primary big", type: "button", onclick: replay }, "Rejouer"),
      h("div", { class: "button-row" },
        h("button", { class: "btn secondary", type: "button", onclick: showMenu }, "Changer d'exercice"),
        h("button", { class: "btn secondary", type: "button", onclick: showPlayers }, "Changer de joueur"))),
    h("h2", { class: "section-title" }, "Historique de tes résultats"),
    history.length
      ? h("ol", { class: "history" }, history.map((session) => h("li", {},
        h("span", {}, dateFormat.format(new Date(session.played_at))),
        h("span", { class: "history-score" }, `${formatScore(session.score)} / ${session.total}`))))
      : h("p", { class: "muted" }, "Aucune session enregistrée.")),
  { back: showMenu });
}

/**
 * Play the same exercise again. Words picked by hand (Latin, English verbs):
 * back to that selection. Progressive: the next session. The others redraw
 * a fresh series right away, vocabulary keeping its words and direction.
 */
function replay() {
  const spec = kindSpec(state.exercise);
  if (state.mode === "progressive") startProgressiveSession();
  else if (spec.select && !spec.direction) showSelection();
  else startSession(state.direction);
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

async function loadExercises() {
  const response = await fetch("exercises.json", { cache: "no-cache" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const catalog = await response.json();
  return catalog.exercises.sort((a, b) =>
    (a.level ?? "").localeCompare(b.level ?? "") || (a.sort_order ?? 100) - (b.sort_order ?? 100) || a.name.localeCompare(b.name));
}

async function start() {
  if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("sw.js").catch(() => { /* the site works without it */ });
  }
  try {
    state.exercises = await loadExercises();
  } catch {
    show(h("div", { class: "screen" },
      h("p", { class: "error" }, "Impossible de charger les exercices. Vérifie la connexion internet, puis réessaie."),
      h("button", { class: "btn primary", type: "button", onclick: () => window.location.reload() }, "Réessayer")));
    return;
  }
  const last = store.lastPlayer();
  if (last) {
    state.player = last;
    showMenu();
  } else {
    showPlayers();
  }
}

start();
