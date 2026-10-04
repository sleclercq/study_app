#!/usr/bin/env python3
"""
build_site.py - Builds the website: web/ + data/ -> _site/.

    python3 tools/build_site.py            # build into _site/
    python3 tools/build_site.py --serve    # build, then serve on http://localhost:8000

The GitHub workflow (.github/workflows/site.yml) runs this same build on every
push to main and publishes _site/ on GitHub Pages: nothing else to do.

What it does:
  - reads every exercise file under data/ with the rule of the desktop app
    (db._exercise_files): any *.json, folders starting with "_" skipped;
  - checks them, and stops with a readable message rather than publish a
    broken site (the version already online then simply stays);
  - writes _site/exercises.json: every exercise with only the fields the site
    reads (the "_notes", "_carnet"... documentation fields stay in the repo);
  - copies web/ and stamps a build id on the file names, so that a phone never
    mixes the files of two publications.

Standard library only: nothing to install, here or on the GitHub runner.
"""

import argparse
import functools
import hashlib
import http.server
import json
import mimetypes
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"
DEFAULT_OUT = ROOT / "_site"

# Left behind in every build, so that --out never wipes a folder it did not create.
MARKER = ".build_site"

# Files of web/ that are not part of the site.
NOT_PUBLISHED = {"package.json"}

# Exercise metadata read by the site, with the defaults of db._EXERCISE_META.
META_DEFAULTS = {
    "level": "",
    "kind": "forms",
    "sort_order": 100,
    "color": "#4a7c59",
    "button_label": "",
    "source_language": "",
    "target_language": "",
    "source_lang_code": "",
    "target_lang_code": "",
    "canonical_prompt": "",
    "reverse_prompt": "",
    "form_prompt": "",
}

KINDS = {"forms", "triple", "vocab", "leitner", "sentences", "accord_pp"}
ACCORD_CASES = {"sans_auxiliaire", "avec_etre", "avoir_cod_apres", "avoir_cod_avant"}
TRIPLE_LABELS = {"base verbale", "prétérit", "participe passé"}


def exercise_files(data_dir: Path) -> list:
    """Same rule as db._exercise_files: data/**/*.json, "_" folders never read."""
    return sorted(
        path for path in data_dir.rglob("*.json")
        if not any(part.startswith("_") for part in path.relative_to(data_dir).parts)
    )


def check_exercise(exercise, where: str) -> list:
    """Problems that would break the exercise on the site (empty list = fine)."""
    if not isinstance(exercise, dict):
        return [f"{where} : le fichier doit contenir un objet JSON {{...}}."]
    errors = []
    for key in ("slug", "name"):
        if not isinstance(exercise.get(key), str) or not exercise.get(key).strip():
            errors.append(f'{where} : champ "{key}" manquant ou vide.')
    kind = exercise.get("kind", META_DEFAULTS["kind"])
    if kind not in KINDS:
        errors.append(f'{where} : kind "{kind}" inconnu (attendu : {", ".join(sorted(KINDS))}).')
    words = exercise.get("words")
    if not isinstance(words, list):
        return errors + [f'{where} : "words" doit être une liste.']

    for number, word in enumerate(words, start=1):
        at = f"{where}, mot n°{number}"
        if not isinstance(word, dict):
            errors.append(f"{at} : doit être un objet {{...}}.")
            continue
        for key in ("source", "canonical"):
            if not isinstance(word.get(key), str):
                errors.append(f'{at} : champ "{key}" manquant (texte attendu, "" si vide).')
        forms = word.get("forms", [])
        if not isinstance(forms, list) or any(
            not isinstance(f, dict) or not isinstance(f.get("label"), str) or not isinstance(f.get("value"), str)
            for f in forms
        ):
            errors.append(f'{at} : "forms" doit être une liste de {{"label": ..., "value": ...}}.')
            continue
        for key in ("alt_source", "alt_target"):
            if not isinstance(word.get(key, []), list) or any(not isinstance(v, str) for v in word.get(key, [])):
                errors.append(f'{at} : "{key}" doit être une liste de textes.')
        labels = {f["label"]: f["value"] for f in forms}
        if kind == "accord_pp" and labels.get("__case__") not in ACCORD_CASES:
            errors.append(f'{at} : __case__ "{labels.get("__case__", "")}" inconnu '
                          f'(attendu : {", ".join(sorted(ACCORD_CASES))}).')
        if kind == "triple" and not TRIPLE_LABELS <= set(labels):
            errors.append(f'{at} : il faut les trois formes {", ".join(sorted(TRIPLE_LABELS))}.')
    return errors


def warnings_for(exercise, where: str) -> list:
    """Not blocking, but worth a look: the classic traps of a vocabulary list."""
    if exercise.get("kind") not in ("vocab", "leitner", "forms", "triple"):
        return []
    found = []
    seen_pairs = set()
    translations = {}
    for word in exercise["words"]:
        pair = (word["source"], word["canonical"])
        if pair in seen_pairs:
            found.append(f"{where} : « {word['source']} » est en double (même traduction) : "
                         "les deux partagent la même progression.")
        seen_pairs.add(pair)
        translations.setdefault(word["source"], set()).add(word["canonical"])
    ambiguous = [source for source, canonicals in translations.items() if len(canonicals) > 1]
    if exercise.get("kind") in ("vocab", "leitner") and ambiguous:
        examples = ", ".join(f"« {source} »" for source in ambiguous[:4])
        found.append(f"{where} : {len(ambiguous)} mot(s) français ont plusieurs traductions ({examples}...) : "
                     "dans le sens français -> langue étrangère, impossible de deviner laquelle est attendue. "
                     "Préciser entre parenthèses, ou accepter l'autre via alt_target.")
    return found


def slim_word(word: dict) -> dict:
    """Only what the site reads: the "_..." documentation fields stay in the repo."""
    out = {"source": word["source"], "canonical": word["canonical"]}
    if word.get("theme"):
        out["theme"] = word["theme"]
    forms = [{"label": f["label"], "value": f["value"]} for f in word.get("forms", [])]
    if forms:
        out["forms"] = forms
    for key in ("alt_source", "alt_target"):
        if word.get(key):
            out[key] = list(word[key])
    return out


def load_exercises(data_dir: Path):
    """(exercises for the site, errors, warnings)."""
    exercises, errors, warnings = [], [], []
    slugs = {}
    for path in exercise_files(data_dir):
        where = str(path.relative_to(data_dir.parent))
        try:
            exercise = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            errors.append(f"{where} : JSON invalide, ligne {error.lineno} colonne {error.colno} ({error.msg}).")
            continue
        problems = check_exercise(exercise, where)
        if problems:
            errors.extend(problems)
            continue
        slug = exercise["slug"]
        if slug in slugs:
            errors.append(f'{where} : le slug "{slug}" est déjà celui de {slugs[slug]}.')
            continue
        slugs[slug] = where
        warnings.extend(warnings_for(exercise, where))

        site_exercise = {"slug": slug, "name": exercise["name"]}
        for key, default in META_DEFAULTS.items():
            value = exercise.get(key)
            site_exercise[key] = default if value is None else value
        site_exercise["button_label"] = site_exercise["button_label"] or exercise["name"]
        site_exercise["words"] = [slim_word(word) for word in exercise["words"]]
        exercises.append(site_exercise)
    return exercises, errors, warnings


def stamp(text: str, suffix: str, build: str) -> str:
    """Put the build id on the local file names a page or a module refers to."""
    text = text.replace("__BUILD__", build)
    if suffix == ".js":
        return re.sub(r'(\bfrom\s+["\'])(\./[^"\'?]+\.js)(["\'])', rf"\g<1>\g<2>?v={build}\g<3>", text)
    if suffix == ".html":
        return re.sub(r'(\b(?:src|href)=")([^":?#]+\.(?:js|css))(")', rf"\g<1>\g<2>?v={build}\g<3>", text)
    return text


def build(out: Path) -> str:
    exercises, errors, warnings = load_exercises(DATA_DIR)
    for warning in warnings:
        print(f"attention : {warning}")
    if errors:
        print("\nLe site n'est PAS construit (la version en ligne ne change pas) :", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)

    catalog = json.dumps({"exercises": exercises}, ensure_ascii=False, separators=(",", ":"))
    web_files = sorted(
        path for path in WEB_DIR.rglob("*")
        if path.is_file() and path.name not in NOT_PUBLISHED and not path.name.startswith(".")
    )
    digest = hashlib.sha256(catalog.encode("utf-8"))
    for path in web_files:
        digest.update(str(path.relative_to(WEB_DIR)).encode("utf-8"))
        digest.update(path.read_bytes())
    build_id = digest.hexdigest()[:10]

    if out.exists():
        if not (out / MARKER).exists():
            sys.exit(f"{out} existe et n'a pas été créé par ce script : je ne l'efface pas.")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / MARKER).write_text("Dossier généré par tools/build_site.py, effacé à chaque build.\n", encoding="utf-8")

    for path in web_files:
        target = out / path.relative_to(WEB_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix in (".html", ".js", ".css"):
            target.write_text(stamp(path.read_text(encoding="utf-8"), path.suffix, build_id), encoding="utf-8")
        else:
            shutil.copyfile(path, target)
    (out / "exercises.json").write_text(
        json.dumps({"build": build_id, "exercises": exercises}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    words = sum(len(e["words"]) for e in exercises)
    print(f"Site construit dans {out} : {len(exercises)} exercices, {words} mots ou phrases, build {build_id}.")
    return build_id


def serve(out: Path, port: int) -> None:
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    mimetypes.add_type("text/javascript", ".js")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"Aperçu sur http://localhost:{port}/  (Ctrl+C pour arrêter)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Construit le site de révisions dans _site/.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="dossier de sortie (défaut : _site/)")
    parser.add_argument("--serve", action="store_true", help="puis le servir en local pour l'essayer")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    out = args.out.resolve()
    build(out)
    if args.serve:
        serve(out, args.port)


if __name__ == "__main__":
    main()
