"""Lernendes Kontolexikon (A1): was ein Markenprofil schon weiß, wie man es schreibt.

Das Lexikon eines Markenprofils besteht aus
  * ``brand_vocab`` (Eigennamen, Produkte, Personen) und ``protected_terms`` (Austriazismen, Helvetismen),
  * jedem ``transcript_corrections.new_text`` mit ``add_to_vocab = true`` aus Quellen dieses Profils.

Dazu kommt die Verwechslungsliste (confusion map) ``old_text -> new_text`` aus angenommenen Korrekturen: eine
Verwechslung gilt, wenn sie mindestens zweimal korrigiert wurde oder einmal mit ``add_to_vocab``. Geschützte
Begriffe sind nie die Quelle einer Verwechslung, denn sie sind kein Fehler. Widersprechen sich zwei
Korrekturen gleich oft, gilt keine von beiden.

``apply_confusions`` ersetzt nur ganze Tokens (ohne Groß- und Kleinschreibung, Satzzeichen am Ende bleiben)
und rührt ``start``, ``end`` und alle anderen Wortfelder nicht an. ``transcribe.apply_brand_vocab`` bleibt
unverändert daneben bestehen.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .. import db

CONFUSION_MIN_SEEN = 2

SQL_BRAND = "select brand_vocab, protected_terms from brand_profiles where id = %s"
SQL_CORRECTIONS = (
    "select c.old_text, c.new_text, c.add_to_vocab from transcript_corrections c "
    "join sources s on s.id = c.source_id where s.brand_profile_id = %s order by c.created_at asc"
)
_TRAILING = re.compile(r"[.,!?;:…]+$")


def token_key(text: str) -> str:
    """Vergleichsschlüssel eines Tokens: kleingeschrieben, ohne Satzzeichen an den Rändern."""
    return re.sub(r"^\W+|\W+$", "", str(text).lower())


@dataclass
class Lexicon:
    terms: list[str] = field(default_factory=list)
    protected: list[str] = field(default_factory=list)
    # Schlüssel (token_key des alten Texts) -> neue Schreibweise
    confusions: dict[str, str] = field(default_factory=dict)

    def has_term(self, text: str) -> bool:
        key = token_key(text)
        return any(token_key(t) == key for t in self.terms)

    def is_protected(self, text: str) -> bool:
        key = token_key(text)
        return any(token_key(t) == key for t in self.protected)

    def to_dict(self) -> dict[str, Any]:
        return {"terms": list(self.terms), "protected": list(self.protected), "confusions": dict(self.confusions)}


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        v = str(v or "").strip()
        k = token_key(v)
        if v and k and k not in seen:
            seen.add(k)
            out.append(v)
    return out


def build_confusions(corrections: list[tuple[Any, Any, Any]], protected: list[str] | tuple[str, ...] = ()) -> dict[str, str]:
    """Verwechslungsliste aus ``[(old_text, new_text, add_to_vocab)]``. Nur einzelne Tokens als Quelle."""
    protected_keys = {token_key(p) for p in protected}
    seen: dict[str, Counter[str]] = defaultdict(Counter)
    vocab_flag: dict[tuple[str, str], bool] = {}
    for old, new, add in corrections:
        old_s, new_s = str(old or "").strip(), _TRAILING.sub("", str(new or "").strip())
        key = token_key(old_s)
        if not key or not new_s or " " in old_s or key == token_key(new_s) or key in protected_keys:
            continue
        seen[key][new_s] += 1
        vocab_flag[(key, new_s)] = vocab_flag.get((key, new_s), False) or bool(add)
    out: dict[str, str] = {}
    for key, counter in seen.items():
        ranked = counter.most_common()
        top, n = ranked[0]
        if len(ranked) > 1 and ranked[1][1] == n:
            continue  # widersprüchlich, keine Regel
        if n >= CONFUSION_MIN_SEEN or vocab_flag.get((key, top)):
            out[key] = top
    return out


def build_lexicon(conn, brand_profile_id: str | None, extra_vocab: list[str] | None = None, extra_protected: list[str] | None = None) -> Lexicon:
    """Lexikon eines Markenprofils; ohne Profil nur die mitgegebenen Begriffe (z. B. aus ``db.load_source``)."""
    vocab = list(extra_vocab or [])
    protected = list(extra_protected or [])
    corrections: list[tuple[Any, Any, Any]] = []
    if brand_profile_id:
        row = db.fetch_one(conn, SQL_BRAND, (brand_profile_id,))
        if row is not None:
            vocab += list(row[0] or [])
            protected += list(row[1] or [])
        corrections = [tuple(r) for r in db.fetch_all(conn, SQL_CORRECTIONS, (brand_profile_id,))]
    learned = [_TRAILING.sub("", str(new).strip()) for _old, new, add in corrections if add and str(new or "").strip()]
    protected_u = _unique(protected)
    return Lexicon(
        terms=_unique([*vocab, *learned, *protected_u]),
        protected=protected_u,
        confusions=build_confusions(corrections, protected_u),
    )


def apply_confusions(words: list[dict], confusions: dict[str, str]) -> list[dict]:
    """Bekannte Verwechslungen ersetzen; nur ``text`` ändert sich, Satzzeichen am Ende bleiben."""
    if not confusions:
        return words
    for w in words:
        raw = str(w.get("text") or "")
        hit = confusions.get(token_key(raw))
        if hit is None:
            continue
        trailing = _TRAILING.findall(raw)
        w["text"] = hit + (trailing[0] if trailing else "")
    return words


__all__ = ["CONFUSION_MIN_SEEN", "Lexicon", "apply_confusions", "build_confusions", "build_lexicon", "token_key"]
