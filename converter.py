"""Rule-based Gurmukhi -> casual Roman transliteration.

Casual style means the way people type Punjabi on WhatsApp:
    ਪੰਜਾਬੀ -> punjabi, ਮੈਂ -> main, ਪੱਕਾ -> pakka

Pipeline: normalise -> split into words -> parse each word into syllables
-> apply schwa deletion -> emit Roman text.
"""
import ast
import json
import re
import unicodedata
from dataclasses import dataclass

# --------------------------------------------------------------------------
# Tables (edit these to change the output style)
# --------------------------------------------------------------------------
CONSONANTS = {
    "ਕ": "k", "ਖ": "kh", "ਗ": "g", "ਘ": "gh", "ਙ": "",
    "ਚ": "ch", "ਛ": "chh", "ਜ": "j", "ਝ": "jh", "ਞ": "",
    "ਟ": "t", "ਠ": "th", "ਡ": "d", "ਢ": "dh", "ਣ": "n",
    "ਤ": "t", "ਥ": "th", "ਦ": "d", "ਧ": "dh", "ਨ": "n",
    "ਪ": "p", "ਫ": "f", "ਬ": "b", "ਭ": "bh", "ਮ": "m",
    "ਯ": "y", "ਰ": "r", "ਲ": "l", "ਵ": "v", "ੜ": "d",
    "ਸ": "s", "ਹ": "h",
}

NUKTA = "\u0a3c"  # ਼
# Consonant + nukta. After NFC normalisation ਸ਼ ਖ਼ ਗ਼ ਜ਼ ਫ਼ ਲ਼ are base + nukta.
NUKTA_FORMS = {"ਸ": "sh", "ਖ": "kh", "ਗ": "g", "ਜ": "z", "ਫ": "f", "ਲ": "l"}

INDEPENDENT_VOWELS = {
    "ਅ": "a", "ਆ": "aa", "ਇ": "i", "ਈ": "ee", "ਉ": "u", "ਊ": "oo",
    "ਏ": "e", "ਐ": "ae", "ਓ": "o", "ਔ": "au",
    "ੳ": "u", "ੲ": "i",
}
CARRIERS = {"ਅ", "ੳ", "ੲ"}  # vowel carriers: a following vowel sign replaces them

SIGNS_SHORT = {
    "ਾ": "a", "ਿ": "e", "ੀ": "i", "ੁ": "u", "ੂ": "oo",
    "ੇ": "e", "ੈ": "ae", "ੋ": "o", "ੌ": "au",
}
SIGNS_LONG = {**SIGNS_SHORT, "ਾ": "aa", "ੀ": "ee", "ੂ": "oo"}

NASALS = {"ਂ", "ੰ", "ਁ"}   # bindi, tippi, adak bindi
ADDAK = "ੱ"
VIRAMA = "੍"
VISARGA = "ਃ"

DIGITS = str.maketrans("੦੧੨੩੪੫੬੭੮੯", "0123456789")
PUNCT = str.maketrans({"।": ".", "॥": "."})

# Whole-word overrides, checked before any rule. Add names and loanwords here.
EXCEPTIONS = {
    "ਪੰਜਾਬ": "punjab",
    "ਪੰਜਾਬੀ": "punjabi",
    "ਤੁਸੀਂ": "tusi",
    "ਸਤਿ": "sat",
    "ੴ": "ik onkar",
    "ਸ਼ਹਿਰ": "shehar",
    "ਜ਼ਿੰਦਗੀ": "zindagi",
    "ਫ਼ਿਲਮ": "film",
    "ਵਿੱਚ": "vich",
}

WORD_RE = re.compile(r"[\u0A01-\u0A65\u0A70-\u0A7F]+")


@dataclass
class Syl:
    onset: str = ""
    vowel: str = ""
    kind: str = "exp"   # exp = fixed vowel, inh = inherent 'a' (deletable),
                        # none = consonant cluster part, dead = deleted 'a'
    nasal: bool = False
    coda: str = ""


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def _parse(word: str, signs: dict) -> list:
    sylls = []
    double_next = False
    i, n = 0, len(word)
    while i < n:
        ch = word[i]
        if ch in CONSONANTS:
            rom = CONSONANTS[ch]
            if i + 1 < n and word[i + 1] == NUKTA:
                rom = NUKTA_FORMS.get(ch, rom)
                i += 1
            if double_next:
                rom = rom[0] + rom
                double_next = False
            sylls.append(Syl(onset=rom, vowel="a", kind="inh"))
        elif ch in INDEPENDENT_VOWELS:
            sylls.append(Syl(vowel=INDEPENDENT_VOWELS[ch], kind="exp"))
        elif ch in signs:
            if sylls:
                sylls[-1].vowel = signs[ch]
                sylls[-1].kind = "exp"
        elif ch in NASALS:
            if sylls:
                sylls[-1].nasal = True
                if sylls[-1].kind == "inh":
                    sylls[-1].kind = "exp"
        elif ch == ADDAK:
            if sylls and sylls[-1].kind == "inh":
                sylls[-1].kind = "exp"
            double_next = True
        elif ch == VIRAMA:
            if sylls:
                sylls[-1].vowel = ""
                sylls[-1].kind = "none"
        elif ch == VISARGA:
            if sylls:
                sylls[-1].coda = "h"
        # other marks (stray nukta, yakash, udaat) are ignored
        i += 1
    return sylls


# --------------------------------------------------------------------------
# Schwa deletion
# --------------------------------------------------------------------------
def _delete_schwas(sylls: list) -> None:
    # 1. Final inherent 'a' is dropped: ਕਮ -> kam (but a lone consonant keeps it)
    if len(sylls) > 1 and sylls[-1].kind == "inh":
        sylls[-1].vowel, sylls[-1].kind = "", "dead"
    # 2. Medial inherent 'a' is dropped between two syllables that keep their
    #    vowels, working right to left: ਕਰਨਾ -> karna, but ਸਮਝ -> samajh
    for i in range(len(sylls) - 2, 0, -1):
        s = sylls[i]
        if s.kind == "inh" and sylls[i - 1].vowel and sylls[i + 1].vowel:
            s.vowel, s.kind = "", "dead"


# --------------------------------------------------------------------------
# Emitting
# --------------------------------------------------------------------------
def _emit(sylls: list) -> str:
    out = []
    for idx, s in enumerate(sylls):
        text = s.onset
        # glide between vowels: ਪਿਆਰ -> piyaar
        if (idx and not s.onset and s.vowel.startswith("a")
                and sylls[idx - 1].vowel.endswith(("i", "ee"))
                and not sylls[idx - 1].nasal):
            text += "y"
        text += s.vowel
        if s.nasal:
            nxt = ""
            if idx + 1 < len(sylls):
                nxt = sylls[idx + 1].onset or sylls[idx + 1].vowel
            text += "m" if nxt[:1] in ("p", "b", "m") else "n"
        text += s.coda
        out.append(text)
    return "".join(out)


def _merge(exceptions: dict = None) -> dict:
    return EXCEPTIONS if not exceptions else {**EXCEPTIONS, **exceptions}


def _word(word: str, long_vowels: bool, table: dict) -> str:
    word = unicodedata.normalize("NFC", word)
    if word in table:
        return table[word]
    sylls = _parse(word, SIGNS_LONG if long_vowels else SIGNS_SHORT)
    _delete_schwas(sylls)
    return _emit(sylls)


def convert_word(word: str, long_vowels: bool = False, exceptions: dict = None) -> str:
    return _word(word, long_vowels, _merge(exceptions))


# A capital letter is used only after . ? ! (optionally followed by a closing
# quote/bracket) and whitespace, and an opening quote or bracket before the
# letter is allowed:  ho? "main -> ho? "Main
# The first word of the text and of each line is NOT capitalised on its own.
_SENTENCE_START = re.compile(r"""([.?!]+["')\]]*\s+["'(\[]*)([a-z])""")


def capitalize_sentences(text: str) -> str:
    """Capitalise the first letter of the word that follows . ? or !"""
    return _SENTENCE_START.sub(lambda m: m.group(1) + m.group(2).upper(), text)


def convert(text: str, long_vowels: bool = False, exceptions: dict = None,
            capitalize: bool = False) -> str:
    """Convert Gurmukhi text to casual Roman. Non-Gurmukhi text passes through.

    If `capitalize` is True, the first letter of the word after . ? or ! is
    capitalised; every other letter stays lowercase.

    `exceptions` is an optional {gurmukhi_word: roman} dict that overrides the
    built-in EXCEPTIONS. Keys must match whole words.
    """
    table = _merge(exceptions)
    text = unicodedata.normalize("NFC", text)
    text = WORD_RE.sub(lambda m: _word(m.group(), long_vowels, table), text)
    text = text.translate(DIGITS).translate(PUNCT)
    return capitalize_sentences(text) if capitalize else text


# --------------------------------------------------------------------------
# Loading exception lists from uploaded files
# --------------------------------------------------------------------------
MAX_BYTES = 1_000_000
MAX_ENTRIES = 50_000


def _literal_dict(raw: str) -> dict:
    """Find the first dict literal in Python source, without running the code."""
    try:
        tree = ast.parse(raw)
    except (SyntaxError, RecursionError, MemoryError, ValueError) as err:
        line = getattr(err, "lineno", None)
        where = f" (problem near line {line})" if line else ""
        raise ValueError(f"Could not read the file as JSON or as a Python dictionary{where}.")
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Expr)) and isinstance(node.value, ast.Dict):
            try:
                return ast.literal_eval(node.value)
            except (ValueError, TypeError, RecursionError):
                raise ValueError("The dictionary may only contain plain text, with no variables or function calls.")
    raise ValueError("No dictionary found in the file.")


def parse_exceptions(raw: str) -> dict:
    """Parse an exceptions file: a JSON object or a Python dict literal.

    Python files are read with ast.literal_eval, so no uploaded code is ever executed.
    Both of these work:
        {"ਪੰਜਾਬ": "punjab"}
        EXCEPTIONS = {"ਪੰਜਾਬ": "punjab"}
    """
    if len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("The file is too large (limit 1 MB).")
    raw = raw.lstrip("\ufeff").strip()          # drop BOM from Windows editors
    if not raw:
        raise ValueError("The file is empty.")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, RecursionError):
        data = _literal_dict(raw)
    if not isinstance(data, dict):
        raise ValueError("Expected a dictionary of Punjabi word: Roman spelling pairs.")
    if len(data) > MAX_ENTRIES:
        raise ValueError(f"Too many entries (limit {MAX_ENTRIES}).")
    clean = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError(f"Entry {key!r}: the word and its Roman spelling must both be text.")
        key = unicodedata.normalize("NFC", key.strip())
        if key:
            clean[key] = value.strip()
    return clean


# --------------------------------------------------------------------------
# Subtitle (.srt) files
# --------------------------------------------------------------------------
# Cue numbers, timestamps and blank lines are never touched. The case rule
# compares each text line with the PREVIOUS TEXT LINE, even across cues:
#   previous text line ended with . ? !  -> first letter is capitalised
#   otherwise                            -> first letter is lowercased
# Capitals inside a line follow the same rule as plain text (after . ? !).
_TIMESTAMP = re.compile(
    r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{3}"
)
_TAG = r"(?:<[^>]+>|\{[^}]*\})"                      # <i> </i> {\an8}
_LEAD = re.compile(rf"""^(\s*(?:{_TAG}|["'(\[])*)([^\W\d_])""")
_END_PUNCT = re.compile(rf"""[.?!](?:["')\]]|{_TAG})*\s*$""")
_MID_LINE = re.compile(rf"""([.?!]+(?:["')\]]|{_TAG})*[ \t]+(?:{_TAG}|["'(\[])*)([a-z])""")


def looks_like_srt(text: str) -> bool:
    """True if the text contains at least one subtitle timestamp line."""
    return any(_TIMESTAMP.match(line) for line in text.splitlines())


def _srt_skip(lines: list, i: int) -> bool:
    """True for blank lines, cue numbers and timestamp lines."""
    body = lines[i].rstrip("\r\n")
    stripped = body.strip()
    if not stripped or _TIMESTAMP.match(body):
        return True
    return stripped.isdigit() and i + 1 < len(lines) and bool(_TIMESTAMP.match(lines[i + 1]))


def fix_srt_case(text: str) -> str:
    """Apply the capital-letter rule to the text lines of an .srt file."""
    lines = text.splitlines(keepends=True)
    out = []
    prev_ended = None            # None until the first text line has been seen
    for i, raw in enumerate(lines):
        if _srt_skip(lines, i):
            out.append(raw)
            continue
        body = raw.rstrip("\r\n")
        eol = raw[len(body):]
        if prev_ended is not None:
            m = _LEAD.match(body)
            if m:
                ch = m.group(2).upper() if prev_ended else m.group(2).lower()
                body = m.group(1) + ch + body[m.end():]
        body = _MID_LINE.sub(lambda m: m.group(1) + m.group(2).upper(), body)
        prev_ended = bool(_END_PUNCT.search(body))
        out.append(body + eol)
    return "".join(out)


def convert_srt(text: str, long_vowels: bool = False, exceptions: dict = None,
                capitalize: bool = True) -> str:
    """Convert the text lines of a Gurmukhi .srt file to casual Roman."""
    table = _merge(exceptions)
    text = unicodedata.normalize("NFC", text.lstrip("\ufeff"))
    lines = text.splitlines(keepends=True)
    out = []
    for i, raw in enumerate(lines):
        if _srt_skip(lines, i):
            out.append(raw)
            continue
        body = raw.rstrip("\r\n")
        eol = raw[len(body):]
        body = WORD_RE.sub(lambda m: _word(m.group(), long_vowels, table), body)
        out.append(body.translate(DIGITS).translate(PUNCT) + eol)
    result = "".join(out)
    return fix_srt_case(result) if capitalize else result


if __name__ == "__main__":
    import sys
    print(convert(" ".join(sys.argv[1:]) or "ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ"))
