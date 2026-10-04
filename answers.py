"""
answers.py - Comparing what the child typed with what was expected.

Historically every screen did `given.strip().lower() == expected.strip().lower()`.
That is still the rule for Latin, French and English: those exercises pass no
language code and get exactly the old behaviour.

Vocabulary exercises need a little more tolerance, because the point of the
exercise is the foreign word, not the child's typing:

  German (lang="de")
    - ä/ö/ü/ß may be typed ae/oe/ue/ss (the official substitution, and what a
      French keyboard makes you do). "für" == "fuer".
    - the article stays mandatory: "der Tisch" is not satisfied by "Tisch".
      The gender is precisely what has to be learnt, so it is graded.

  French (lang="fr", i.e. the German -> French direction)
    - accents are ignored: "la fenetre" == "la fenêtre".
    - the leading article is optional: "table" == "la table".
      What is being tested is the German word's meaning, not French spelling.

Both directions also accept the synonyms listed in the JSON seed
(alt_source / alt_target), passed here as `accepted`.
"""

import re
import unicodedata

# ü -> ue etc. Applied after lowercasing, so only lowercase forms are needed.
_DE_SUBSTITUTIONS = (
    ("ä", "ae"),
    ("ö", "oe"),
    ("ü", "ue"),
    ("ß", "ss"),
)

# Dropped when they open a French answer ("l'école" -> "ecole").
_FR_LEADING_ARTICLES = (
    "le ", "la ", "les ", "l'", "un ", "une ", "des ",
    "du ", "de la ", "de l'", "de ", "d'",
)

# A parenthesis in a seeded answer disambiguates the prompt - "la fille (de
# quelqu'un)" tells the child which "fille" is being asked for in the FR -> DE
# direction. In the other direction the child obviously answers "la fille", so
# the parenthesis is never required.
_PAREN_RE = re.compile(r"\s*\([^)]*\)")

# Punctuation that never changes the answer, only the typing.
_TRIM_CHARS = " \t\n.,;:!?\"'«»"


def normalize(text: str) -> str:
    """
    Lowercase, trim outer punctuation/spaces, collapse inner whitespace.

    Ligatures are spelled out (œ -> oe), because no child types "l'œil" and
    that is a keyboard question, never a vocabulary one. Same for the curly
    apostrophe of the textbook (’ -> ') and for an ellipsis marking a gap in
    a phrase ("Wie …?" is answered "Wie").
    """
    text = text.strip().lower().replace("\u0153", "oe").replace("\u00e6", "ae")
    text = text.replace("\u2019", "'").replace("\u2026", " ").replace("...", " ")
    text = " ".join(text.split())
    return text.strip(_TRIM_CHARS).strip()


def _strip_accents(text: str) -> str:
    """"élève" -> "eleve" (leaves ß alone, it is not an accent)."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _de_key(text: str) -> str:
    """German comparison key: umlauts folded to their two-letter spelling."""
    for char, replacement in _DE_SUBSTITUTIONS:
        text = text.replace(char, replacement)
    return text


def _fr_key(text: str) -> str:
    """French comparison key: accents dropped, leading article optional."""
    text = _strip_accents(text)
    for article in _FR_LEADING_ARTICLES:
        if text.startswith(article):
            return text[len(article):].strip()
    return text


def keys_for(text: str, lang: str = "") -> set:
    """
    All the spellings that count as "this answer", for the given language.

    Always contains the plain normalized form, so an exact answer matches
    whatever the language is.
    """
    variants = {normalize(text), normalize(_PAREN_RE.sub("", text))}
    keys = set(variants)
    for variant in variants:
        if lang == "de":
            keys.add(_de_key(variant))
        elif lang == "fr":
            keys.add(_strip_accents(variant))   # accents optional
            keys.add(_fr_key(variant))          # accents + leading article optional
    return {k for k in keys if k}


def matches(given: str, accepted, lang: str = "") -> bool:
    """
    True when `given` is one of the `accepted` answers.

    accepted: a single string or a list of strings (the expected answer plus
              any synonym from the JSON seed).
    lang:     "de", "fr", or "" for the strict historical comparison.
    """
    if isinstance(accepted, str):
        accepted = [accepted]

    given_keys = keys_for(given, lang)
    if not given_keys:
        return False

    for candidate in accepted:
        if given_keys & keys_for(candidate, lang):
            return True
    return False


# German articles that may open an answer, longest first so that "die" is not
# matched inside "dieser".
_DE_ARTICLES = ("der", "die", "das", "den", "dem", "ein", "eine", "einen")


def hint_base(answer: str, lang: str = "") -> str:
    """
    The part of the answer the hint letters are taken from.

    For a German noun the article is stripped: hinting on "der Tisch" would
    spell out "de..." and hand over the gender, which is the hard half of the
    exercise. The hint is built on "Tisch" instead, and the article is only
    revealed with the full answer after the third miss.

    Returns "" when there is nothing to hint on besides the article.
    """
    if lang != "de":
        return answer

    parts = answer.strip().split()
    if len(parts) >= 2 and parts[0].lower() in _DE_ARTICLES:
        return " ".join(parts[1:])
    return answer


def hint_prefix(answer: str, attempt: int, lang: str = "") -> str:
    """
    The hint shown after a wrong attempt, unchanged from the original rule:
      attempt 1 -> first 2 letters
      attempt 2 -> first 4 letters, or len-1 when the word is 4 letters or less
    Applied to hint_base(), so a German article is never given away.
    """
    base = hint_base(answer, lang)
    if not base:
        return ""
    n = len(base)
    if attempt <= 1:
        length = 2
    else:
        length = (n - 1) if n <= 4 else 4
    return base[:max(length, 1)]
