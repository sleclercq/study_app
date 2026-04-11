"""
main.py - Entry point and full UI for the Latin revision app.

Run with:  python main.py   (or ./run.sh)

Architecture:
  - Single tkinter.Tk window.
  - Four Frame subclasses act as "screens" stacked in the same grid cell:
      PlayerScreen       - choose or create a player
      VerbSelectionScreen- checkboxes to pick which verbs to practice (per player, persisted)
      QuizScreen         - 20-question quiz with attempt logic, hints, and scoring
      ResultsScreen      - final score + full scrollable session history
  - show_frame(name) swaps the visible screen by raising the chosen frame.
  - A shared app_state dict carries context between screens (player, exercise, questions).

Navigation flow:
  PlayerScreen -> VerbSelectionScreen -> QuizScreen -> ResultsScreen
                       ^                                   |
                       |___________ Rejouer ________________|
  PlayerScreen <------ Changer de joueur -------------------|

Key-binding strategy:
  Enter and Space are bound at the root window level by QuizScreen.on_show(),
  and unbound by QuizScreen._end_session() before switching away. This prevents
  those keys from accidentally firing on other screens.
  The Continue button intentionally does NOT receive focus after feedback so that
  Space does not double-fire (button-space-activation + root binding).

Scoring rules (QuizScreen._check_answer):
  - Correct on attempt 1: +1.0 point
  - Correct on attempt 2: +0.5 point
  - Correct on attempt 3: +0.25 point
  - All 3 wrong:          +0.0 point, reveal correct answer

Hint rules (QuizScreen._check_answer, after wrong attempt):
  - After attempt 1 wrong: show first 2 letters of answer
  - After attempt 2 wrong: show first 4 letters (or len-1 if answer is <= 4 chars)

Extensibility notes:
  - To add a new screen: define a Frame subclass, register it in App.build_frames(),
    call show_frame("ClassName") from wherever it should appear.
  - To support multiple exercises: add an ExerciseScreen after PlayerScreen and set
    app_state["exercise"] there; VerbSelectionScreen and QuizScreen use whatever
    exercise is in app_state.
  - Scoring and hint rules live only in QuizScreen._check_answer() — edit there.

Styling constants (fonts, colours) are class-level attributes for easy theming.
"""

import tkinter as tk
from tkinter import messagebox
import random
from datetime import datetime

import db

# ---------------------------------------------------------------------------
# Shared application state passed between screens
# ---------------------------------------------------------------------------
# Keys set at runtime:
#   player           : dict {id, name}
#   exercise         : dict {id, slug, name}
#   enabled_word_ids : list of int — word IDs the player chose to practice
#   questions        : list of question dicts for the current session
#   last_score       : float — score from the most recent completed session
#   last_total       : int   — number of questions in that session
app_state: dict = {}

# Slug of the exercise loaded at startup. When an exercise-selection screen is
# added, this default becomes the fallback or is removed entirely.
DEFAULT_EXERCISE_SLUG = "latin_verbs_present"

# Target number of questions per session. Actual count may be lower if the
# player selected very few verbs (each verb contributes at most 7 questions).
SESSION_LENGTH = 20


# ---------------------------------------------------------------------------
# App shell
# ---------------------------------------------------------------------------

class App(tk.Tk):
    """
    Root window. Owns the frame stack and exposes show_frame().

    To add a new screen:
      1. Define a Frame subclass below.
      2. Add the class to the tuple in build_frames().
      3. Call self.app.show_frame("YourClassName") from any other screen.
    """

    def __init__(self):
        super().__init__()
        self.title("Révision Latin")
        self.resizable(False, False)
        self._center_window(width=640, height=520)

        self._frames: dict = {}
        self.build_frames()
        self.show_frame("PlayerScreen")

    def _center_window(self, width: int, height: int) -> None:
        """Place the window at the centre of the primary screen."""
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

    def build_frames(self) -> None:
        """
        Instantiate all screens and stack them in the same grid cell (z-order swap).
        Add new screens to this tuple.
        """
        container = tk.Frame(self)
        container.pack(fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        for FrameClass in (PlayerScreen, VerbSelectionScreen, QuizScreen, ResultsScreen):
            frame = FrameClass(parent=container, app=self)
            self._frames[FrameClass.__name__] = frame
            frame.grid(row=0, column=0, sticky="nsew")

    def show_frame(self, name: str) -> None:
        """
        Raise the named frame to the front and call its on_show() to refresh content.
        """
        frame = self._frames[name]
        frame.tkraise()
        if hasattr(frame, "on_show"):
            frame.on_show()


# ---------------------------------------------------------------------------
# Screen 1: Player selection
# ---------------------------------------------------------------------------

class PlayerScreen(tk.Frame):
    """
    Child picks their name from a list or creates a new player, then proceeds
    to verb selection.

    Layout: title | player listbox | new-player entry + button | Commencer button
    """

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

        tk.Label(self, text="Révision Latin", font=self.TITLE_FONT,
                 bg=self.BG, fg="#3a2a0a").pack(pady=(0, 20))

        tk.Label(self, text="Choisis ton prénom :", font=self.LABEL_FONT,
                 bg=self.BG, anchor="w").pack(fill="x")

        # Scrollable player list
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

        # New player row
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
            bg="#4a7c59", fg="white", activebackground="#3a6349",
            state="disabled", command=self._start, pady=8,
        )
        self._start_btn.pack(fill="x")

    def on_show(self) -> None:
        """Refresh player list each time this screen is raised."""
        self._listbox.delete(0, "end")
        for p in db.list_players():
            self._listbox.insert("end", p["name"])
        self._start_btn.config(state="disabled")

    def _on_player_selected(self, _event=None) -> None:
        if self._listbox.curselection():
            self._start_btn.config(state="normal")

    def _add_player(self) -> None:
        """Create a new player and auto-select them in the list."""
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
        """Set player + exercise in app_state, then go to verb selection."""
        sel = self._listbox.curselection()
        if not sel:
            return

        player = db.get_or_create_player(self._listbox.get(sel[0]))
        app_state["player"] = player

        exercise = db.get_exercise_by_slug(DEFAULT_EXERCISE_SLUG)
        if exercise is None:
            messagebox.showerror("Erreur", "Exercice introuvable. Vérifie les fichiers data/.")
            return
        app_state["exercise"] = exercise

        self.app.show_frame("VerbSelectionScreen")


# ---------------------------------------------------------------------------
# Screen 2: Verb selection (per-player, persisted)
# ---------------------------------------------------------------------------

class VerbSelectionScreen(tk.Frame):
    """
    Displays all verbs in the exercise as a scrollable checklist.
    The player can uncheck any verb they don't want to practice.
    Preferences are saved to the DB (player_word_prefs table) and reloaded
    each time this screen is shown, so they persist across sessions.

    Only checked verbs generate questions. A minimum of 1 verb must be checked.

    Layout:
      title | scrollable checkboxes | Tout cocher / Tout décocher | Commencer | Retour
    """

    BG        = "#f5f0e8"
    TITLE_FONT= ("Helvetica", 16, "bold")
    VERB_FONT = ("Helvetica", 13)
    BTN_FONT  = ("Helvetica", 13)

    def __init__(self, parent, app):
        super().__init__(parent, bg=self.BG)
        self.app = app
        # Maps word_id -> BooleanVar (one per word, built in on_show)
        self._checks: dict = {}
        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(padx=30, pady=16)

        tk.Label(self, text="Choisir les verbes à réviser",
                 font=self.TITLE_FONT, bg=self.BG, fg="#3a2a0a").pack(pady=(0, 8))

        # Scrollable checkbox area
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

        # Mouse-wheel scroll
        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)

        # Quick-select row
        sel_row = tk.Frame(self, bg=self.BG)
        sel_row.pack(fill="x", pady=(0, 8))
        tk.Button(sel_row, text="Tout cocher", font=self.BTN_FONT,
                  command=self._check_all).pack(side="left", padx=(0, 8))
        tk.Button(sel_row, text="Tout décocher", font=self.BTN_FONT,
                  command=self._uncheck_all).pack(side="left")

        # Action buttons
        btn_row = tk.Frame(self, bg=self.BG)
        btn_row.pack(fill="x")

        tk.Button(btn_row, text="← Retour", font=self.BTN_FONT,
                  command=lambda: self.app.show_frame("PlayerScreen")
                  ).pack(side="left", padx=(0, 8))

        self._start_btn = tk.Button(
            btn_row, text="Commencer  ▶", font=("Helvetica", 14, "bold"),
            bg="#4a7c59", fg="white", activebackground="#3a6349",
            command=self._start, pady=6,
        )
        self._start_btn.pack(side="left", expand=True, fill="x")

    def on_show(self) -> None:
        """Reload words and preferences, rebuild the checkbox list."""
        player = app_state.get("player", {})
        exercise = app_state.get("exercise", {})
        if not player or not exercise:
            return

        # Destroy previous checkboxes
        for w in self._cb_frame.winfo_children():
            w.destroy()
        self._checks.clear()

        prefs = db.get_word_prefs(player["id"], exercise["id"])

        # Build two columns of checkboxes for a compact layout
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
        """Disable Commencer if no verb is checked."""
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
        """Save preferences, build filtered question pool, launch quiz."""
        player = app_state["player"]
        exercise = app_state["exercise"]

        # Persist the current checkbox state for this player.
        prefs = {wid: var.get() for wid, var in self._checks.items()}
        db.save_word_prefs(player["id"], prefs)

        enabled_ids = [wid for wid, enabled in prefs.items() if enabled]
        app_state["enabled_word_ids"] = enabled_ids

        all_q = db.get_questions_for_exercise(exercise["id"], enabled_word_ids=enabled_ids)
        random.shuffle(all_q)
        # Use up to SESSION_LENGTH questions; fewer if the player selected very few verbs.
        app_state["questions"] = all_q[:SESSION_LENGTH]

        self.app.show_frame("QuizScreen")


# ---------------------------------------------------------------------------
# Screen 3: Quiz
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
      - Score is a float displayed as "17", "17.5", or "17.25" as needed.

    Keyboard shortcuts (bound at root window level in on_show, unbound in _end_session):
      Enter  - submit answer (while answering) OR advance to next question (after feedback)
      Space  - advance to next question (after feedback only)

    Note on space/enter binding:
      The Continue button does NOT receive focus after feedback (_show_continue gives
      focus to the frame instead). This prevents the button's built-in space-activation
      from double-firing when the root <space> binding also fires.
    """

    BG            = "#f5f0e8"
    HEADER_FONT   = ("Helvetica", 11)
    PROMPT_FONT   = ("Helvetica", 16, "bold")
    ENTRY_FONT    = ("Helvetica", 15)
    FEEDBACK_FONT = ("Helvetica", 13)
    HINT_FONT     = ("Helvetica", 12, "italic")
    BTN_FONT      = ("Helvetica", 13)
    CONTINUE_FONT = ("Helvetica", 13, "bold")

    COLOR_CORRECT = "#1a7a2a"   # green
    COLOR_WRONG   = "#b22222"   # red
    COLOR_HINT    = "#7a5500"   # amber for hints
    COLOR_REVEAL  = "#1a4a8a"   # blue for revealed answer
    COLOR_NEUTRAL = "#3a2a0a"

    def __init__(self, parent, app):
        super().__init__(parent, bg=self.BG)
        self.app = app

        # Per-session state (reset in on_show)
        self._questions: list = []
        self._q_index: int = 0
        self._attempts: int = 0
        self._score: float = 0.0
        self._answered: bool = False  # True while waiting for "continue" input

        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(padx=40, pady=20)

        # Header: player name (left) + question counter (right, always visible)
        header = tk.Frame(self, bg=self.BG)
        header.pack(fill="x", pady=(0, 10))
        self._player_label = tk.Label(header, text="", font=self.HEADER_FONT,
                                      bg=self.BG, fg="#666")
        self._player_label.pack(side="left")
        self._counter_label = tk.Label(header, text="", font=self.HEADER_FONT,
                                       bg=self.BG, fg="#666")
        self._counter_label.pack(side="right")

        tk.Frame(self, bg="#ccc", height=1).pack(fill="x", pady=(0, 20))

        # Question prompt
        self._prompt_label = tk.Label(
            self, text="", font=self.PROMPT_FONT, bg=self.BG,
            fg=self.COLOR_NEUTRAL, wraplength=540, justify="center",
        )
        self._prompt_label.pack(pady=(10, 20))

        # Answer entry + submit
        entry_frame = tk.Frame(self, bg=self.BG)
        entry_frame.pack(fill="x", pady=(0, 10))
        self._answer_var = tk.StringVar()
        self._entry = tk.Entry(entry_frame, textvariable=self._answer_var,
                               font=self.ENTRY_FONT, width=26)
        self._entry.pack(side="left", padx=(0, 10))
        # Note: Return is bound at root level in on_show(), not here, to stay active
        # even when the entry is disabled.
        self._submit_btn = tk.Button(entry_frame, text="Valider", font=self.BTN_FONT,
                                     command=self._check_answer)
        self._submit_btn.pack(side="left")

        # Feedback line (correct / wrong message)
        self._feedback_label = tk.Label(
            self, text="", font=self.FEEDBACK_FONT, bg=self.BG,
            fg=self.COLOR_CORRECT, wraplength=540, justify="center",
        )
        self._feedback_label.pack(pady=(8, 2))

        # Hint / reveal line (shown below feedback)
        self._hint_label = tk.Label(
            self, text="", font=self.HINT_FONT, bg=self.BG, fg=self.COLOR_HINT,
        )
        self._hint_label.pack(pady=(0, 2))

        # Continue button — hidden while the student is answering
        self._continue_btn = tk.Button(
            self, text="Continuer  →", font=self.CONTINUE_FONT,
            bg="#4a7c59", fg="white", activebackground="#3a6349",
            command=self._next_question, pady=6,
        )
        self._continue_btn.pack(fill="x", pady=(16, 0))
        self._continue_btn.pack_forget()

    def on_show(self) -> None:
        """
        Reset session state and start the first question.
        Also registers Enter/Space at the root window level.
        These are unregistered in _end_session() so they don't leak to other screens.
        """
        self._questions = app_state.get("questions", [])
        self._q_index = 0
        self._score = 0.0
        player = app_state.get("player", {})
        self._player_label.config(text=f"Joueur : {player.get('name', '')}")

        # Bind keyboard shortcuts at root level so they work regardless of focus.
        root = self.winfo_toplevel()
        root.bind("<Return>", self._on_enter)
        root.bind("<space>", self._on_space)

        self._load_question()

    def _load_question(self) -> None:
        """Display the current question and reset per-question state."""
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
        """Root-level Return handler: submit or continue depending on state."""
        if self._answered:
            self._next_question()
        else:
            self._check_answer()

    def _on_space(self, _event=None) -> None:
        """Root-level Space handler: continue only when waiting after feedback."""
        if self._answered:
            self._next_question()

    def _check_answer(self) -> None:
        """
        Validate the student's answer and update state.

        Scoring: 1.0 / 0.5 / 0.25 / 0.0 for attempts 1 / 2 / 3 / exhausted.
        Hints:   show first 2 letters after attempt 1; first 4 (or len-1) after attempt 2.
        The entry field is NOT cleared on wrong so the child can correct in-place.
        """
        if self._answered:
            return

        raw = self._answer_var.get()
        answer = raw.strip().lower()
        q = self._questions[self._q_index]
        correct_lower = q["answer"].strip().lower()
        correct_display = q["answer"].strip()  # original case for display

        self._attempts += 1

        if answer == correct_lower:
            # --- Correct ---
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
            # --- All attempts exhausted: reveal answer ---
            self._feedback_label.config(text="\u2717  Pas cette fois\u2026", fg=self.COLOR_WRONG)
            self._hint_label.config(
                text=f"La bonne r\u00e9ponse \u00e9tait : {correct_display}",
                fg=self.COLOR_REVEAL,
                font=self.FEEDBACK_FONT,
            )
            self._show_continue()

        else:
            # --- Wrong, attempts remain: give a hint ---
            remaining = 3 - self._attempts
            s = "essai" if remaining == 1 else "essais"
            self._feedback_label.config(
                text=f"\u2717  Pas tout \u00e0 fait\u2026 encore {remaining} {s}.",
                fg=self.COLOR_WRONG,
            )

            # Build hint: attempt 1 -> 2 letters; attempt 2 -> 4 letters (or len-1)
            n = len(correct_display)
            if self._attempts == 1:
                hint_len = 2
            else:  # attempt 2
                hint_len = (n - 1) if n <= 4 else 4
            hint = correct_display[:hint_len]
            self._hint_label.config(
                text=f"Indice : {hint}\u2026",
                fg=self.COLOR_HINT,
                font=self.HINT_FONT,
            )

            # Keep field content; select all so typing replaces it cleanly.
            self._entry.focus_set()
            self._entry.select_range(0, "end")

    def _show_continue(self) -> None:
        """
        Lock the entry, reveal the Continue button.
        Focus goes to the frame (not the button) to prevent Space double-fire:
        a focused button activates on Space natively AND the root binding would fire.
        """
        self._answered = True
        self._entry.config(state="disabled")
        self._submit_btn.config(state="disabled")
        self._continue_btn.pack(fill="x", pady=(16, 0))
        self.focus_set()  # frame focus — intentionally NOT the continue button

    def _next_question(self) -> None:
        """Move to the next question, or end the session if all done."""
        if not self._answered:
            return  # guard: ignore accidental calls while still answering
        self._q_index += 1
        if self._q_index >= len(self._questions):
            self._end_session()
        else:
            self._load_question()

    def _end_session(self) -> None:
        """Save the session score and transition to the results screen."""
        # Unregister keyboard shortcuts before leaving so they don't fire on ResultsScreen.
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
# Screen 4: Results
# ---------------------------------------------------------------------------

class ResultsScreen(tk.Frame):
    """
    Shows the session score and a scrollable history of all past sessions for
    this player + exercise. No cap on the number of rows shown.

    Buttons:
      Rejouer          -> VerbSelectionScreen (same player, re-pick verbs if desired)
      Changer de joueur-> PlayerScreen
    """

    BG         = "#f5f0e8"
    SCORE_FONT = ("Helvetica", 42, "bold")
    MSG_FONT   = ("Helvetica", 14)
    HIST_FONT  = ("Helvetica", 12)
    BTN_FONT   = ("Helvetica", 13)

    # Messages by score percentage (descending threshold order).
    # To add or change messages, edit this list.
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

        # History table: fixed-height canvas (not expand=True) so buttons stay visible.
        hist_outer = tk.Frame(self, bg=self.BG, bd=1, relief="groove")
        hist_outer.pack(fill="x", pady=(4, 10))

        canvas = tk.Canvas(hist_outer, bg=self.BG, highlightthickness=0, height=160)
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

        # Navigation buttons — always visible below the fixed-height canvas
        btn_row = tk.Frame(self, bg=self.BG)
        btn_row.pack(fill="x", pady=(0, 4))

        tk.Button(
            btn_row, text="Rejouer", font=self.BTN_FONT,
            bg="#4a7c59", fg="white", command=self._replay,
        ).pack(side="left", padx=(0, 8), expand=True, fill="x")

        tk.Button(
            btn_row, text="Changer de joueur", font=self.BTN_FONT,
            command=lambda: self.app.show_frame("PlayerScreen"),
        ).pack(side="left", expand=True, fill="x")

    def on_show(self) -> None:
        """Refresh score and history. Called by show_frame()."""
        score = app_state.get("last_score", 0.0)
        total = app_state.get("last_total", SESSION_LENGTH)

        # Display: whole number -> "20", otherwise strip trailing zeros ("17.5", "17.25")
        score_str = f"{score:.2f}".rstrip("0").rstrip(".")
        self._score_label.config(text=f"{score_str} / {total}")

        pct = round(score / total * 100) if total else 0
        msg = next(m for thr, m in self._MESSAGES if pct >= thr)
        self._msg_label.config(text=msg)

        self._populate_history()

    def _populate_history(self) -> None:
        """Rebuild the scrollable history rows from DB."""
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

        # Column headers
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
        """Go back to verb selection so the player can adjust their verb list."""
        self.app.show_frame("VerbSelectionScreen")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    db.bootstrap()
    app = App()
    app.mainloop()
