"""
main.py - Entry point and full UI for the revision app.

Run with:  python main.py   (or ./run.sh)

Navigation flow:
  PlayerScreen -> ExerciseSelectionScreen -> VerbSelectionScreen -> QuizScreen        -> ResultsScreen
                                                                 -> EnglishQuizScreen  -> ResultsScreen
"""

import re
import tkinter as tk
from tkinter import messagebox
import random
from datetime import datetime

import db

# ---------------------------------------------------------------------------
# Shared application state passed between screens
# ---------------------------------------------------------------------------
app_state: dict = {}

SESSION_LENGTH = 20


# ---------------------------------------------------------------------------
# App shell
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Révision Verbes")
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
            VerbSelectionScreen,
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

        tk.Label(self, text="Révision Verbes", font=self.TITLE_FONT,
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
    BG         = "#f5f0e8"
    TITLE_FONT = ("Helvetica", 18, "bold")
    BTN_FONT   = ("Helvetica", 14, "bold")
    BACK_FONT  = ("Helvetica", 12)

    def __init__(self, parent, app):
        super().__init__(parent, bg=self.BG)
        self.app = app
        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(padx=60, pady=30)

        self._title = tk.Label(self, text="", font=self.TITLE_FONT,
                               bg=self.BG, fg="#3a2a0a")
        self._title.pack(pady=(0, 36))

        tk.Button(
            self,
            text="Verbes Latins\n(Présent de l'indicatif)",
            font=self.BTN_FONT,
            bg="#4a7c59", fg="black", activebackground="#3a6349",
            command=self._choose_latin, pady=22,
        ).pack(fill="x", pady=(0, 18))

        tk.Button(
            self,
            text="Verbes Anglais irréguliers",
            font=self.BTN_FONT,
            bg="#4a6a9c", fg="black", activebackground="#3a5a8c",
            command=self._choose_english, pady=22,
        ).pack(fill="x", pady=(0, 18))

        tk.Button(
            self,
            text="Anglais - Phrases à trous",
            font=self.BTN_FONT,
            bg="#7a4a9c", fg="black", activebackground="#6a3a8c",
            command=self._choose_fill_blank, pady=22,
        ).pack(fill="x", pady=(0, 18))

        tk.Button(
            self,
            text="Français - Accord du participe passé",
            font=self.BTN_FONT,
            bg="#9c4a4a", fg="black", activebackground="#8c3a3a",
            command=self._choose_accord_pp, pady=22,
        ).pack(fill="x", pady=(0, 18))

        tk.Button(
            self,
            text="Français - Conjugaison\n(dire, pouvoir, voir)",
            font=self.BTN_FONT,
            bg="#9c4a4a", fg="black", activebackground="#8c3a3a",
            command=self._choose_french_verbs, pady=22,
        ).pack(fill="x")

        tk.Button(
            self, text="← Retour", font=self.BACK_FONT,
            command=lambda: self.app.show_frame("PlayerScreen"),
        ).pack(pady=(30, 0))

    def on_show(self) -> None:
        player = app_state.get("player", {})
        name = player.get("name", "")
        self._title.config(text=f"Bonjour {name} ! Quel exercice ?")

    def _choose_latin(self) -> None:
        exercise = db.get_exercise_by_slug("latin_verbs_present")
        if exercise is None:
            messagebox.showerror("Erreur", "Exercice introuvable. Vérifie les fichiers data/.")
            return
        app_state["exercise"] = exercise
        self.app.show_frame("VerbSelectionScreen")

    def _choose_english(self) -> None:
        exercise = db.get_exercise_by_slug("english_irregular_verbs")
        if exercise is None:
            messagebox.showerror("Erreur", "Exercice introuvable. Vérifie les fichiers data/.")
            return
        app_state["exercise"] = exercise
        self.app.show_frame("VerbSelectionScreen")

    def _choose_fill_blank(self) -> None:
        exercise = db.get_exercise_by_slug("english_fill_blanks")
        if exercise is None:
            messagebox.showerror("Erreur", "Exercice introuvable. Vérifie les fichiers data/.")
            return
        app_state["exercise"] = exercise
        all_q = db.get_fill_blank_questions(exercise["id"])
        random.shuffle(all_q)
        app_state["questions"] = all_q[:SESSION_LENGTH]
        self.app.show_frame("QuizScreen")

    def _choose_accord_pp(self) -> None:
        exercise = db.get_exercise_by_slug("accord_participe_passe")
        if exercise is None:
            messagebox.showerror("Erreur", "Exercice introuvable. Vérifie les fichiers data/.")
            return
        app_state["exercise"] = exercise
        all_q = db.get_accord_pp_questions(exercise["id"])
        random.shuffle(all_q)
        app_state["questions"] = all_q[:SESSION_LENGTH]
        self.app.show_frame("AccordPPScreen")

    def _choose_french_verbs(self) -> None:
        exercise = db.get_exercise_by_slug("french_verbs_modes")
        if exercise is None:
            messagebox.showerror("Erreur", "Exercice introuvable. Vérifie les fichiers data/.")
            return
        app_state["exercise"] = exercise
        self.app.show_frame("VerbSelectionScreen")


# ---------------------------------------------------------------------------
# Screen 3: Verb selection (per-player, persisted)
# ---------------------------------------------------------------------------

class VerbSelectionScreen(tk.Frame):
    BG        = "#f5f0e8"
    TITLE_FONT= ("Helvetica", 16, "bold")
    VERB_FONT = ("Helvetica", 13)
    BTN_FONT  = ("Helvetica", 13)

    def __init__(self, parent, app):
        super().__init__(parent, bg=self.BG)
        self.app = app
        self._checks: dict = {}
        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(padx=30, pady=16)

        tk.Label(self, text="Choisir les verbes à réviser",
                 font=self.TITLE_FONT, bg=self.BG, fg="#3a2a0a").pack(pady=(0, 8))

        outer = tk.Frame(self, bg=self.BG, bd=1, relief="groove")
        outer.pack(fill="both", expand=True, pady=(0, 8))

        canvas = tk.Canvas(outer, bg=self.BG, highlightthickness=0, height=280)
        sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._cb_frame = tk.Frame(canvas, bg=self.BG)
        self._cb_win = canvas.create_window((0, 0), window=self._cb_frame, anchor="nw")

        def _on_canvas_resize(event):
            canvas.itemconfig(self._cb_win, width=event.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        def _on_inner_resize(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        self._cb_frame.bind("<Configure>", _on_inner_resize)

        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)

        sel_row = tk.Frame(self, bg=self.BG)
        sel_row.pack(fill="x", pady=(0, 8))
        tk.Button(sel_row, text="Tout cocher", font=self.BTN_FONT,
                  command=self._check_all).pack(side="left", padx=(0, 8))
        tk.Button(sel_row, text="Tout décocher", font=self.BTN_FONT,
                  command=self._uncheck_all).pack(side="left")

        btn_row = tk.Frame(self, bg=self.BG)
        btn_row.pack(fill="x")

        tk.Button(btn_row, text="← Retour", font=self.BTN_FONT,
                  command=lambda: self.app.show_frame("ExerciseSelectionScreen")
                  ).pack(side="left", padx=(0, 8))

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

        for w in self._cb_frame.winfo_children():
            w.destroy()
        self._checks.clear()

        prefs = db.get_word_prefs(player["id"], exercise["id"])

        for i, pref in enumerate(prefs):
            var = tk.BooleanVar(value=pref["enabled"])
            self._checks[pref["word_id"]] = var

            col = i % 2
            row = i // 2
            cb = tk.Checkbutton(
                self._cb_frame, text=pref["source"],
                variable=var, font=self.VERB_FONT,
                bg=self.BG, anchor="w",
                command=self._update_start_btn,
            )
            cb.grid(row=row, column=col, sticky="w", padx=12, pady=2)

        self._cb_frame.columnconfigure(0, weight=1)
        self._cb_frame.columnconfigure(1, weight=1)
        self._update_start_btn()

    def _update_start_btn(self) -> None:
        any_checked = any(v.get() for v in self._checks.values())
        self._start_btn.config(state="normal" if any_checked else "disabled")

    def _check_all(self) -> None:
        for v in self._checks.values():
            v.set(True)
        self._update_start_btn()

    def _uncheck_all(self) -> None:
        for v in self._checks.values():
            v.set(False)
        self._update_start_btn()

    def _start(self) -> None:
        player = app_state["player"]
        exercise = app_state["exercise"]

        prefs = {wid: var.get() for wid, var in self._checks.items()}
        db.save_word_prefs(player["id"], prefs)

        enabled_ids = [wid for wid, enabled in prefs.items() if enabled]
        app_state["enabled_word_ids"] = enabled_ids

        if exercise["slug"] == "english_irregular_verbs":
            all_q = db.get_english_questions_for_exercise(
                exercise["id"], enabled_word_ids=enabled_ids
            )
            random.shuffle(all_q)
            app_state["questions"] = all_q[:SESSION_LENGTH]
            self.app.show_frame("EnglishQuizScreen")
        else:
            all_q = db.get_questions_for_exercise(
                exercise["id"], enabled_word_ids=enabled_ids
            )
            random.shuffle(all_q)
            app_state["questions"] = all_q[:SESSION_LENGTH]
            self.app.show_frame("QuizScreen")


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

    COLOR_CORRECT = "#1a7a2a"
    COLOR_WRONG   = "#b22222"
    COLOR_HINT    = "#7a5500"
    COLOR_REVEAL  = "#1a4a8a"
    COLOR_NEUTRAL = "#3a2a0a"

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
        q = self._questions[self._q_index]

        total = len(self._questions)
        self._counter_label.config(text=f"Question {self._q_index + 1} / {total}")
        self._prompt_label.config(text=q["prompt"], fg=self.COLOR_NEUTRAL)
        self._feedback_label.config(text="")
        self._hint_label.config(text="")

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
        answer = raw.strip().lower()
        q = self._questions[self._q_index]
        correct_lower = q["answer"].strip().lower()
        correct_display = q["answer"].strip()

        self._attempts += 1

        if answer == correct_lower:
            if self._attempts == 1:
                points, msg = 1.0, "Excellent !"
            elif self._attempts == 2:
                points, msg = 0.5, "Bien rattrapé !"
            else:
                points, msg = 0.25, "Bien joué !"
            self._score += points
            self._feedback_label.config(text=f"\u2713  {msg}", fg=self.COLOR_CORRECT)
            self._hint_label.config(text="")
            self._show_continue()

        elif self._attempts >= 3:
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

            n = len(correct_display)
            if self._attempts == 1:
                hint_len = 2
            else:
                hint_len = (n - 1) if n <= 4 else 4
            hint = correct_display[:hint_len]
            self._hint_label.config(
                text=f"Indice : {hint}\u2026",
                fg=self.COLOR_HINT,
                font=self.HINT_FONT,
            )

            self._entry.focus_set()
            self._entry.select_range(0, "end")

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
        self._msg_label.pack(pady=(0, 10))

        tk.Frame(self, bg="#ccc", height=1).pack(fill="x", pady=(0, 6))

        tk.Label(self, text="Historique de tes resultats :",
                 font=("Helvetica", 12, "bold"), bg=self.BG).pack(anchor="w")

        hist_outer = tk.Frame(self, bg=self.BG, bd=1, relief="groove")
        hist_outer.pack(fill="x", pady=(4, 10))

        canvas = tk.Canvas(hist_outer, bg=self.BG, highlightthickness=0, height=140)
        sb = tk.Scrollbar(hist_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._hist_inner = tk.Frame(canvas, bg=self.BG)
        self._hist_win = canvas.create_window((0, 0), window=self._hist_inner, anchor="nw")

        def _on_canvas_resize(event):
            canvas.itemconfig(self._hist_win, width=event.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        def _on_inner_resize(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        self._hist_inner.bind("<Configure>", _on_inner_resize)

        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)

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

        self._populate_history()

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
        exercise = app_state.get("exercise", {})
        slug = exercise.get("slug", "")
        if slug == "accord_participe_passe":
            all_q = db.get_accord_pp_questions(exercise["id"])
            random.shuffle(all_q)
            app_state["questions"] = all_q[:SESSION_LENGTH]
            self.app.show_frame("AccordPPScreen")
        elif slug == "english_fill_blanks":
            all_q = db.get_fill_blank_questions(exercise["id"])
            random.shuffle(all_q)
            app_state["questions"] = all_q[:SESSION_LENGTH]
            self.app.show_frame("QuizScreen")
        else:
            self.app.show_frame("VerbSelectionScreen")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    db.bootstrap()
    app = App()
    app.mainloop()
