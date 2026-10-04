"""
main.py - Entry point and full UI for the revision app.

Run with:  python main.py   (or ./run.sh)

Navigation flow:
  PlayerScreen -> ExerciseSelectionScreen -> VerbSelectionScreen -+-> QuizScreen        -> ResultsScreen
                                                                 +-> EnglishQuizScreen -> ResultsScreen
                                          |                      +-> DirectionScreen   -> QuizScreen -> ResultsScreen
                                          +-> ModeScreen -> QuizScreen (progressive session) -> ResultsScreen
                                          |            +-> VerbSelectionScreen (free practice, as above)
                                          +-> (no selection) -----> QuizScreen / AccordPPScreen -> ResultsScreen

Which of those paths an exercise takes is decided by its `kind`, read from the
database (and ultimately from its JSON file in data/) - see _KINDS below.
Nothing about a given exercise is hardcoded in this file any more.
"""

import tkinter as tk
from tkinter import messagebox
import random
import re
from datetime import datetime

import answers
import db

# ---------------------------------------------------------------------------
# Shared application state passed between screens
# ---------------------------------------------------------------------------
app_state: dict = {}

SESSION_LENGTH = 20

# School year being revised right now. Its exercises open the menu; previous
# years are grouped underneath as "Révisions". Bump this every September.
CURRENT_LEVEL = "4e"


# ---------------------------------------------------------------------------
# Exercise kinds: what a session looks like for each family of exercise
# ---------------------------------------------------------------------------
#
#   select      : show VerbSelectionScreen first (pick the words / themes)
#   direction   : ask which way round to translate (DirectionScreen)
#   progressive : open on ModeScreen, which offers the progressive session
#                 (db.get_progressive_questions) before free practice
#   screen    : the screen that runs the questions
#   build     : (exercise, enabled_word_ids, direction) -> list of questions
#
# Adding an exercise family = one entry here + a builder in db.py. Adding an
# exercise of an existing family = a JSON file in data/, nothing else.

_KINDS: dict = {
    # French -> Latin infinitive + conjugated forms, one answer field.
    "forms": {
        "select": True, "direction": False, "screen": "QuizScreen",
        "build": lambda ex, ids, d: db.get_questions_for_exercise(ex["id"], enabled_word_ids=ids),
    },
    # English irregular verbs: three fields at once.
    "triple": {
        "select": True, "direction": False, "screen": "EnglishQuizScreen",
        "build": lambda ex, ids, d: db.get_english_questions_for_exercise(ex["id"], enabled_word_ids=ids),
    },
    # Vocabulary list, translated either way.
    "vocab": {
        "select": True, "direction": True, "screen": "QuizScreen",
        "build": lambda ex, ids, d: db.get_vocab_questions(ex["id"], enabled_word_ids=ids, direction=d),
    },
    # Big catch-up list (6e-5e textbook lexicons): free practice exactly like
    # "vocab", plus the progressive session offered first on ModeScreen.
    "leitner": {
        "select": True, "direction": True, "progressive": True, "screen": "QuizScreen",
        "build": lambda ex, ids, d: db.get_vocab_questions(ex["id"], enabled_word_ids=ids, direction=d),
    },
    # A bank of sentences with a blank: no per-word selection, random draw.
    "sentences": {
        "select": False, "direction": False, "screen": "QuizScreen",
        "build": lambda ex, ids, d: db.get_fill_blank_questions(ex["id"]),
    },
    # Accord du participe passé: its own screen (click the COD, then answer).
    "accord_pp": {
        "select": False, "direction": False, "screen": "AccordPPScreen",
        "build": lambda ex, ids, d: db.get_accord_pp_questions(ex["id"]),
    },
}


# ---------------------------------------------------------------------------
# What counts as a correct answer, explained to the child
# ---------------------------------------------------------------------------
#
# answers.py is tolerant on some spellings and strict on others. A child cannot
# guess where that line sits, and "j'avais écrit la bonne réponse" is how they
# lose confidence in the app - so the rules are written on screen, in the
# language of the expected answer. Keyed by the *_lang_code of the exercise.

_ANSWER_RULES: dict = {
    "de": ("ä ö ü ß : tu peux taper ae oe ue ss (für = fuer, mais fur est faux).\n"
           "L'article fait partie de la réponse : der Tisch, pas Tisch."),
    "fr": ("Les accents ne sont pas obligatoires (fenetre = fenêtre),\n"
           "l'article non plus (fenêtre = la fenêtre)."),
}


def answer_rules(lang: str) -> str:
    """The typing rules for answers in that language, "" when there is nothing to say."""
    return _ANSWER_RULES.get(lang, "")


def kind_spec(exercise: dict) -> dict:
    """The _KINDS entry of an exercise, falling back to the plain "forms" flow."""
    return _KINDS.get(exercise.get("kind", ""), _KINDS["forms"])


def open_exercise(app, exercise: dict) -> None:
    """Menu click: go to the selection screen, or straight into the questions."""
    app_state["exercise"] = exercise
    app_state.pop("enabled_word_ids", None)
    spec = kind_spec(exercise)
    if spec.get("progressive"):
        app.show_frame("ModeScreen")
    elif spec["select"]:
        app.show_frame("VerbSelectionScreen")
    else:
        start_session(app, exercise)


def start_session(app, exercise: dict, enabled_word_ids=None,
                  direction: str = db.DIRECTION_MIXED) -> None:
    """
    Draw up to SESSION_LENGTH questions and hand them to the right screen.

    Single entry point for starting a series - used by the menu, by the
    selection screen, by the direction chooser and by "Rejouer", so all four
    behave the same.
    """
    questions = kind_spec(exercise)["build"](exercise, enabled_word_ids, direction)
    if not questions:
        messagebox.showwarning(
            "Rien à réviser",
            "Aucune question pour cette sélection. Coche au moins un mot.",
        )
        return

    random.shuffle(questions)
    app_state["questions"] = questions[:SESSION_LENGTH]
    app_state["enabled_word_ids"] = enabled_word_ids
    app_state["direction"] = direction
    app_state["mode"] = "free"
    app.show_frame(kind_spec(exercise)["screen"])


def start_progressive_session(app, exercise: dict) -> None:
    """
    Today's progressive series for the current player: the words due for
    review, topped up with new ones in textbook order. Which words and in
    which direction is decided by db.get_progressive_questions().
    """
    player = app_state["player"]
    questions = db.get_progressive_questions(exercise["id"], player["id"], size=SESSION_LENGTH)
    if not questions:
        messagebox.showinfo(
            "Rien pour aujourd'hui",
            "Tous les mots ont déjà été présentés et aucun n'est à revoir aujourd'hui.\n"
            "Reviens demain !",
        )
        return
    app_state["questions"] = questions
    app_state["mode"] = "progressive"
    app_state["progress_before"] = db.get_progress_stats(exercise["id"], player["id"])
    app.show_frame("QuizScreen")


# ---------------------------------------------------------------------------
# Small shared UI helpers
# ---------------------------------------------------------------------------

def make_scroll_area(parent, bg: str, height: int):
    """
    A bordered, vertically scrollable area (used by three screens).

    Returns (outer, inner, bind_wheel):
      outer      - frame to pack into the screen
      inner      - frame to put the content in
      bind_wheel - call it from the screen's on_show() so the wheel scrolls THIS
                   area; the binding is global to the window, so the screen
                   being shown claims it.
    """
    outer = tk.Frame(parent, bg=bg, bd=1, relief="groove")
    canvas = tk.Canvas(outer, bg=bg, highlightthickness=0, height=height)
    scrollbar = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    inner = tk.Frame(canvas, bg=bg)
    window = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(window, width=e.width))
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

    def _on_wheel(event):
        # macOS reports small deltas (+/-1 per notch), Windows/X11 multiples of
        # 120. Dividing by 120 unconditionally - as this app used to - meant no
        # scrolling at all on a Mac, which a 258-word list makes unbearable.
        step = event.delta
        if abs(step) >= 120:
            step = step / 120
        step = int(step) or (1 if step > 0 else -1)
        canvas.yview_scroll(-step, "units")

    def bind_wheel():
        canvas.bind_all("<MouseWheel>", _on_wheel)

    return outer, inner, bind_wheel


def darken(hex_color: str, factor: float = 0.82) -> str:
    """Darker shade of a #rrggbb colour, for a button's pressed state."""
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return hex_color
    return "#%02x%02x%02x" % tuple(min(255, int(c * factor)) for c in (r, g, b))


# ---------------------------------------------------------------------------
# App shell
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Révisions")
        self.resizable(False, False)
        self._center_window(width=640, height=620)

        self._frames: dict = {}
        self.build_frames()
        self.show_frame("PlayerScreen")

    def _center_window(self, width: int, height: int) -> None:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

    def build_frames(self) -> None:
        container = tk.Frame(self)
        container.pack(fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        for FrameClass in (
            PlayerScreen,
            ExerciseSelectionScreen,
            ModeScreen,
            VerbSelectionScreen,
            DirectionScreen,
            QuizScreen,
            EnglishQuizScreen,
            AccordPPScreen,
            ResultsScreen,
        ):
            frame = FrameClass(parent=container, app=self)
            self._frames[FrameClass.__name__] = frame
            frame.grid(row=0, column=0, sticky="nsew")

    def show_frame(self, name: str) -> None:
        frame = self._frames[name]
        frame.tkraise()
        if hasattr(frame, "on_show"):
            frame.on_show()


# ---------------------------------------------------------------------------
# Screen 1: Player selection
# ---------------------------------------------------------------------------

class PlayerScreen(tk.Frame):
    BG         = "#f5f0e8"
    TITLE_FONT = ("Helvetica", 20, "bold")
    LABEL_FONT = ("Helvetica", 13)
    BTN_FONT   = ("Helvetica", 13)
    LIST_FONT  = ("Helvetica", 14)

    def __init__(self, parent, app):
        super().__init__(parent, bg=self.BG)
        self.app = app
        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(padx=40, pady=30)

        tk.Label(self, text="Révisions", font=self.TITLE_FONT,
                 bg=self.BG, fg="#3a2a0a").pack(pady=(0, 20))

        tk.Label(self, text="Choisis ton prénom :", font=self.LABEL_FONT,
                 bg=self.BG, anchor="w").pack(fill="x")

        list_frame = tk.Frame(self, bg=self.BG)
        list_frame.pack(fill="x", pady=(4, 10))

        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        self._listbox = tk.Listbox(
            list_frame, font=self.LIST_FONT, height=5, selectmode="single",
            yscrollcommand=scrollbar.set, activestyle="dotbox",
        )
        scrollbar.config(command=self._listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self._listbox.pack(side="left", fill="x", expand=True)
        self._listbox.bind("<<ListboxSelect>>", self._on_player_selected)
        self._listbox.bind("<Double-Button-1>", lambda e: self._start())

        new_frame = tk.Frame(self, bg=self.BG)
        new_frame.pack(fill="x", pady=(0, 20))

        self._name_var = tk.StringVar()
        entry = tk.Entry(new_frame, textvariable=self._name_var,
                         font=self.LIST_FONT, width=18)
        entry.pack(side="left", padx=(0, 8))
        entry.bind("<Return>", lambda e: self._add_player())

        tk.Button(new_frame, text="Nouveau joueur", font=self.BTN_FONT,
                  command=self._add_player).pack(side="left")

        self._start_btn = tk.Button(
            self, text="Commencer  ▶", font=("Helvetica", 15, "bold"),
            bg="#4a7c59", fg="black", activebackground="#3a6349",
            state="disabled", command=self._start, pady=8,
        )
        self._start_btn.pack(fill="x")

    def on_show(self) -> None:
        self._listbox.delete(0, "end")
        for p in db.list_players():
            self._listbox.insert("end", p["name"])
        self._start_btn.config(state="disabled")

    def _on_player_selected(self, _event=None) -> None:
        if self._listbox.curselection():
            self._start_btn.config(state="normal")

    def _add_player(self) -> None:
        name = self._name_var.get().strip()
        if not name:
            return
        db.get_or_create_player(name)
        self._name_var.set("")
        self.on_show()
        players = db.list_players()
        names = [p["name"] for p in players]
        if name in names:
            idx = names.index(name)
            self._listbox.selection_set(idx)
            self._listbox.see(idx)
            self._start_btn.config(state="normal")

    def _start(self) -> None:
        sel = self._listbox.curselection()
        if not sel:
            return
        player = db.get_or_create_player(self._listbox.get(sel[0]))
        app_state["player"] = player
        self.app.show_frame("ExerciseSelectionScreen")


# ---------------------------------------------------------------------------
# Screen 2: Exercise selection (Latin vs English)
# ---------------------------------------------------------------------------

class ExerciseSelectionScreen(tk.Frame):
    """
    The menu, built entirely from the database (db.list_exercises).

    Exercises are grouped by school level: the current year first, older years
    below under "Révisions de 5e". Label, colour and position all come from the
    exercise's JSON file, so adding an exercise never means editing this screen.
    """

    BG            = "#f5f0e8"
    TITLE_FONT    = ("Helvetica", 18, "bold")
    SECTION_FONT  = ("Helvetica", 12, "bold")
    BTN_FONT      = ("Helvetica", 14, "bold")   # exercises of the current year
    REVISION_FONT = ("Helvetica", 12, "bold")   # previous years, kept compact
    BACK_FONT     = ("Helvetica", 12)

    def __init__(self, parent, app):
        super().__init__(parent, bg=self.BG)
        self.app = app
        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(padx=40, pady=20)

        self._title = tk.Label(self, text="", font=self.TITLE_FONT,
                               bg=self.BG, fg="#3a2a0a")
        self._title.pack(pady=(0, 14))

        outer, self._menu, self._bind_wheel = make_scroll_area(self, self.BG, height=470)
        outer.pack(fill="both", expand=True, pady=(0, 10))

        tk.Button(
            self, text="← Retour", font=self.BACK_FONT,
            command=lambda: self.app.show_frame("PlayerScreen"),
        ).pack()

    @staticmethod
    def _level_sort_key(level: str):
        """Current year first, then the other years newest to oldest, rest last."""
        if level == CURRENT_LEVEL:
            return (0, "")
        if not level:
            return (2, "")
        return (1, level)   # "4e" < "5e" < "6e" = most recent first

    @staticmethod
    def _level_heading(level: str) -> str:
        if not level:
            return "Autres exercices"
        if level == CURRENT_LEVEL:
            return f"Programme de {level}"
        return f"Révisions de {level}"

    def on_show(self) -> None:
        player = app_state.get("player", {})
        self._title.config(text=f"Bonjour {player.get('name', '')} ! Quel exercice ?")

        for widget in self._menu.winfo_children():
            widget.destroy()

        exercises = db.list_exercises()
        if not exercises:
            tk.Label(self._menu, text="Aucun exercice. Vérifie les fichiers data/.",
                     font=self.BTN_FONT, bg=self.BG, fg="#b22222").pack(pady=20)
            return

        by_level: dict = {}
        for exercise in exercises:
            by_level.setdefault(exercise.get("level", ""), []).append(exercise)

        for level in sorted(by_level, key=self._level_sort_key):
            tk.Label(
                self._menu, text=self._level_heading(level), font=self.SECTION_FONT,
                bg=self.BG, fg="#8a7a5a", anchor="w",
            ).pack(fill="x", padx=6, pady=(8, 2))

            # This year's exercises get the big buttons; older years are listed
            # underneath in a compact form - still one click away, but visibly
            # secondary, and the whole menu fits without scrolling.
            current = (level == CURRENT_LEVEL)
            for exercise in by_level[level]:
                color = exercise.get("color") or "#4a7c59"
                label = exercise.get("button_label") or exercise["name"]
                tk.Button(
                    self._menu,
                    text=label if current else label.replace("\n", " "),
                    font=self.BTN_FONT if current else self.REVISION_FONT,
                    bg=color, fg="black", activebackground=darken(color),
                    pady=11 if current else 6,
                    command=lambda e=exercise: open_exercise(self.app, e),
                ).pack(fill="x", padx=6, pady=(0, 7 if current else 4))

        self._bind_wheel()


# ---------------------------------------------------------------------------
# Screen 3: Verb selection (per-player, persisted)
# ---------------------------------------------------------------------------

class VerbSelectionScreen(tk.Frame):
    """
    Pick what to revise: one checkbox per word, saved per player.

    When the exercise groups its words by theme (a vocabulary list), each theme
    gets a header checkbox that ticks or unticks the whole block - that is how
    you revise only "Lektion 3" the evening before a test.
    """

    BG          = "#f5f0e8"
    TITLE_FONT  = ("Helvetica", 16, "bold")
    THEME_FONT  = ("Helvetica", 12, "bold")
    VERB_FONT   = ("Helvetica", 13)
    COUNT_FONT  = ("Helvetica", 11)
    BTN_FONT    = ("Helvetica", 13)

    def __init__(self, parent, app):
        super().__init__(parent, bg=self.BG)
        self.app = app
        self._checks: dict = {}        # word_id -> BooleanVar
        self._theme_vars: dict = {}    # theme   -> BooleanVar (header checkbox)
        self._theme_words: dict = {}   # theme   -> [word_id, ...]
        self._grid_row: int = 0        # next free row in the checkbox grid
        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(padx=30, pady=16)

        self._title = tk.Label(self, text="", font=self.TITLE_FONT,
                               bg=self.BG, fg="#3a2a0a")
        self._title.pack(pady=(0, 8))

        outer, self._cb_frame, self._bind_wheel = make_scroll_area(self, self.BG, height=300)
        outer.pack(fill="both", expand=True, pady=(0, 8))

        sel_row = tk.Frame(self, bg=self.BG)
        sel_row.pack(fill="x", pady=(0, 8))
        tk.Button(sel_row, text="Tout cocher", font=self.BTN_FONT,
                  command=self._check_all).pack(side="left", padx=(0, 8))
        tk.Button(sel_row, text="Tout décocher", font=self.BTN_FONT,
                  command=self._uncheck_all).pack(side="left")
        self._count_label = tk.Label(sel_row, text="", font=self.COUNT_FONT,
                                     bg=self.BG, fg="#666")
        self._count_label.pack(side="right")

        btn_row = tk.Frame(self, bg=self.BG)
        btn_row.pack(fill="x")

        tk.Button(btn_row, text="← Retour", font=self.BTN_FONT,
                  command=self._back).pack(side="left", padx=(0, 8))

        self._start_btn = tk.Button(
            btn_row, text="Commencer  ▶", font=("Helvetica", 14, "bold"),
            bg="#4a7c59", fg="black", activebackground="#3a6349",
            command=self._start, pady=6,
        )
        self._start_btn.pack(side="left", expand=True, fill="x")

    def on_show(self) -> None:
        player = app_state.get("player", {})
        exercise = app_state.get("exercise", {})
        if not player or not exercise:
            return

        for widget in self._cb_frame.winfo_children():
            widget.destroy()
        self._checks.clear()
        self._theme_vars.clear()
        self._theme_words.clear()
        self._grid_row = 0

        prefs = db.get_word_prefs(player["id"], exercise["id"])
        is_vocab = exercise.get("kind") == "vocab"
        self._title.config(
            text="Choisir les mots à réviser" if is_vocab
            else "Choisir les verbes à réviser"
        )

        # Group in seed order; "" is the single group for ungrouped exercises.
        groups: dict = {}
        for pref in prefs:
            groups.setdefault(pref.get("theme", ""), []).append(pref)

        for theme, words in groups.items():
            if theme:
                self._add_theme_header(theme, words)
            self._add_words(words)

        self._cb_frame.columnconfigure(0, weight=1)
        self._cb_frame.columnconfigure(1, weight=1)
        self._bind_wheel()
        self._update_start_btn()

    def _add_theme_header(self, theme: str, words: list) -> None:
        """Bold checkbox that ticks/unticks every word of the theme."""
        self._theme_words[theme] = [w["word_id"] for w in words]
        var = tk.BooleanVar(value=all(w["enabled"] for w in words))
        self._theme_vars[theme] = var

        header = tk.Frame(self._cb_frame, bg=self.BG)
        header.grid(row=self._grid_row, column=0, columnspan=2,
                    sticky="ew", pady=(10, 2))
        self._grid_row += 1
        tk.Checkbutton(
            header, text=theme, variable=var, font=self.THEME_FONT,
            bg=self.BG, fg="#6a5a3a", anchor="w",
            command=lambda t=theme: self._toggle_theme(t),
        ).pack(side="left", padx=(6, 0))

    def _add_words(self, words: list) -> None:
        """Two columns of word checkboxes, appended under the current row."""
        first_row = self._grid_row
        for i, pref in enumerate(words):
            var = tk.BooleanVar(value=pref["enabled"])
            self._checks[pref["word_id"]] = var
            tk.Checkbutton(
                self._cb_frame, text=pref["source"], variable=var,
                font=self.VERB_FONT, bg=self.BG, anchor="w",
                command=self._on_word_toggled,
            ).grid(row=first_row + i // 2, column=i % 2, sticky="w", padx=12, pady=2)
        self._grid_row = first_row + (len(words) + 1) // 2

    def _back(self) -> None:
        progressive = kind_spec(app_state.get("exercise") or {}).get("progressive")
        self.app.show_frame("ModeScreen" if progressive else "ExerciseSelectionScreen")

    def _toggle_theme(self, theme: str) -> None:
        wanted = self._theme_vars[theme].get()
        for word_id in self._theme_words[theme]:
            self._checks[word_id].set(wanted)
        self._update_start_btn()

    def _on_word_toggled(self) -> None:
        """Keep each theme header in sync with the words underneath it."""
        for theme, word_ids in self._theme_words.items():
            self._theme_vars[theme].set(all(self._checks[w].get() for w in word_ids))
        self._update_start_btn()

    def _update_start_btn(self) -> None:
        selected = sum(1 for v in self._checks.values() if v.get())
        total = len(self._checks)
        self._count_label.config(text=f"{selected} / {total} sélectionnés")
        self._start_btn.config(state="normal" if selected else "disabled")

    def _set_all(self, value: bool) -> None:
        for var in self._checks.values():
            var.set(value)
        for var in self._theme_vars.values():
            var.set(value)
        self._update_start_btn()

    def _check_all(self) -> None:
        self._set_all(True)

    def _uncheck_all(self) -> None:
        self._set_all(False)

    def _start(self) -> None:
        player = app_state["player"]
        exercise = app_state["exercise"]

        prefs = {word_id: var.get() for word_id, var in self._checks.items()}
        db.save_word_prefs(player["id"], prefs)

        enabled_ids = [word_id for word_id, enabled in prefs.items() if enabled]
        app_state["enabled_word_ids"] = enabled_ids

        if kind_spec(exercise)["direction"]:
            self.app.show_frame("DirectionScreen")
        else:
            start_session(self.app, exercise, enabled_ids)


# ---------------------------------------------------------------------------
# Screen 3a: How to work a big list (progressive exercises only)
# ---------------------------------------------------------------------------

class ModeScreen(tk.Frame):
    """
    Entry of a progressive exercise (the 6e-5e German catch-up list).

    Two ways in: today's session, where the app picks the words - the one
    recommended, so it comes first and big - or free practice on units picked
    by hand, the ordinary vocabulary flow. The player's progress sits on top:
    on a list of a thousand words, watching the acquired count move is most of
    the motivation. The method is explained in plain words, like the typing
    rules elsewhere, so that a word coming back is never a mystery.
    """

    BG             = "#f5f0e8"
    TITLE_FONT     = ("Helvetica", 18, "bold")
    STATS_FONT     = ("Helvetica", 13, "bold")
    SUB_FONT       = ("Helvetica", 11)
    BTN_FONT       = ("Helvetica", 15, "bold")
    ALT_BTN_FONT   = ("Helvetica", 13)
    HOW_TITLE_FONT = ("Helvetica", 11, "bold")
    HOW_FONT       = ("Helvetica", 11)
    BACK_FONT      = ("Helvetica", 12)

    BAR_WIDTH, BAR_HEIGHT = 520, 14
    COLOR_ACQUIRED = "#4a7c59"
    COLOR_LEARNING = "#d9a441"
    COLOR_UNSEEN   = "#ddd5c4"

    HOW_IT_WORKS = (
        "Chaque séance reprend les mots à revoir aujourd'hui, puis ajoute des mots\n"
        "nouveaux dans l'ordre du manuel : plus tu en connais, plus il en arrive.\n"
        "Un mot nouveau est un petit test, en allemand. Trouvé du premier coup :\n"
        "il est acquis, tu ne le reverras que dans 2 mois pour vérifier.\n"
        "Pas trouvé : tu l'apprends, d'abord dans le sens allemand → français, puis\n"
        "dans l'autre, de plus en plus espacé (le lendemain, 3 jours, 7 jours).\n"
        "Trouvé grâce à l'indice : il recule d'une case. Raté : il repart au début."
    )

    def __init__(self, parent, app):
        super().__init__(parent, bg=self.BG)
        self.app = app
        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(padx=50, pady=22)

        self._title = tk.Label(self, text="", font=self.TITLE_FONT,
                               bg=self.BG, fg="#3a2a0a")
        self._title.pack(pady=(0, 10))

        self._stats = tk.Label(self, text="", font=self.STATS_FONT, bg=self.BG, fg="#3a2a0a")
        self._stats.pack()
        self._bar = tk.Canvas(self, width=self.BAR_WIDTH, height=self.BAR_HEIGHT,
                              bg=self.COLOR_UNSEEN, highlightthickness=0)
        self._bar.pack(pady=(6, 4))
        self._next = tk.Label(self, text="", font=self.SUB_FONT, bg=self.BG, fg="#666")
        self._next.pack(pady=(0, 16))

        tk.Button(
            self, text="Séance du jour  ▶", font=self.BTN_FONT,
            bg="#4a7c59", fg="black", activebackground=darken("#4a7c59"), pady=14,
            command=lambda: start_progressive_session(self.app, app_state["exercise"]),
        ).pack(fill="x")
        tk.Label(self, text="L'appli choisit les mots : ceux à revoir, puis des nouveaux.",
                 font=self.SUB_FONT, bg=self.BG, fg="#666").pack(pady=(3, 12))

        tk.Button(
            self, text="Réviser des unités au choix", font=self.ALT_BTN_FONT,
            command=lambda: self.app.show_frame("VerbSelectionScreen"),
        ).pack(fill="x")

        how = tk.Frame(self, bg="#ece5d8")
        how.pack(fill="x", pady=(16, 0))
        tk.Label(how, text="Comment ça marche", font=self.HOW_TITLE_FONT,
                 bg="#ece5d8", fg="#6a5a3a", anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(how, text=self.HOW_IT_WORKS, font=self.HOW_FONT, bg="#ece5d8",
                 fg="#5a4a2a", justify="left", anchor="w").pack(fill="x", padx=12, pady=(0, 10))

        tk.Button(
            self, text="← Retour", font=self.BACK_FONT,
            command=lambda: self.app.show_frame("ExerciseSelectionScreen"),
        ).pack(pady=(14, 0))

    def on_show(self) -> None:
        exercise, player = app_state.get("exercise") or {}, app_state.get("player") or {}
        if not exercise or not player:
            return
        self._title.config(text=exercise.get("name", ""))

        stats = db.get_progress_stats(exercise["id"], player["id"])
        self._stats.config(
            text=f"Acquis : {stats['acquired']}   ·   En cours : {stats['learning']}"
                 f"   ·   À découvrir : {stats['unseen']}"
        )
        self._draw_bar(stats)

        parts = []
        if stats["tested"] >= 20:
            rate = round(100 * stats["known_at_test"] / stats["tested"])
            parts.append(f"{rate} % des mots testés étaient déjà sus")
        if stats["due"]:
            parts.append(f"{stats['due']} mot{'s' if stats['due'] > 1 else ''} à revoir aujourd'hui")
        if stats["next_theme"]:
            parts.append(f"prochains mots nouveaux : {stats['next_theme']}")
        self._next.config(text="   ·   ".join(parts) or "Tous les mots ont été présentés.")

    def _draw_bar(self, stats: dict) -> None:
        """Acquired (green), learning (amber), still unseen (background)."""
        self._bar.delete("all")
        total = stats["total"] or 1
        acquired = self.BAR_WIDTH * stats["acquired"] / total
        learning = self.BAR_WIDTH * stats["learning"] / total
        self._bar.create_rectangle(0, 0, acquired, self.BAR_HEIGHT,
                                   fill=self.COLOR_ACQUIRED, width=0)
        self._bar.create_rectangle(acquired, 0, acquired + learning, self.BAR_HEIGHT,
                                   fill=self.COLOR_LEARNING, width=0)


# ---------------------------------------------------------------------------
# Screen 3b: Direction of translation (vocabulary only)
# ---------------------------------------------------------------------------

class DirectionScreen(tk.Frame):
    """
    "Dans quel sens ?", asked once before a vocabulary series.

    Producing the foreign word (Français -> Allemand) and recognising it
    (Allemand -> Français) are two different skills, and the hard one is
    production. Letting the child choose means they can drill the one they are
    weak at instead of always meeting half the questions they already know.
    The languages are read from the exercise, so this screen works as-is for a
    future Spanish or English list.
    """

    BG              = "#f5f0e8"
    TITLE_FONT      = ("Helvetica", 18, "bold")
    BTN_FONT        = ("Helvetica", 15, "bold")
    SUB_FONT        = ("Helvetica", 11)
    RULES_TITLE_FONT= ("Helvetica", 11, "bold")
    RULES_FONT      = ("Helvetica", 11)
    BACK_FONT       = ("Helvetica", 12)

    def __init__(self, parent, app):
        super().__init__(parent, bg=self.BG)
        self.app = app
        self._buttons: list = []
        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(padx=60, pady=30)

        tk.Label(self, text="Dans quel sens ?", font=self.TITLE_FONT,
                 bg=self.BG, fg="#3a2a0a").pack(pady=(10, 6))
        self._subtitle = tk.Label(self, text="", font=self.SUB_FONT,
                                  bg=self.BG, fg="#666")
        self._subtitle.pack(pady=(0, 20))

        for direction, color in (
            (db.DIRECTION_FORWARD, "#8a6a2a"),
            (db.DIRECTION_REVERSE, "#4a6a9c"),
            (db.DIRECTION_MIXED,   "#4a7c59"),
        ):
            button = tk.Button(
                self, text="", font=self.BTN_FONT,
                bg=color, fg="black", activebackground=darken(color), pady=14,
                command=lambda d=direction: self._start(d),
            )
            button.pack(fill="x", pady=(0, 12))
            self._buttons.append((direction, button))

        # Same rules as the footer of the quiz, but read calmly before starting.
        self._rules_frame = tk.Frame(self, bg="#ece5d8", bd=1, relief="flat")
        self._rules_frame.pack(fill="x", pady=(6, 0))
        tk.Label(self._rules_frame, text="Comment écrire tes réponses",
                 font=self.RULES_TITLE_FONT, bg="#ece5d8", fg="#6a5a3a",
                 anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        self._rules_label = tk.Label(
            self._rules_frame, text="", font=self.RULES_FONT, bg="#ece5d8",
            fg="#5a4a2a", justify="left", anchor="w",
        )
        self._rules_label.pack(fill="x", padx=12, pady=(0, 10))

        tk.Button(
            self, text="← Retour", font=self.BACK_FONT,
            command=lambda: self.app.show_frame("VerbSelectionScreen"),
        ).pack(pady=(14, 0))

    def on_show(self) -> None:
        exercise = app_state.get("exercise", {})
        source = exercise.get("source_language") or "Français"
        target = exercise.get("target_language") or "Langue étrangère"

        selected = len(app_state.get("enabled_word_ids") or [])
        self._subtitle.config(text=f"{selected} mots sélectionnés")

        labels = {
            db.DIRECTION_FORWARD: f"{source}  →  {target}",
            db.DIRECTION_REVERSE: f"{target}  →  {source}",
            db.DIRECTION_MIXED:   "Les deux mélangés",
        }
        for direction, button in self._buttons:
            button.config(text=labels[direction])

        # Both directions are reachable from here, including in "mixed", so both
        # sets of rules are shown - the child reads them once before starting.
        rules = [answer_rules(exercise.get("target_lang_code", "")),
                 answer_rules(exercise.get("source_lang_code", ""))]
        text = "\n".join(r for r in rules if r)
        self._rules_label.config(text=text)
        if text:
            self._rules_frame.pack(fill="x", pady=(6, 0))
        else:
            self._rules_frame.pack_forget()

    def _start(self, direction: str) -> None:
        start_session(self.app, app_state["exercise"],
                      app_state.get("enabled_word_ids"), direction)


# ---------------------------------------------------------------------------
# Screen 4: Latin quiz (single answer field)
# ---------------------------------------------------------------------------

class QuizScreen(tk.Frame):
    """
    Runs a session of up to SESSION_LENGTH questions.

    Attempt and scoring rules:
      - Up to 3 attempts per question.
      - Wrong answer: red feedback, field NOT cleared (child corrects in-place).
      - Hint shown below feedback:
          - After attempt 1 wrong: first 2 letters of the answer
          - After attempt 2 wrong: first 4 letters, or len(answer)-1 if answer <= 4 chars
      - After 3 wrong attempts: reveal the full correct answer in blue.
      - Correct on attempt 1: +1.0 point
      - Correct on attempt 2: +0.5 point
      - Correct on attempt 3: +0.25 point

    Keyboard shortcuts (bound at root window level in on_show, unbound in _end_session):
      Enter  - submit answer (while answering) OR advance to next question (after feedback)
      Space  - advance to next question (after feedback only)
    """

    BG            = "#f5f0e8"
    HEADER_FONT   = ("Helvetica", 11)
    PROMPT_FONT   = ("Helvetica", 16, "bold")
    ENTRY_FONT    = ("Helvetica", 15)
    FEEDBACK_FONT = ("Helvetica", 13)
    HINT_FONT     = ("Helvetica", 12, "italic")
    BTN_FONT      = ("Helvetica", 13)
    CONTINUE_FONT = ("Helvetica", 13, "bold")
    RULES_FONT    = ("Helvetica", 10)

    COLOR_CORRECT = "#1a7a2a"
    COLOR_WRONG   = "#b22222"
    COLOR_HINT    = "#7a5500"
    COLOR_REVEAL  = "#1a4a8a"
    COLOR_NEUTRAL = "#3a2a0a"
    COLOR_RULES   = "#8a7a5a"

    def __init__(self, parent, app):
        super().__init__(parent, bg=self.BG)
        self.app = app

        self._questions: list = []
        self._q_index: int = 0
        self._attempts: int = 0
        self._score: float = 0.0
        self._answered: bool = False

        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(padx=40, pady=20)

        header = tk.Frame(self, bg=self.BG)
        header.pack(fill="x", pady=(0, 10))
        self._player_label = tk.Label(header, text="", font=self.HEADER_FONT,
                                      bg=self.BG, fg="#666")
        self._player_label.pack(side="left")
        self._counter_label = tk.Label(header, text="", font=self.HEADER_FONT,
                                       bg=self.BG, fg="#666")
        self._counter_label.pack(side="right")

        tk.Frame(self, bg="#ccc", height=1).pack(fill="x", pady=(0, 20))

        self._prompt_label = tk.Label(
            self, text="", font=self.PROMPT_FONT, bg=self.BG,
            fg=self.COLOR_NEUTRAL, wraplength=540, justify="center",
        )
        self._prompt_label.pack(pady=(10, 20))

        entry_frame = tk.Frame(self, bg=self.BG)
        entry_frame.pack(fill="x", pady=(0, 10))
        self._answer_var = tk.StringVar()
        self._entry = tk.Entry(entry_frame, textvariable=self._answer_var,
                               font=self.ENTRY_FONT, width=26)
        self._entry.pack(side="left", padx=(0, 10))
        self._submit_btn = tk.Button(entry_frame, text="Valider", font=self.BTN_FONT,
                                     command=self._check_answer)
        self._submit_btn.pack(side="left")

        self._feedback_label = tk.Label(
            self, text="", font=self.FEEDBACK_FONT, bg=self.BG,
            fg=self.COLOR_CORRECT, wraplength=540, justify="center",
        )
        self._feedback_label.pack(pady=(8, 2))

        self._hint_label = tk.Label(
            self, text="", font=self.HINT_FONT, bg=self.BG, fg=self.COLOR_HINT,
        )
        self._hint_label.pack(pady=(0, 2))

        self._continue_btn = tk.Button(
            self, text="Continuer  →", font=self.CONTINUE_FONT,
            bg="#4a7c59", fg="black", activebackground="#3a6349",
            command=self._next_question, pady=6,
        )
        self._continue_btn.pack(fill="x", pady=(16, 0))
        self._continue_btn.pack_forget()

        # Pinned to the bottom: the typing rules for the language being answered
        # in. Empty (and invisible) for Latin, English and French exercises,
        # which are compared strictly and have nothing to explain.
        self._rules_label = tk.Label(
            self, text="", font=self.RULES_FONT, bg=self.BG, fg=self.COLOR_RULES,
            justify="center",
        )
        self._rules_label.pack(side="bottom", pady=(10, 0))

    def on_show(self) -> None:
        self._questions = app_state.get("questions", [])
        self._q_index = 0
        self._score = 0.0
        player = app_state.get("player", {})
        self._player_label.config(
            text=f"Joueur : {player.get('name', '')}{self._direction_suffix()}"
        )

        root = self.winfo_toplevel()
        root.bind("<Return>", self._on_enter)
        root.bind("<space>", self._on_space)

        self._load_question()

    @staticmethod
    def _direction_suffix() -> str:
        """" · Français → Allemand" for a one-way vocabulary series, else ""."""
        exercise = app_state.get("exercise", {})
        direction = app_state.get("direction", db.DIRECTION_MIXED)
        if app_state.get("mode") == "progressive":
            return "   ·   séance progressive"
        if not kind_spec(exercise)["direction"]:
            return ""
        source = exercise.get("source_language", "")
        target = exercise.get("target_language", "")
        if direction == db.DIRECTION_FORWARD:
            return f"   ·   {source} → {target}"
        if direction == db.DIRECTION_REVERSE:
            return f"   ·   {target} → {source}"
        return "   ·   les deux sens"

    def _load_question(self) -> None:
        self._attempts = 0
        self._answered = False
        q = self._questions[self._q_index]

        total = len(self._questions)
        self._counter_label.config(text=f"Question {self._q_index + 1} / {total}")
        self._prompt_label.config(text=q["prompt"], fg=self.COLOR_NEUTRAL)
        self._feedback_label.config(text="")
        self._hint_label.config(text="")
        # In a mixed series the language changes from one question to the next.
        self._rules_label.config(text=answer_rules(q.get("answer_lang", "")))

        self._entry.config(state="normal")
        self._submit_btn.config(state="normal")
        self._answer_var.set("")
        self._continue_btn.pack_forget()
        self._entry.focus_set()

    def _on_enter(self, _event=None) -> None:
        if self._answered:
            self._next_question()
        else:
            self._check_answer()

    def _on_space(self, _event=None) -> None:
        if self._answered:
            self._next_question()

    def _check_answer(self) -> None:
        if self._answered:
            return

        raw = self._answer_var.get()
        q = self._questions[self._q_index]
        correct_display = q["answer"].strip()
        # Vocabulary questions carry every accepted answer and the language of
        # the expected one; the older exercises carry neither and keep the
        # strict comparison they always had (see answers.py).
        accepted = q.get("accepted") or [correct_display]
        lang = q.get("answer_lang", "")

        self._attempts += 1

        if answers.matches(raw, accepted, lang):
            if self._attempts == 1:
                points, msg = 1.0, "Excellent !"
            elif self._attempts == 2:
                points, msg = 0.5, "Bien rattrapé !"
            else:
                points, msg = 0.25, "Bien joué !"
            self._score += points
            self._record_progress(q, db.result_of(self._attempts, found=True))
            self._feedback_label.config(text=f"\u2713  {msg}", fg=self.COLOR_CORRECT)
            self._hint_label.config(text="")
            self._show_continue()

        elif self._attempts >= 3:
            self._record_progress(q, db.result_of(self._attempts, found=False))
            self._feedback_label.config(text="\u2717  Pas cette fois\u2026", fg=self.COLOR_WRONG)
            self._hint_label.config(
                text=f"La bonne réponse était : {correct_display}",
                fg=self.COLOR_REVEAL,
                font=self.FEEDBACK_FONT,
            )
            self._show_continue()

        else:
            remaining = 3 - self._attempts
            s = "essai" if remaining == 1 else "essais"
            self._feedback_label.config(
                text=f"\u2717  Pas tout à fait\u2026 encore {remaining} {s}.",
                fg=self.COLOR_WRONG,
            )

            hint = answers.hint_prefix(correct_display, self._attempts, lang)
            self._hint_label.config(
                text=f"Indice : {hint}\u2026",
                fg=self.COLOR_HINT,
                font=self.HINT_FONT,
            )

            self._entry.focus_set()
            self._entry.select_range(0, "end")

    @staticmethod
    def _record_progress(q: dict, result: str) -> None:
        """Progressive mode only: file the outcome, the word moves to its next box."""
        if q.get("progressive"):
            db.record_progress(app_state["player"]["id"], q["word_id"], result)

    def _show_continue(self) -> None:
        self._answered = True
        self._entry.config(state="disabled")
        self._submit_btn.config(state="disabled")
        self._continue_btn.pack(fill="x", pady=(16, 0))
        self.focus_set()

    def _next_question(self) -> None:
        if not self._answered:
            return
        self._q_index += 1
        if self._q_index >= len(self._questions):
            self._end_session()
        else:
            self._load_question()

    def _end_session(self) -> None:
        root = self.winfo_toplevel()
        root.unbind("<Return>")
        root.unbind("<space>")

        player = app_state["player"]
        exercise = app_state["exercise"]
        total = len(self._questions)

        db.save_session(
            player_id=player["id"],
            exercise_id=exercise["id"],
            score=self._score,
            total=total,
        )
        app_state["last_score"] = self._score
        app_state["last_total"] = total

        self.app.show_frame("ResultsScreen")


# ---------------------------------------------------------------------------
# Screen 5: English irregular-verb quiz (three answer fields)
# ---------------------------------------------------------------------------

class EnglishQuizScreen(tk.Frame):
    """
    Runs a session of English irregular-verb questions.

    Each question shows a French word; the student must fill in the three
    English forms simultaneously (base verbale, prétérit, participe passé).

    Scoring - per field, averaged over three fields:
      Each field is scored independently based on when the student first typed it
      correctly. Fields pre-filled by the system (blue) score 0.
        - Student correct on attempt 1: 1.0 pts for that field
        - Student correct on attempt 2: 0.5 pts
        - Student correct on attempt 3: 0.25 pts
        - System-revealed:              0 pts
      Question score = sum(field scores) / 3.  Max = 1.0.
      Anchors: all three by student on attempt 1 = 1.0; all three on attempt 2 = 0.5;
               all three on attempt 3 = 0.25.

    Reveal rules:
      - Fields the student gets right are locked green immediately.
      - On each wrong attempt (attempts 1 and 2): the first still-wrong field is
        revealed in blue (pre-filled, locked). Focus moves to the next editable field.
      - Attempt 3 wrong: all remaining wrong fields revealed; no further credit.

    Keyboard shortcuts:
      Enter  - submit or continue (same as QuizScreen)
      Space  - continue after feedback
    """

    BG            = "#f5f0e8"
    HEADER_FONT   = ("Helvetica", 11)
    PROMPT_FONT   = ("Helvetica", 18, "bold")
    LABEL_FONT    = ("Helvetica", 13)
    ENTRY_FONT    = ("Helvetica", 14)
    FEEDBACK_FONT = ("Helvetica", 13)
    BTN_FONT      = ("Helvetica", 13)
    CONTINUE_FONT = ("Helvetica", 13, "bold")

    COLOR_CORRECT  = "#1a7a2a"
    COLOR_WRONG    = "#b22222"
    COLOR_REVEAL   = "#1a4a8a"
    COLOR_REVEAL_BG = "#dce8ff"
    COLOR_NEUTRAL  = "#3a2a0a"

    def __init__(self, parent, app):
        super().__init__(parent, bg=self.BG)
        self.app = app

        self._questions: list = []
        self._q_index: int = 0
        self._attempts: int = 0
        self._score: float = 0.0
        self._answered: bool = False
        self._field_scores: list = [None, None, None]   # per-field pts: 1.0/0.5/0.25 or None
        self._field_revealed: list = [False, False, False]  # True = system-revealed, no credit

        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(padx=40, pady=14)

        # Header
        header = tk.Frame(self, bg=self.BG)
        header.pack(fill="x", pady=(0, 6))
        self._player_label = tk.Label(header, text="", font=self.HEADER_FONT,
                                      bg=self.BG, fg="#666")
        self._player_label.pack(side="left")
        self._counter_label = tk.Label(header, text="", font=self.HEADER_FONT,
                                       bg=self.BG, fg="#666")
        self._counter_label.pack(side="right")

        tk.Frame(self, bg="#ccc", height=1).pack(fill="x", pady=(0, 10))

        # Prompt
        self._prompt_label = tk.Label(
            self, text="", font=self.PROMPT_FONT, bg=self.BG,
            fg=self.COLOR_NEUTRAL, wraplength=520, justify="center",
        )
        self._prompt_label.pack(pady=(4, 14))

        # Three answer fields
        fields_frame = tk.Frame(self, bg=self.BG)
        fields_frame.pack(fill="x", pady=(0, 6))

        self._base_var = tk.StringVar()
        self._pret_var = tk.StringVar()
        self._pp_var   = tk.StringVar()

        self._field_rows = []  # (var, entry) tuples in order
        for label_text, var in [
            ("Base verbale :", self._base_var),
            ("Prétérit :",     self._pret_var),
            ("Participe passé :", self._pp_var),
        ]:
            row = tk.Frame(fields_frame, bg=self.BG)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label_text, font=self.LABEL_FONT,
                     bg=self.BG, width=18, anchor="e").pack(side="left", padx=(0, 8))
            entry = tk.Entry(row, textvariable=var, font=self.ENTRY_FONT, width=22)
            entry.pack(side="left")
            self._field_rows.append((var, entry))

        self._base_entry = self._field_rows[0][1]
        self._pret_entry = self._field_rows[1][1]
        self._pp_entry   = self._field_rows[2][1]

        # Submit
        self._submit_btn = tk.Button(self, text="Valider", font=self.BTN_FONT,
                                     command=self._check_answer)
        self._submit_btn.pack(pady=(4, 0))

        # Feedback
        self._feedback_label = tk.Label(
            self, text="", font=self.FEEDBACK_FONT, bg=self.BG,
            fg=self.COLOR_CORRECT, wraplength=520, justify="center",
        )
        self._feedback_label.pack(pady=(6, 0))

        # Continue
        self._continue_btn = tk.Button(
            self, text="Continuer  →", font=self.CONTINUE_FONT,
            bg="#4a6a9c", fg="black", activebackground="#3a5a8c",
            command=self._next_question, pady=6,
        )
        self._continue_btn.pack(fill="x", pady=(10, 0))
        self._continue_btn.pack_forget()

    def on_show(self) -> None:
        self._questions = app_state.get("questions", [])
        self._q_index = 0
        self._score = 0.0
        player = app_state.get("player", {})
        self._player_label.config(text=f"Joueur : {player.get('name', '')}")

        root = self.winfo_toplevel()
        root.bind("<Return>", self._on_enter)
        root.bind("<space>", self._on_space)

        self._load_question()

    def _load_question(self) -> None:
        self._attempts = 0
        self._answered = False
        self._field_scores = [None, None, None]
        self._field_revealed = [False, False, False]
        q = self._questions[self._q_index]

        total = len(self._questions)
        self._counter_label.config(text=f"Question {self._q_index + 1} / {total}")
        self._prompt_label.config(
            text=f"Traduis en anglais : \u00ab\u00a0{q['source']}\u00a0\u00bb",
            fg=self.COLOR_NEUTRAL,
        )
        self._feedback_label.config(text="")

        # Reset all three fields
        for var, entry in self._field_rows:
            var.set("")
            entry.config(state="normal", fg="black", bg="white",
                         disabledforeground="gray", disabledbackground="#e0e0e0")

        self._submit_btn.config(state="normal")
        self._continue_btn.pack_forget()
        self._base_entry.focus_set()

    def _on_enter(self, _event=None) -> None:
        if self._answered:
            self._next_question()
        else:
            self._check_answer()

    def _on_space(self, _event=None) -> None:
        if self._answered:
            self._next_question()

    @staticmethod
    def _normalize(s: str) -> str:
        """Lowercase, strip, collapse spaces, normalize slash spacing."""
        s = s.strip().lower()
        s = re.sub(r"\s*/\s*", "/", s)
        return " ".join(s.split())

    def _check_answer(self) -> None:
        if self._answered:
            return

        q = self._questions[self._q_index]
        self._attempts += 1

        attempt_pts = {1: 1.0, 2: 0.5, 3: 0.25}.get(self._attempts, 0.0)

        entries = [self._base_entry, self._pret_entry, self._pp_entry]
        vars_   = [self._base_var,   self._pret_var,   self._pp_var]
        values  = [q["base"],        q["preterit"],     q["past_participle"]]

        ok = [
            self._normalize(vars_[i].get()) == self._normalize(values[i])
            for i in range(3)
        ]

        # Lock each newly-correct field in green and record its score.
        for i in range(3):
            if ok[i] and self._field_scores[i] is None and not self._field_revealed[i]:
                self._field_scores[i] = attempt_pts
                self._lock_correct(entries[i])

        all_done = all(ok)  # every field has the right value (student or system)

        if all_done:
            q_score = sum(s for s in self._field_scores if s is not None) / 3
            self._score += q_score
            if self._attempts == 1:
                msg = "Excellent !"
            elif self._attempts == 2:
                msg = "Bien rattrapé !"
            else:
                msg = "Bien joué !"
            self._feedback_label.config(text=f"\u2713  {msg}", fg=self.COLOR_CORRECT)
            self._show_continue()

        elif self._attempts >= 3:
            # Reveal all remaining wrong fields; no further credit.
            q_score = sum(s for s in self._field_scores if s is not None) / 3
            self._score += q_score
            for i in range(3):
                if not ok[i]:
                    self._field_revealed[i] = True
                    self._reveal(entries[i], vars_[i], values[i])
            self._feedback_label.config(
                text="\u2717  Pas cette fois\u2026", fg=self.COLOR_WRONG
            )
            self._show_continue()

        else:
            remaining = 3 - self._attempts
            s = "essai" if remaining == 1 else "essais"
            self._feedback_label.config(
                text=f"\u2717  Pas tout à fait\u2026 encore {remaining} {s}.",
                fg=self.COLOR_WRONG,
            )
            # Reveal the first still-wrong field; focus on next still-editable field.
            revealed_one = False
            for i in range(3):
                if not ok[i] and not self._field_revealed[i]:
                    if not revealed_one:
                        self._field_revealed[i] = True
                        self._reveal(entries[i], vars_[i], values[i])
                        revealed_one = True
                    else:
                        entries[i].focus_set()
                        entries[i].select_range(0, "end")
                        break

    def _reveal(self, entry: tk.Entry, var: tk.StringVar, value: str) -> None:
        """Pre-fill a field with the correct answer and lock it (blue - system revealed)."""
        var.set(value)
        entry.config(
            state="disabled",
            disabledforeground=self.COLOR_REVEAL,
            disabledbackground=self.COLOR_REVEAL_BG,
        )

    def _lock_correct(self, entry: tk.Entry) -> None:
        """Lock a field the student entered correctly (green - student earned it)."""
        entry.config(
            state="disabled",
            disabledforeground="#1a7a2a",
            disabledbackground="#d4f0d4",
        )

    def _show_continue(self) -> None:
        self._answered = True
        # Disable any field still enabled (correct answers stay their default colour).
        for _, entry in self._field_rows:
            if entry["state"] == "normal":
                entry.config(state="disabled")
        self._submit_btn.config(state="disabled")
        self._continue_btn.pack(fill="x", pady=(10, 0))
        self.focus_set()

    def _next_question(self) -> None:
        if not self._answered:
            return
        self._q_index += 1
        if self._q_index >= len(self._questions):
            self._end_session()
        else:
            self._load_question()

    def _end_session(self) -> None:
        root = self.winfo_toplevel()
        root.unbind("<Return>")
        root.unbind("<space>")

        player = app_state["player"]
        exercise = app_state["exercise"]
        total = len(self._questions)

        db.save_session(
            player_id=player["id"],
            exercise_id=exercise["id"],
            score=self._score,
            total=total,
        )
        app_state["last_score"] = self._score
        app_state["last_total"] = total

        self.app.show_frame("ResultsScreen")


# ---------------------------------------------------------------------------
# Screen 6: Accord du participe passé (French grammar)
# ---------------------------------------------------------------------------

class AccordPPScreen(tk.Frame):
    """
    Quiz screen for 'Accord du participe passé'.

    Four grammatical cases are tested (source: data/accord_participe_passe.json):
      sans_auxiliaire : ppé without auxiliary — agrees like an adjective with
                        the noun it qualifies.
      avec_etre       : ppé with auxiliary ÊTRE — always agrees with the subject.
      avoir_cod_apres : ppé with AVOIR, COD placed AFTER the verb → no agreement.
      avoir_cod_avant : ppé with AVOIR, COD placed BEFORE the verb → agreement
                        with the COD. The COD may be a personal pronoun (le/la/les),
                        the relative pronoun (que), or an interrogative determiner
                        + noun (quel/quelle/quels/quelles + noun).

    Exercise rules:
      - ONE attempt per sentence — no hints, no retries.
      - For avoir_cod_avant questions the student must ALSO identify the COD
        by clicking on the word(s) in the sentence before submitting.
      - After submission, colour-coded feedback shows:
          green  = correct answer / correctly selected COD word
          red    = wrong answer / wrongly selected word
          gold   = expected COD word that was missed
        The grammatical case explanation is always displayed.

    Scoring (per sentence):
      PP wrong                                        → 0.0
      PP correct, avoir_cod_avant, COD wrong          → 0.5
      PP correct + COD correct (or non-avant case)    → 1.0
    """

    BG         = "#f5f0e8"
    TITLE_FONT = ("Helvetica", 15, "bold")
    LABEL_FONT = ("Helvetica", 13)
    ENTRY_FONT = ("Helvetica", 14)
    SMALL_FONT = ("Helvetica", 11)
    TOKEN_FONT = ("Helvetica", 12)
    BTN_FONT   = ("Helvetica", 13, "bold")

    # Explanations shown to the student after each submission
    CASE_LABELS = {
        "sans_auxiliaire": (
            "Cas : sans auxiliaire — le participe passé s'accorde comme "
            "un adjectif avec le nom qu'il qualifie."
        ),
        "avec_etre": (
            "Cas : auxiliaire ÊTRE — le participe passé s'accorde toujours "
            "avec le sujet."
        ),
        "avoir_cod_apres": (
            "Cas : auxiliaire AVOIR — le COD est placé après le verbe : "
            "pas d'accord."
        ),
        "avoir_cod_avant": (
            "Cas : auxiliaire AVOIR — le COD est placé avant le verbe : "
            "le participe passé s'accorde avec le COD."
        ),
    }

    # Punctuation stripped when normalising tokens for COD comparison
    _STRIP = ".,;:!?\"'»«()"

    def __init__(self, parent, app):
        super().__init__(parent, bg=self.BG)
        self.app = app
        self._questions:       list  = []
        self._idx:             int   = 0
        self._score:           float = 0.0
        self._submitted:       bool  = False
        self._selected_tokens: set   = set()   # indices of clicked tokens
        self._token_labels:    list  = []       # (widget|None, raw_text, is_selectable)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction (called once at startup)
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.configure(padx=30, pady=14)

        tk.Label(
            self,
            text="Français — Accord du participe passé",
            font=self.TITLE_FONT, bg=self.BG, fg="#3a2a0a",
        ).pack(pady=(0, 4))

        self._counter_lbl = tk.Label(
            self, text="", font=self.SMALL_FONT, bg=self.BG, fg="#666"
        )
        self._counter_lbl.pack()

        tk.Frame(self, bg="#ccc", height=1).pack(fill="x", pady=(6, 8))

        # Sentence display
        self._sentence_lbl = tk.Label(
            self, text="", font=self.LABEL_FONT,
            bg=self.BG, wraplength=560, justify="left",
        )
        self._sentence_lbl.pack(pady=(0, 10), fill="x")

        # Participe passé input row
        pp_row = tk.Frame(self, bg=self.BG)
        pp_row.pack(fill="x", pady=(0, 6))
        tk.Label(pp_row, text="Participe passé :", font=self.LABEL_FONT,
                  bg=self.BG).pack(side="left", padx=(0, 8))
        self._pp_var   = tk.StringVar()
        self._pp_entry = tk.Entry(
            pp_row, textvariable=self._pp_var, font=self.ENTRY_FONT, width=18
        )
        self._pp_entry.pack(side="left")

        # COD identification section — shown only for avoir_cod_avant questions.
        # Not packed initially; inserted before the submit button when needed.
        self._cod_section = tk.Frame(self, bg=self.BG)
        tk.Label(
            self._cod_section,
            text="Identifie le COD — clique sur le ou les mots :",
            font=self.LABEL_FONT, bg=self.BG,
        ).pack(anchor="w")
        # Inner frame that will hold the Text widget (re-created per question)
        self._cod_text_frame = tk.Frame(self._cod_section, bg=self.BG)
        self._cod_text_frame.pack(fill="x", pady=(4, 0))

        # Submit button (always packed initially; hidden after submission)
        self._submit_btn = tk.Button(
            self, text="Valider", font=self.BTN_FONT,
            bg="#4a7c59", fg="black", activebackground="#3a6349",
            command=self._submit, pady=6,
        )
        self._submit_btn.pack(fill="x", pady=(6, 0))

        # Feedback widgets — NOT packed initially; appear after submission
        self._feedback_lbl = tk.Label(
            self, text="", font=self.LABEL_FONT,
            bg=self.BG, wraplength=560, justify="left",
        )
        self._case_lbl = tk.Label(
            self, text="", font=self.SMALL_FONT,
            bg=self.BG, wraplength=560, justify="left", fg="#555",
        )
        self._next_btn = tk.Button(
            self, text="Phrase suivante →", font=self.BTN_FONT,
            bg="#4a6a9c", fg="black", activebackground="#3a5a8c",
            command=self._next_question, pady=6,
        )

    # ------------------------------------------------------------------
    # Screen lifecycle
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        self._questions = list(app_state.get("questions", []))
        self._idx   = 0
        self._score = 0.0

        root = self.winfo_toplevel()
        root.bind("<Return>", self._on_enter)
        root.bind("<space>",  self._on_space)

        self._load_question()

    def _on_enter(self, _event=None) -> None:
        if self._submitted:
            self._next_question()
        else:
            self._submit()

    def _on_space(self, _event=None) -> None:
        if self._submitted:
            self._next_question()

    # ------------------------------------------------------------------
    # Question loading / navigation
    # ------------------------------------------------------------------

    def _load_question(self) -> None:
        q = self._questions[self._idx]
        self._submitted       = False
        self._selected_tokens = set()
        self._token_labels    = []

        self._counter_lbl.config(
            text=f"Question {self._idx + 1} / {len(self._questions)}"
        )
        self._sentence_lbl.config(text=q["prompt"])

        # Reset entry
        self._pp_var.set("")
        self._pp_entry.config(state="normal", bg="white")
        self._pp_entry.focus_set()

        # Show submit, hide feedback / next (must happen before cod_section
        # is packed, because cod_section uses before=_submit_btn)
        self._submit_btn.pack(fill="x", pady=(6, 0))
        self._feedback_lbl.pack_forget()
        self._case_lbl.pack_forget()
        self._next_btn.pack_forget()

        # Show or hide COD section depending on the grammatical case
        if q["case"] == "avoir_cod_avant":
            self._cod_section.pack(fill="x", pady=(0, 6), before=self._submit_btn)
            self._display_cod_tokens(q["prompt"])
        else:
            self._cod_section.pack_forget()

    def _next_question(self) -> None:
        self._idx += 1
        if self._idx >= len(self._questions):
            self._end_session()
        else:
            self._load_question()

    def _end_session(self) -> None:
        root = self.winfo_toplevel()
        root.unbind("<Return>")
        root.unbind("<space>")

        player   = app_state["player"]
        exercise = app_state["exercise"]
        total    = len(self._questions)
        db.save_session(
            player_id=player["id"],
            exercise_id=exercise["id"],
            score=self._score,
            total=total,
        )
        app_state["last_score"] = self._score
        app_state["last_total"] = total
        self.app.show_frame("ResultsScreen")

    # ------------------------------------------------------------------
    # COD token display (avoir_cod_avant questions only)
    # ------------------------------------------------------------------

    def _tokenize(self, sentence: str) -> list:
        """
        Split sentence into (display_text, raw_text, is_selectable) tuples.

        Non-selectable tokens (displayed greyed-out, not clickable):
          - the blank placeholder: any token containing '_____'
          - the verb hint: any token starting with '('
          - standalone punctuation marks whose raw text is empty after stripping
            (e.g. a lone '?' or '.' that ends up as an empty string after strip)

        raw_text: token with surrounding punctuation stripped, CASE PRESERVED.
        Case is intentionally preserved so that 'Les' (article, sentence-start)
        and 'les' (pronoun, mid-sentence) are treated as distinct clickable targets.
        The COD stored in the JSON also preserves the exact case as it appears
        in the sentence, so comparison is case-sensitive after stripping.
        """
        result = []
        for word in sentence.split():
            is_blank = "_____" in word
            is_hint  = word.startswith("(")
            raw = word.strip(self._STRIP) if (not is_blank and not is_hint) else word
            # Mark as non-selectable if raw is empty (standalone '?', '.', etc.)
            selectable = not is_blank and not is_hint and bool(raw)
            result.append((word, raw, selectable))
        return result

    def _display_cod_tokens(self, sentence: str) -> None:
        """
        Populate the COD token area with clickable word-labels.

        A read-only Text widget is used as a wrapping flow container so that
        tokens reflow correctly when the sentence is long.
        Selectable tokens appear as raised label-buttons (neutral beige).
        Non-selectable tokens (blank, hint) are rendered as greyed text.
        """
        # Clear any previous content
        for w in self._cod_text_frame.winfo_children():
            w.destroy()
        self._token_labels    = []
        self._selected_tokens = set()

        txt = tk.Text(
            self._cod_text_frame,
            wrap="word", height=2,
            bg=self.BG, relief="flat",
            state="normal",
        )
        txt.tag_configure("hint", foreground="#aaa")
        txt.pack(fill="x")

        tokens = self._tokenize(sentence)
        for i, (display, raw, selectable) in enumerate(tokens):
            if selectable:
                lbl = tk.Label(
                    txt, text=display,
                    font=self.TOKEN_FONT,
                    bg="#ddd8c8", relief="solid", borderwidth=1,
                    padx=4, pady=2, cursor="hand2",
                )
                lbl.bind(
                    "<Button-1>",
                    lambda e, idx=i, lb=lbl: self._toggle_token(idx, lb),
                )
                txt.window_create("end", window=lbl)
            else:
                lbl = None
                txt.insert("end", display, "hint")
            txt.insert("end", " ")
            self._token_labels.append((lbl, raw, selectable))

        txt.config(state="disabled")

    def _toggle_token(self, idx: int, label: tk.Label) -> None:
        """Toggle the selected state of a clickable token."""
        if self._submitted:
            return
        if idx in self._selected_tokens:
            self._selected_tokens.discard(idx)
            label.config(bg="#ddd8c8")
        else:
            self._selected_tokens.add(idx)
            label.config(bg="#90EE90")

    def _get_selected_cod(self) -> str:
        """Return the raw text of selected tokens joined in sentence order."""
        indices = sorted(
            i for i in self._selected_tokens
            if i < len(self._token_labels) and self._token_labels[i][2]
        )
        return " ".join(self._token_labels[i][1] for i in indices)

    @staticmethod
    def _normalize(text: str) -> str:
        """Lowercase and strip punctuation — used for participe passé comparison."""
        return " ".join(w.strip(".,;:!?\"'»«()-").lower() for w in text.split())

    @staticmethod
    def _strip_punct(text: str) -> str:
        """Strip punctuation but PRESERVE CASE — used for COD comparison.

        Case must be preserved so that 'Les' (article at sentence start) and
        'les' (pronoun mid-sentence) are NOT treated as the same COD candidate.
        The cod field in the JSON is stored with its exact sentence capitalisation.
        """
        return " ".join(w.strip(".,;:!?\"'»«()-") for w in text.split())

    # ------------------------------------------------------------------
    # Submission and feedback
    # ------------------------------------------------------------------

    def _submit(self) -> None:
        if self._submitted:
            return
        self._submitted = True
        self._pp_entry.config(state="disabled")

        q          = self._questions[self._idx]
        typed_pp   = self._pp_var.get().strip()
        correct_pp = q["answer"]
        pp_ok      = self._normalize(typed_pp) == self._normalize(correct_pp)

        # COD check applies only to avoir_cod_avant questions
        cod_ok       = True
        selected_cod = ""
        if q["case"] == "avoir_cod_avant":
            selected_cod = self._get_selected_cod()
            # COD comparison is case-sensitive (strip punct, keep case) so that
            # 'Les' (article) and 'les' (pronoun) are correctly distinguished.
            cod_ok = self._strip_punct(selected_cod) == self._strip_punct(q["cod"])
            self._color_cod_tokens(q["cod"])

        # Scoring:
        #   PP wrong                                       → 0.0
        #   PP correct + avoir_cod_avant + COD wrong       → 0.5
        #   PP correct + COD correct (or non-avant case)   → 1.0
        if not pp_ok:
            question_score = 0.0
        elif q["case"] == "avoir_cod_avant" and not cod_ok:
            question_score = 0.5
        else:
            question_score = 1.0
        self._score += question_score

        # PP feedback line
        if pp_ok:
            pp_line = f"\u2713  Participe passé : {correct_pp}"
            self._pp_entry.config(bg="#c8f0c8")
        else:
            pp_line = (
                f"\u2717  Participe passé : {typed_pp or '(vide)'}  \u2192  {correct_pp}"
            )
            self._pp_entry.config(bg="#f0c8c8")

        lines = [pp_line]

        # COD feedback line (avoir_cod_avant only)
        if q["case"] == "avoir_cod_avant":
            if cod_ok:
                lines.append(f"\u2713  COD identifié : \u00ab {q['cod']} \u00bb")
            else:
                shown = (
                    f"\u00ab {selected_cod} \u00bb"
                    if selected_cod else "(aucun sélectionné)"
                )
                lines.append(
                    f"\u2717  COD : {shown}  \u2192  \u00ab {q['cod']} \u00bb"
                )

        overall_ok = pp_ok and cod_ok
        self._feedback_lbl.config(
            text="\n".join(lines),
            fg="#1a6a1a" if overall_ok else "#8a1a1a",
        )
        self._feedback_lbl.pack(pady=(8, 2), fill="x")

        self._case_lbl.config(text=self.CASE_LABELS.get(q["case"], ""))
        self._case_lbl.pack(fill="x", pady=(0, 4))

        # Replace submit button with next/results button
        self._submit_btn.pack_forget()
        is_last = self._idx + 1 >= len(self._questions)
        self._next_btn.config(
            text="Voir les résultats \u25b6" if is_last else "Phrase suivante \u2192"
        )
        self._next_btn.pack(fill="x")

    def _color_cod_tokens(self, expected_cod: str) -> None:
        """
        Colour each selectable token after submission:
          green (#90EE90) : selected AND part of the expected COD
          red   (#f0a0a0) : selected but NOT part of the expected COD
          gold  (#FFD700) : NOT selected but IS part of the expected COD (missed)
          default         : neither selected nor expected (no change)
        """
        # Use case-sensitive word set so 'Les' (article) ≠ 'les' (pronoun)
        expected_words = {self._strip_punct(w) for w in expected_cod.split()}
        for i, (lbl, raw, selectable) in enumerate(self._token_labels):
            if lbl is None or not selectable:
                continue
            is_selected = i in self._selected_tokens
            is_expected = self._strip_punct(raw) in expected_words
            if is_selected and is_expected:
                lbl.config(bg="#90EE90")
            elif is_selected and not is_expected:
                lbl.config(bg="#f0a0a0")
            elif not is_selected and is_expected:
                lbl.config(bg="#FFD700")


# ---------------------------------------------------------------------------
# Screen 7: Results
# ---------------------------------------------------------------------------

class ResultsScreen(tk.Frame):
    """
    Shows the session score and a scrollable history of all past sessions for
    this player + exercise.

    Buttons:
      Rejouer           -> VerbSelectionScreen (same player, same exercise)
      Changer d'exercice-> ExerciseSelectionScreen
      Changer de joueur -> PlayerScreen
    """

    BG         = "#f5f0e8"
    SCORE_FONT = ("Helvetica", 42, "bold")
    MSG_FONT   = ("Helvetica", 14)
    HIST_FONT  = ("Helvetica", 12)
    BTN_FONT   = ("Helvetica", 13)

    _MESSAGES = [
        (100, "Parfait !"),
        (90,  "Excellent travail !"),
        (75,  "Tres bien !"),
        (60,  "Bien, continue comme ca !"),
        (40,  "Pas mal, mais on peut faire mieux !"),
        (0,   "Courage, tu vas progresser !"),
    ]

    def __init__(self, parent, app):
        super().__init__(parent, bg=self.BG)
        self.app = app
        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(padx=40, pady=16)

        self._score_label = tk.Label(self, text="", font=self.SCORE_FONT,
                                     bg=self.BG, fg="#4a7c59")
        self._score_label.pack(pady=(8, 2))

        self._msg_label = tk.Label(self, text="", font=self.MSG_FONT,
                                   bg=self.BG, fg="#3a2a0a")
        self._msg_label.pack(pady=(0, 4))

        # Progressive sessions only: where the player now stands on the list.
        self._progress_label = tk.Label(self, text="", font=("Helvetica", 12),
                                        bg=self.BG, fg="#4a6a3a")
        self._progress_label.pack(pady=(0, 8))

        tk.Frame(self, bg="#ccc", height=1).pack(fill="x", pady=(0, 6))

        tk.Label(self, text="Historique de tes resultats :",
                 font=("Helvetica", 12, "bold"), bg=self.BG).pack(anchor="w")

        hist_outer, self._hist_inner, self._bind_wheel = make_scroll_area(
            self, self.BG, height=140)
        hist_outer.pack(fill="x", pady=(4, 10))

        btn_row = tk.Frame(self, bg=self.BG)
        btn_row.pack(fill="x", pady=(0, 4))

        tk.Button(
            btn_row, text="Rejouer", font=self.BTN_FONT,
            bg="#4a7c59", fg="black", command=self._replay,
        ).pack(side="left", padx=(0, 6), expand=True, fill="x")

        tk.Button(
            btn_row, text="Changer d'exercice", font=self.BTN_FONT,
            command=lambda: self.app.show_frame("ExerciseSelectionScreen"),
        ).pack(side="left", padx=(0, 6), expand=True, fill="x")

        tk.Button(
            btn_row, text="Changer de joueur", font=self.BTN_FONT,
            command=lambda: self.app.show_frame("PlayerScreen"),
        ).pack(side="left", expand=True, fill="x")

    def on_show(self) -> None:
        score = app_state.get("last_score", 0.0)
        total = app_state.get("last_total", SESSION_LENGTH)

        score_str = f"{score:.2f}".rstrip("0").rstrip(".")
        self._score_label.config(text=f"{score_str} / {total}")

        pct = round(score / total * 100) if total else 0
        msg = next(m for thr, m in self._MESSAGES if pct >= thr)
        self._msg_label.config(text=msg)

        self._progress_label.config(text=self._progress_text())
        self._populate_history()
        self._bind_wheel()

    @staticmethod
    def _progress_text() -> str:
        """"Mots acquis : 57 (+3) · en cours : 143 · à découvrir : 780" after a progressive series."""
        if app_state.get("mode") != "progressive":
            return ""
        exercise, player = app_state["exercise"], app_state["player"]
        now = db.get_progress_stats(exercise["id"], player["id"])
        gained = now["acquired"] - app_state.get("progress_before", now)["acquired"]
        delta = f" (+{gained})" if gained > 0 else ""
        return (f"Mots acquis : {now['acquired']}{delta}   ·   en cours : {now['learning']}"
                f"   ·   à découvrir : {now['unseen']}")

    def _populate_history(self) -> None:
        for w in self._hist_inner.winfo_children():
            w.destroy()

        player = app_state.get("player", {})
        exercise = app_state.get("exercise", {})
        if not player or not exercise:
            return

        history = db.get_history(player["id"], exercise["id"])

        if not history:
            tk.Label(self._hist_inner, text="Aucune session enregistree.",
                     font=self.HIST_FONT, bg=self.BG, fg="#888").pack(anchor="w", padx=6)
            return

        hdr = tk.Frame(self._hist_inner, bg=self.BG)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Date", font=("Helvetica", 11, "bold"),
                 bg=self.BG, width=22, anchor="w").pack(side="left", padx=(6, 0))
        tk.Label(hdr, text="Score", font=("Helvetica", 11, "bold"),
                 bg=self.BG, width=12, anchor="w").pack(side="left")
        tk.Frame(self._hist_inner, bg="#ccc", height=1).pack(fill="x")

        for i, session in enumerate(history):
            row_bg = "#ede8de" if i % 2 == 0 else self.BG
            try:
                dt = datetime.fromisoformat(session["played_at"])
                date_str = dt.strftime("%d/%m/%Y %H:%M")
            except (ValueError, TypeError):
                date_str = str(session["played_at"])

            sc = session["score"]
            sc_str = f"{sc:.2f}".rstrip("0").rstrip(".")
            row = tk.Frame(self._hist_inner, bg=row_bg)
            row.pack(fill="x")
            tk.Label(row, text=date_str, font=self.HIST_FONT,
                     bg=row_bg, width=22, anchor="w").pack(side="left", padx=(6, 0))
            tk.Label(row, text=f"{sc_str} / {session['total']}", font=self.HIST_FONT,
                     bg=row_bg, width=12, anchor="w").pack(side="left")

    def _replay(self) -> None:
        """
        Play the same exercise again.

        Exercises whose words are picked by hand (Latin, English verbs) go back
        to that screen. The others - sentence banks, and vocabulary, which also
        remembers the direction just played - redraw a fresh series right away,
        which is the one-click "encore" a child expects.
        """
        exercise = app_state.get("exercise", {})
        if not exercise:
            self.app.show_frame("ExerciseSelectionScreen")
            return
        if app_state.get("mode") == "progressive":
            start_progressive_session(self.app, exercise)
            return

        spec = kind_spec(exercise)
        if spec["select"] and not spec["direction"]:
            self.app.show_frame("VerbSelectionScreen")
        else:
            start_session(
                self.app, exercise,
                app_state.get("enabled_word_ids"),
                app_state.get("direction", db.DIRECTION_MIXED),
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    db.bootstrap()
    app = App()
    app.mainloop()
