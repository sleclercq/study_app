#!/usr/bin/env python3
"""
check_qcm.py - Runs the Python of the QCM exercises and checks their answers.

    python3 tools/check_qcm.py

A QCM that marks a wrong answer as right teaches the mistake the night before
the test: every question that shows code is checked by running it.

For every question of a `"kind": "qcm"` exercise under data/:
  - type "resultat": runs `code` and checks that what it prints is `canonical`
    (and therefore none of the four `wrong`). A code that stops on an error
    must have "Erreur (NameOfTheError)" as its answer, after what it printed
    before the error, if anything.
  - type "code": runs `code` (the beginning of the program shown with the
    question, may be empty) followed by each of the five choices, and checks
    that `canonical` prints exactly `output` and that no wrong choice does.
  - type "cours": nothing to run.
A question with "_check": false is skipped (random numbers, the clock...).

Each snippet runs in a fresh namespace, stdout captured, input() refused, two
seconds at most. These are our own exercise files: code we wrote, nothing else.
The GitHub workflow runs this before the build: a wrong answer is not published.
Standard library only.
"""

import builtins
import contextlib
import io
import json
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TIMEOUT_SECONDS = 2


def exercise_files(data_dir: Path) -> list:
    """Same rule as the build: data/**/*.json, "_" folders never read."""
    return sorted(
        path for path in data_dir.rglob("*.json")
        if not any(part.startswith("_") for part in path.relative_to(data_dir).parts)
    )


class Timeout(Exception):
    pass


def _no_input(*_args, **_kwargs):
    raise RuntimeError("input() n'est pas utilisable dans une question vérifiée")


def run(source: str) -> str:
    """What the console shows: the printed lines, then "Erreur (X)" if it stopped on X."""
    out = io.StringIO()
    namespace = {"__name__": "__main__", "__builtins__": {**vars(builtins), "input": _no_input}}

    def alarm(_signum, _frame):
        raise Timeout()

    previous = signal.signal(signal.SIGALRM, alarm)
    signal.alarm(TIMEOUT_SECONDS)
    error = None
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(source, "<question>", "exec"), namespace)
    except Timeout:
        error = "Timeout"
    except BaseException as exc:          # SyntaxError and KeyboardInterrupt included
        error = type(exc).__name__
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    printed = out.getvalue().rstrip("\n")
    if error is None:
        return printed
    return f"{printed}\nErreur ({error})" if printed else f"Erreur ({error})"


def check_question(question: dict, where: str) -> list:
    kind = question.get("type", "cours")
    if kind == "cours" or question.get("_check") is False:
        return []
    right = question["canonical"]
    if kind == "resultat":
        actual = run(question["code"])
        if actual != right:
            return [f"{where} : le code affiche {actual!r}, la bonne réponse indiquée est {right!r}."]
        return []
    if kind == "code":
        context = question.get("code", "")
        expected = question["output"]
        problems = []
        actual = run(f"{context}\n{right}" if context else right)
        if actual != expected:
            problems.append(f"{where} : la bonne réponse affiche {actual!r} au lieu de {expected!r}.")
        for choice in question["wrong"]:
            if run(f"{context}\n{choice}" if context else choice) == expected:
                problems.append(f"{where} : la mauvaise réponse {choice!r} affiche aussi le résultat attendu.")
        return problems
    return [f"{where} : type {kind!r} inconnu."]


def main() -> int:
    problems = []
    checked = 0
    for path in exercise_files(DATA_DIR):
        try:
            exercise = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue                      # the build reports it
        if not isinstance(exercise, dict) or exercise.get("kind") != "qcm":
            continue
        for number, question in enumerate(exercise.get("words", []), start=1):
            where = f"{path.relative_to(ROOT)}, question n°{number} ({question.get('source', '')[:50]})"
            found = check_question(question, where)
            problems.extend(found)
            checked += question.get("type", "cours") != "cours" and question.get("_check") is not False
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} problème(s) dans les QCM : le site ne doit pas être publié ainsi.", file=sys.stderr)
        return 1
    print(f"QCM vérifiés : {checked} questions avec du code, toutes les réponses sont justes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
