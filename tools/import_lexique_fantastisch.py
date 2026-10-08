#!/usr/bin/env python3
"""
tools/import_lexique_fantastisch.py - Lexique du manuel Fantastisch! Neu -> exercice.

Transforme les pages « Lexique allemand-français » du manuel (PDF fournis par la
professeure) en fichier d'exercice pour l'appli, dans l'ordre du manuel :
une année après l'autre, unité par unité.

    python3 tools/import_lexique_fantastisch.py \\
        --annee 6e data/_sources/allemand/manuel_fantastisch_neu/1re_annee_6e/lexique_*.pdf \\
        --annee 5e data/_sources/allemand/manuel_fantastisch_neu/2e_annee_5e/lexique_*.pdf \\
        --sortie data/allemand/rattrapage_6e_5e.json

Besoin de pdftohtml (brew install poppler). Si le fichier de sortie existe, son
en-tête (slug, nom, consignes...) est conservé et seule la liste "words" est
régénérée. Relancer l'outil est sans danger pour les progrès des enfants tant
que les mots ne changent pas : un mot est reconnu par son couple français +
allemand. Un mot corrigé devient un nouveau mot, l'ancien est retiré du jeu.

Comment le lexique est lu (voir le XML produit par pdftohtml -xml) :
  - allemand en gras, français en romain, unité en couleur après « | »
    ("Abend (-e), der" / "soir, soirée" / U5) ;
  - verbe à particule : "ab" | "räumen (abgeräumt)" -> "abräumen (abgeräumt)" ;
  - « | U2 | U7 » : le mot revient dans une unité suivante, on garde la première ;
  - la ligature « ff » du PDF est le caractère privé U+E61F ;
  - l'encadré d'explication en haut de la première page n'est pas une entrée,
    ni les numéros de page écrits en lettres (« hundertvierzehn ») ;
  - le lexique inverse (français-allemand), s'il suit, est ignoré : c'est un
    index des mêmes mots, avec le gras inversé ;
  - les coquilles du manuel sont corrigées par TYPOS avant tout traitement :
    lettre oubliée (« Freizeitaktität »), virgule avant le pluriel
    (« Mädchen, (-) das » donnait « Mädchen, das » au lieu de « das Mädchen »),
    espace manquante après « / » (« erste / erster /erstes » donnait la seule
    réponse « erster /erstes » au lieu de « erster » et « erstes ») ;
  - un même français pour plusieurs allemands (« café » = Kaffee / Café) : dans
    le sens français -> allemand, l'enfant ne peut pas deviner lequel est
    attendu. Chaque cas est tranché à la main dans SENS (précision entre
    parenthèses) ou SYNONYMES (chacun accepte les autres) ; un cas non tranché
    est listé en fin d'import, et build_site.py le signale à chaque build.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

FF_LIGATURE = "\ue61f"
UNIT_RE = re.compile(r"^(U\d+|DF)$")
PAGE_NUMBER_RE = re.compile(r"^(\d+|(zwei)?hundert\w*)$")
REVERSE_INDEX_RE = re.compile(r"fran(ç|c)ais-allemand", re.I)
UNIT_LABELS = {"DF": "Fêtes"}

# Coquilles du manuel, corrigées avant tout traitement.
TYPOS = {
    "Freizeitaktität": "Freizeitaktivität",
    "Mädchen, (-) das": "Mädchen (-), das",     # virgule avant le pluriel : article non reconnu
    "erster /erstes": "erster / erstes",        # espace manquante : une seule réponse au lieu de deux
}

# Même français, sens différents : la précision est ajoutée entre parenthèses
# ("café" -> "café (boisson)"). Dans le sens allemand -> français, la
# parenthèse n'est jamais exigée (answers.js).
# {français du manuel: {allemand: précision}}
SENS = {
    "Salut !": {"Hallo!": "en arrivant", "Hi!": "en arrivant", "Tschüss!": "en partant"},
    "rose": {"rosa": "couleur", "rosig": "au figuré : un avenir rose"},
    "aimer": {"lieben": "adorer", "lieb haben": "tendrement"},
    "café": {"der Kaffee": "boisson", "das Café": "lieu"},
    "après": {"nach": "après l'école", "danach": "après ça"},
    "heure": {"die Uhrzeit": "l'heure qu'il est", "die Stunde": "durée"},
    "dîner": {"das Abendessen": "nom", "zu Abend essen": "verbe"},
    "déjeuner": {"das Mittagessen": "nom", "zu Mittag essen": "verbe"},
    "chat": {"die Katze": "animal", "der Chat": "en ligne"},
    "voleur / voleuse": {"der Räuber": "brigand", "der Dieb": "qui vole en cachette"},
    "motif": {"das Motiv": "sujet d'une image", "das Muster": "décor qui se répète"},
    "laver": {"waschen": "en général", "abwaschen (abgewaschen)": "la vaisselle"},
    "suspect / suspecte": {"verdächtig": "adjectif", "der Verdächtige (/ die)": "nom"},
    "échange": {"der Austausch": "scolaire", "der Tausch": "troc"},
    "toujours": {"immer": "tout le temps", "immer noch": "encore maintenant"},
    "par": {"pro … (einmal pro Woche)": "une fois par semaine", "durch": "à travers"},
    "célèbre": {"bekannt": "connu", "berühmt": "fameux"},
    "confortable": {"bequem": "vêtement, fauteuil", "gemütlich": "douillet"},
    "frais / fraîche": {"frisch": "du pain frais", "kühl": "un peu froid"},
    "foyer": {"der Aufenthaltsraum": "salle de détente", "das Foyer": "hall d'entrée"},
    "à gauche": {"nach links": "aller vers la gauche", "links": "se trouver à gauche"},
    "à droite": {"nach rechts": "aller vers la droite", "rechts": "se trouver à droite"},
}

# Même français, traductions qui se valent : chaque mot accepte les autres
# (alt_target). Français tel qu'il est après SENS.
SYNONYMES = {
    "Salut ! (en arrivant)",        # Hallo! / Hi!
    "club (scolaire)",              # die AG / die Arbeitsgemeinschaft
    "taille-crayon",                # der Anspitzer / der Spitzer
    "participer",                   # mitmachen / teilnehmen
    "aider",                        # helfen / mithelfen
    "salle de classe",              # das Klassenzimmer / der Klassenraum
    "carnaval",                     # der Karneval / der Fasching
    "choisir",                      # aussuchen / wählen
    "ensemble",                     # zusammen / gemeinsam
    "cent",                         # einhundert / hundert
    "mille",                        # eintausend / tausend
    "écologique",                   # umweltschonend / ökologisch
    "quartier",                     # der Stadtteil / das Stadtviertel
}

NOUN_RE = re.compile(
    r"^\s*(?P<word>[^,()/]+?)\s*(?:\((?P<pl>[^)]*)\))?\s*,\s*(?P<art>der|die|das)\b(?P<rest>.*)$")
NEXT_NOUN_RE = re.compile(
    r"^[/,]\s*(?P<word>[^,()/]+?)\s*(?:\((?P<pl>[^)]*)\))?\s*,\s*(?P<art>der|die|das)\b(?P<rest>.*)$")


# ---------------------------------------------------------------------------
# Lecture du PDF
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    text = text.replace(FF_LIGATURE, "ff").replace("\u2019", "'").replace("\u2018", "'")
    return " ".join(text.replace("\u00a0", " ").split())


def _runs(pdfs: list) -> list:
    """Morceaux de texte du lexique, dans l'ordre, avec leur mise en forme."""
    runs = []
    with tempfile.TemporaryDirectory() as tmp:
        for index, pdf in enumerate(pdfs):
            stem = Path(tmp) / f"page{index}"
            subprocess.run(["pdftohtml", "-xml", "-i", "-q", "-enc", "UTF-8", str(pdf), str(stem)],
                           check=True)
            root = ET.parse(f"{stem}.xml").getroot()
            fonts = {f.get("id"): (int(f.get("size")), f.get("color"), f.get("family"))
                     for f in root.iter("fontspec")}
            for t in root.iter("text"):
                size, color, family = fonts[t.get("font")]
                top, left = int(t.get("top")), int(t.get("left"))
                if index == 0 and top < 240 and left < 260:
                    continue            # encadré « Ce lexique comprend... » de la 1re page
                text = _clean("".join(t.itertext()))
                if text:
                    runs.append(dict(text=text, bold=t.find("b") is not None,
                                     size=size, color=color, family=family))
    return runs


def raw_entries(pdfs: list) -> list:
    """[{"de": ..., "fr": ..., "units": [...]}] dans l'ordre du lexique."""
    runs = _runs(pdfs)
    entries, de, fr, glue = [], [], [], False

    def is_body(run):
        return (run["color"] == "#231f20" and run["size"] in (8, 9, 10)
                and "Dingbats" not in run["family"])

    for i, run in enumerate(runs):
        text = run["text"]
        if REVERSE_INDEX_RE.search(text):
            break
        if run["size"] == 6 and UNIT_RE.match(text):
            if de or fr:
                entries.append({"de": " ".join(de), "fr": " ".join(fr), "units": [text]})
                de, fr = [], []
            elif entries:
                entries[-1]["units"].append(text)
            continue
        if text == "|":
            between_bold = (i > 0 and runs[i - 1]["bold"]
                            and i + 1 < len(runs) and runs[i + 1]["bold"])
            if between_bold and de:
                glue = True         # ab|räumen
            continue
        if not is_body(run):
            continue
        if not run["bold"] and PAGE_NUMBER_RE.match(text):
            continue            # "114 hundertvierzehn" en pied de page ; le mot "hundert", lui, est en gras
        if run["bold"]:
            if glue and de:
                de[-1] += text
                glue = False
            else:
                de.append(text)
        else:
            fr.append(text)
    return entries


# ---------------------------------------------------------------------------
# Mise en forme pour l'appli
# ---------------------------------------------------------------------------

def parse_german(de: str):
    """"Abend (-e), der" -> ("der Abend", [autres formes acceptées], "-e")"""
    de = de.strip()
    m = NOUN_RE.match(de)
    if m:
        nouns, rest, example = [(m["art"], m["word"].strip(), m["pl"] or "")], m["rest"], ""
        while rest.strip():
            rest = rest.strip()
            other = NEXT_NOUN_RE.match(rest)
            if other:           # "der / Brieffreundin (-nen), die", "das, Kaffee (Sg.), der"
                nouns.append((other["art"], other["word"].strip(), other["pl"] or ""))
                rest = other["rest"]
                continue
            ex = re.match(r"^\((?P<ex>[^)]*)\)(?P<rest>.*)$", rest)
            if ex:              # "die (Angst haben)"
                example = f"{example} {ex['ex']}".strip()
                rest = ex["rest"]
                continue
            example = f"{example} {rest}".strip()
            break
        article, word, plural = nouns[0]
        canonical = f"{article} {word}" + (f" ({example})" if example else "")
        return canonical, [f"{a} {w}" for a, w, _ in nouns[1:]], plural

    reflexive = re.match(r"^(?P<verb>[^,()]+?),\s*sich\b(?P<rest>.*)$", de)
    if reflexive:               # "bewegen, sich (bewegt)" -> "sich bewegen (bewegt)"
        verb = reflexive["verb"].strip()
        return f"sich {verb}{reflexive['rest']}".strip(), [verb], ""

    if " / " in de and "(" not in de:   # "andere / anderer / anderes"
        parts = [p.strip() for p in de.split(" / ") if p.strip()]
        return parts[0], parts[1:], ""
    return de, [], ""


def _split_outside_parens(text: str, seps=(",", " / ", " ou ")) -> list:
    pieces, depth, buf, i = [], 0, "", 0
    while i < len(text):
        c = text[i]
        depth += (c == "(") - (c == ")")
        sep = next((s for s in seps if depth == 0 and text.startswith(s, i)), None)
        if sep:
            pieces.append(buf)
            buf, i = "", i + len(sep)
            continue
        buf += c
        i += 1
    pieces.append(buf)
    return [p.strip() for p in pieces if p.strip()]


def _feminine(base: str, suffix: str) -> str:
    """actif+ive -> active, fermier+ière -> fermière, acteur+trice -> actrice."""
    if suffix == "e":
        return base + "e"
    cut = base.rfind(suffix[0])
    return (base[:cut] if cut > 0 else base) + suffix


def french_alternatives(fr: str) -> list:
    """Chaque sens séparé par une virgule, un « / » ou un « ! », masculin et féminin."""
    pieces = []
    for chunk in re.split(r"(?<=[!?])\s+(?=\S)", fr):     # "À bientôt ! À tout à l'heure !"
        pieces += _split_outside_parens(chunk)
    alts = set()
    for piece in pieces:
        alts.add(piece)
        if re.search(r"\w/\w", piece):                     # "chancelier/ière fédéral/e"
            masc, fem = [], []
            for token in piece.split(" "):
                m = re.match(r"^(?P<base>[\w'-]*\w)/(?P<suf>[a-zéèêàç]{1,5})$", token)
                masc.append(m["base"] if m else token)
                fem.append(_feminine(m["base"], m["suf"]) if m else token)
            alts.add(" ".join(masc))
            alts.add(" ".join(fem))
        bare = " ".join(re.sub(r"\(?\bqq(ch|n)\.?\)?", " ", piece).split())   # "bricoler qqch."
        if bare:
            alts.add(bare)
    alts.discard(fr)
    return sorted(alts)


def ambiguous_french(words: list) -> dict:
    """{français: [mots]} pour chaque français qui a plusieurs traductions allemandes."""
    groups: dict = {}
    for word in words:
        groups.setdefault(word["source"], []).append(word)
    return {french: group for french, group in groups.items()
            if len({w["canonical"] for w in group}) > 1}


def build_words(years: list) -> list:
    """years: [("6e", [pdf, ...]), ("5e", [...])] dans l'ordre de progression."""
    words, by_german = [], {}
    for year_rank, (year, pdfs) in enumerate(years):
        for entry in raw_entries(pdfs):
            for bad, good in TYPOS.items():
                entry["de"] = entry["de"].replace(bad, good)
            canonical, alt_de, plural = parse_german(entry["de"])
            fr, unit = entry["fr"].strip(), entry["units"][0]
            key = re.sub(r"\s*\([^)]*\)", "", canonical).lower()

            if key in by_german:            # déjà appris une année précédente
                word = by_german[key]
                word["alt_source"] = sorted(set(word.get("alt_source", [])) | {fr}
                                            | set(french_alternatives(fr)))
                word["_aussi"] = word.get("_aussi", []) + [f"{year} {unit}"]
                continue

            word = {
                "theme": f"{year} - " + (UNIT_LABELS.get(unit) or f"Unité {unit[1:]}"),
                "source": fr,
                "canonical": canonical,
                "_annee": year, "_unite": unit, "_brut": entry["de"],
                "_rang": (year_rank, 99 if unit == "DF" else int(unit[1:])),
            }
            if len(entry["units"]) > 1:
                word["_aussi"] = [f"{year} {u}" for u in entry["units"][1:]]
            if plural:
                word["_pluriel"] = plural
            if alt_de:
                word["alt_target"] = alt_de
            alternatives = french_alternatives(fr)
            if alternatives:
                word["alt_source"] = alternatives
            words.append(word)
            by_german[key] = word

    words.sort(key=lambda w: w["_rang"])        # stable : alphabétique dans chaque unité

    # Même français pour plusieurs mots allemands : sens précisé (SENS), ou
    # traductions acceptées l'une pour l'autre (SYNONYMES). Un cas qui n'est ni
    # l'un ni l'autre reste tel quel, pour que build_site.py le signale.
    for word in words:
        precision = SENS.get(word["source"], {}).get(word["canonical"])
        if precision:
            word["source"] = f"{word['source']} ({precision})"
    for french, group in ambiguous_french(words).items():
        if french in SYNONYMES:
            for word in group:
                others = {o["canonical"] for o in group if o is not word}
                word["alt_target"] = sorted(set(word.get("alt_target", [])) | others)

    for word in words:
        del word["_rang"]
        word["forms"] = []
    return words


DEFAULT_HEADER = {
    "slug": "allemand_rattrapage",
    "name": "Allemand - Rattrapage 6e et 5e",
    "level": "4e",
    "kind": "leitner",
    "sort_order": 20,
    "color": "#6a8a5a",
    "button_label": "Allemand - Rattrapage 6e et 5e\n(lexique du manuel, méthode progressive)",
    "source_language": "Français",
    "target_language": "Allemand",
    "source_lang_code": "fr",
    "target_lang_code": "de",
    "canonical_prompt": "Traduis en allemand\u00a0: «\u00a0{source}\u00a0»",
    "reverse_prompt": "Traduis en français\u00a0: «\u00a0{canonical}\u00a0»",
    "form_prompt": "«\u00a0{source}\u00a0» - {label}",
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--annee", nargs="+", action="append", required=True,
                        metavar=("ANNEE", "PDF"),
                        help="libellé de l'année (6e, 5e...) puis ses PDF, dans l'ordre des pages")
    parser.add_argument("--sortie", required=True, type=Path)
    args = parser.parse_args(argv)

    years = [(group[0], [Path(p) for p in group[1:]]) for group in args.annee]
    words = build_words(years)

    header = dict(DEFAULT_HEADER)
    if args.sortie.exists():
        existing = json.loads(args.sortie.read_text(encoding="utf-8"))
        header = {k: v for k, v in existing.items() if k != "words"}
    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    args.sortie.write_text(json.dumps({**header, "words": words}, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8")

    per_theme: dict = {}
    for word in words:
        per_theme[word["theme"]] = per_theme.get(word["theme"], 0) + 1
    print(f"{len(words)} mots écrits dans {args.sortie}")
    for theme, count in per_theme.items():
        print(f"  {theme:20} {count:4}")

    undecided = {french: group for french, group in ambiguous_french(words).items()
                 if french not in SYNONYMES}
    if undecided:
        print(f"\nÀ TRANCHER : {len(undecided)} mot(s) français ont plusieurs traductions, "
              "à ajouter dans SENS ou SYNONYMES puis relancer :")
        for french, group in undecided.items():
            print(f"  « {french} » : " + " / ".join(w["canonical"] for w in group))
    return 0


if __name__ == "__main__":
    sys.exit(main())
