"""Readable game transcripts with dependency-free Hepburn romanization."""

from __future__ import annotations

import unicodedata
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from .normalize import normalize_reading
from .frequency import frequency_label


@lru_cache(maxsize=1)
def english_glossary() -> dict[str, list[str]]:
    path = Path(__file__).resolve().parents[2] / "data/processed/english-glosses.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def english_meaning(word: str) -> str:
    if not word or word == "PASS":
        return "—"
    glosses = english_glossary().get(normalize_reading(word), [])
    return " / ".join(glosses[:3]) if glosses else "No accepted noun gloss found"


_KANA = dict(zip(
    "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわゐゑをんがぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽぁぃぅぇぉゃゅょゎゔ",
    "a i u e o ka ki ku ke ko sa shi su se so ta chi tsu te to na ni nu ne no ha hi fu he ho ma mi mu me mo ya yu yo ra ri ru re ro wa wi we o n ga gi gu ge go za ji zu ze zo da ji zu de do ba bi bu be bo pa pi pu pe po a i u e o ya yu yo wa vu".split(),
))
_PAIRS = {base + small: stem + vowel
          for base, stem in {"き": "ky", "ぎ": "gy", "し": "sh", "じ": "j",
                             "ち": "ch", "ぢ": "j", "に": "ny", "ひ": "hy",
                             "び": "by", "ぴ": "py", "み": "my", "り": "ry"}.items()
          for small, vowel in {"ゃ": "a", "ゅ": "u", "ょ": "o"}.items()}
_PAIRS.update(dict(zip(
    "いぇ うぃ うぇ うぉ しぇ じぇ ちぇ てぃ でぃ とぅ どぅ てゅ でゅ つぁ つぃ つぇ つぉ ふぁ ふぃ ふぇ ふぉ ふゅ ゔぁ ゔぃ ゔぇ ゔぉ ゔゅ".split(),
    "ye wi we wo she je che ti di tu du tyu dyu tsa tsi tse tso fa fi fe fo fyu va vi ve vo vyu".split(),
)))


def romanize(text: str) -> str:
    """Hepburn-style transliteration; preserve vowel sequences (e.g. toukyou)."""
    normalized = unicodedata.normalize("NFKC", text)
    kana = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in normalized)
    pieces: list[str] = []
    index = 0
    while index < len(kana):
        char = kana[index]
        pair = kana[index:index + 2]
        if char == "っ":
            following = _PAIRS.get(kana[index + 1:index + 3], _KANA.get(kana[index + 1:index + 2], ""))
            pieces.append("t" if following.startswith("ch") else following[:1] if following[:1] not in "aeioun" else "")
        elif char == "ー":
            previous = "".join(pieces)
            pieces.append(next((c for c in reversed(previous) if c in "aeiou"), "ー"))
        elif pair in _PAIRS:
            pieces.append(_PAIRS[pair])
            index += 1
        elif char == "ん":
            following = _KANA.get(kana[index + 1:index + 2], "")
            pieces.append("n'" if following and following[0] in "aeiouy" else "n")
        else:
            pieces.append(_KANA.get(char, char))
        index += 1
    return "".join(pieces)


def ending_description(record: dict[str, Any]) -> str:
    ending = record["ending"]
    if ending == "GENERATION_ERROR:length":
        return "Output token limit reached before completion (not a competitive loss)."
    if ending.startswith("GENERATION_ERROR:"):
        return f"Generation stopped: {ending.split(':', 1)[1]} (not a competitive loss)."
    if ending.startswith("PLAYER_ERROR:"):
        return f"Player/API error (not a competitive loss): {ending.split(':', 1)[1]}"
    descriptions = {
        "ENDS_IN_N": "The submitted word ends in ん (n).",
        "WRONG_START": "The submitted word starts with the wrong kana.",
        "REPEATED_WORD": "The submitted word was already used.",
        "INVALID_WORD": "The word is not in the benchmark's accepted vocabulary.",
        "MALFORMED_OUTPUT": "The response was not exactly one hiragana word or PASS.",
        "PASS_WITH_LEGAL_MOVE": "Player passed although dictionary moves remained.",
        "PASS_NO_LEGAL_MOVE": "Player passed; no dictionary moves remained.",
        "TURN_LIMIT_DRAW": "Turn cap reached; game unfinished.",
    }
    return descriptions.get(ending, ending)


def cell(value: Any) -> str:
    return str(value).replace("\n", " / ").replace("\r", " ").replace("\t", " ")


def render_game(record: dict[str, Any], number: int = 1) -> str:
    players = record["players"]
    lines = [f"Game {number}", "",
             f"P1: {cell(players[0]['name'])} · P2: {cell(players[1]['name'])}",
             f"Opening: {cell(record['opening_kana'])} ({romanize(record['opening_kana'])})", "",
             "Turn  Player  Word / Romanization / English (JMdict)"]
    for turn in record.get("turns", []):
        word = turn.get("submitted", "")
        roman = "—" if not word or word == "PASS" else romanize(word)
        lines.append(f"{turn['turn']:>4}  P{turn['player_index'] + 1}      {cell(word) if word else '(no final answer)'} / {cell(roman)} / {cell(english_meaning(word))}")
        if word and word != "PASS":
            lines.append(f"             {frequency_label(word)}")
    winner = record.get("winner_index")
    result = f"P{winner + 1} wins" if winner is not None else "No winner"
    lines += ["", f"Result: {result}.", f"Ending: {ending_description(record)}"]
    if record.get("turns") and winner is not None:
        last = record["turns"][-1]
        lines.append(f"Failed move: P{last['player_index'] + 1}, turn {last['turn']}; required kana {last['required_kana']} ({romanize(last['required_kana'])}).")
    return "\n".join(lines) + "\n"


def render_games(records: Iterable[dict[str, Any]]) -> str:
    return ("Game transcripts\n\nEnglish: up to three JMdict noun entries matching the reading, common entries first. "
            "A kana reading can have multiple meanings; the intended sense is not inferred.\n"
            "Frequency: corpus-based estimates per million tokens. TUBELEX ranges reflect ambiguous readings; "
            "BCCWJ short/long units are separate when available. Unmatched means unavailable, not zero.\n\n"
            + "\n".join(render_game(record, index) for index, record in enumerate(records, 1)))
