"""Normalization helpers used by the vocabulary importer and referee."""

from __future__ import annotations

import re
import unicodedata


# The prolonged sound mark is retained inside loanwords. Vocabulary policy
# rejects readings that end in it because their next Shiritori kana would be
# ambiguous without an additional pronunciation rule.
_HIRAGANA_RE = re.compile(r"^[ぁ-ゖー]+$")
_FINAL_SMALL_KANA = str.maketrans(
    {
        "ゃ": "や",
        "ゅ": "ゆ",
        "ょ": "よ",
        "ぁ": "あ",
        "ぃ": "い",
        "ぅ": "う",
        "ぇ": "え",
        "ぉ": "お",
        "っ": "つ",
    }
)


def katakana_to_hiragana(value: str) -> str:
    """Convert ordinary katakana code points to hiragana."""

    converted: list[str] = []
    for character in value:
        codepoint = ord(character)
        if 0x30A1 <= codepoint <= 0x30F6:
            converted.append(chr(codepoint - 0x60))
        else:
            converted.append(character)
    return "".join(converted)


def normalize_reading(value: str) -> str:
    """Return the canonical reading used as a game identity."""

    normalized = unicodedata.normalize("NFKC", value).strip()
    return katakana_to_hiragana(normalized)


def is_hiragana_word(value: str) -> bool:
    return bool(_HIRAGANA_RE.fullmatch(value))


def terminal_kana(reading: str) -> str:
    if not reading:
        raise ValueError("reading cannot be empty")
    return reading[-1].translate(_FINAL_SMALL_KANA)


def initial_kana(reading: str) -> str:
    if not reading:
        raise ValueError("reading cannot be empty")
    return reading[0]

