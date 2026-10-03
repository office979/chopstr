"""Freigaberelevante Behauptungen: wann ein Kandidat nicht automatisch angenommen wird.

Das Flag ``claim`` aus ``story_graph.claims_in`` bleibt, wie es ist (Grounding, ``risk_flags``,
Snapshot v1). Als Kriterium für die automatische Freigabe ist es zu breit: jede Ziffer, jedes
„weil“ und „dadurch“, jedes „alle“ und „jede“ zählt dort, und weil ohne Wortgrenzen gesucht wird,
trifft „Allerdings“ auf „alle“, „jederzeit“ auf „jede“ und „Positionierung“ auf „nie“. An den
Fällen des Testsatzes ``editorial_v1`` und an der Demo trug fast jeder Kandidat das Flag; die
Freigabepflicht hätte damit praktisch jeden Clip zurückgehalten (``docs/ENTSCHEIDUNGEN.md`` P27).

Hier zählt nur, was ein Mensch vor der Veröffentlichung prüfen muss (``docs/ENTSCHEIDUNGEN.md``
P27), und immer als ganzes Wort:

* eine Zahl mit Einheit, Prozent, Währung oder Vervielfachung („40.000 Euro“, „12 Franken“,
  „40 Prozentpunkte“, „fünfundzwanzig Stunden“, „500 Mitarbeiter“, „zehnmal“). Zahlwörter werden
  über einen Ausdruck erkannt, auch zusammengesetzte („fünfzehn“, „vierzigtausend“), das bloße
  Artikelwort „ein“ nicht;
* Vergleich und Vervielfachung ohne Zahl: „doppelt“, „verdoppelt“, „verdreifacht“, „halb so“,
  „Hälfte“, „Drittel“, „Viertel“, „Fünftel“, dazu „Nummer eins“;
* Beleg- und Absolutwörter: „garantiert“, „bewiesen“, „belegt“, „erwiesen“, „wissenschaftlich“;
* Allaussagen: „immer“, „nie“, „niemals“, „jeder“, „alle“ (alle Formen) zusammen mit einer
  Verallgemeinerung im selben Satz. Stark verallgemeinernd sind „man“, „gilt“, „überall“,
  „grundsätzlich“, „bei allen“, „für alle“ und ähnliche; schwächer sind Gruppenobjekte („Kunden“,
  „Firmen“, „Unternehmen“, „Menschen“) und Wirkungsverben („funktioniert“, „klappt“, „wirkt“,
  „hilft“), die nur zählen, wenn der Satz nicht ausdrücklich vom eigenen Fall spricht („bei uns“).

„weil“ und „dadurch“ zählen nicht: eine Begründung ist keine Tatsachenbehauptung, die man am
Material prüfen müsste. Eine Jahreszahl allein („2024“) zählt ebenfalls nicht.
"""

from __future__ import annotations

import re

# Zeilenpräfix im Kandidatentext (``rubric.text``): „[3] (SPEAKER_00) “. Die Ziffern darin sind
# keine Aussage.
_LINE_PREFIX = re.compile(r"^\s*\[\d+\]\s*(?:\([^)]*\)\s*)?", re.MULTILINE)
# Satzende nach . ! ?, aber nicht nach Abkürzungen, die in Zahlenangaben vorkommen („3 Mio. Euro“, „z. B.“).
_SENTENCE_SPLIT = re.compile(
    r"(?<!\bMio\.)(?<!\bMrd\.)(?<!\bca\.)(?<!\bbzw\.)(?<!\bz\.)(?<!\bB\.)(?<=[.!?])\s+|\n+"
)

# Zahlwörter als Ausdruck statt Liste: ein Wort, das nur aus Zahlbausteinen besteht („fünfzehn“,
# „fünfundzwanzig“, „vierzigtausend“, „einhundert“). „ein“ allein ist meist Artikel und zählt nicht.
_NUMBER_PART = (
    r"(?:eins|ein|zwei|drei|vier|fünf|sechs|sech|sieben|sieb|acht|neun|zehn|elf|zwölf|"
    r"zwanzig|dreißig|vierzig|fünfzig|sechzig|siebzig|achtzig|neunzig|hundert|tausend|und)"
)
_NUMBER_WORD = rf"(?!(?:ein|und)(?!\w))(?!und){_NUMBER_PART}+"
_NUMBER = rf"(?:\d+(?:[.,]\d+)*|{_NUMBER_WORD})"
_UNITS = (
    r"(?:prozent|prozentpunkte|prozentpunkten|euro|franken|chf|dollar|"
    r"million|millionen|mio\.|milliarde|milliarden|mrd\.|mal|"
    r"jahr|jahre|jahren|jahres|monat|monate|monaten|monats|woche|wochen|tag|tage|tagen|stunde|stunden|"
    r"kunden|kundinnen|mitarbeiter|mitarbeitern|mitarbeitende|mitarbeitenden|nutzer|nutzern)"
)

_QUANTIFIED = (
    # Zahl, dann Einheit als eigenes Wort: „40.000 Euro“, „fünfzehn Prozent“, „5 Mio.“
    re.compile(rf"(?<![\w.,]){_NUMBER}\s+{_UNITS}(?!\w)", re.IGNORECASE),
    # Zeichen direkt an der Zahl: „40 %“, „40%“, „500 €“, „20 $“
    re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*\s*[%€$]", re.IGNORECASE),
    # Währung vor der Zahl: „€ 500“, „$500“, „CHF 50“
    re.compile(r"(?:[€$]|(?<!\w)chf)\s*\d", re.IGNORECASE),
    # Vervielfachung als ein Wort: „zehnmal“, „3-mal“, „3mal“
    re.compile(rf"(?<![\w.,]){_NUMBER}-?mal(?!\w)", re.IGNORECASE),
    # Vergleich und Vervielfachung ohne Zahl, Bruchwörter, Rangplatz
    re.compile(
        r"(?<!\w)(?:doppelt|doppelte|doppelten|doppelter|doppeltes|"
        r"ver(?:doppel|dreifach|vierfach|zehnfach|vielfach)\w*|"
        r"hälfte|drittel|dritteln|viertel|vierteln|fünftel|fünfteln|"
        r"halb\s+so|nummer\s+(?:eins|1))(?!\w)",
        re.IGNORECASE,
    ),
)
_ABSOLUTE = re.compile(r"(?<!\w)(?:garantiert|bewiesen|belegt|erwiesen|wissenschaftlich\w*)(?!\w)", re.IGNORECASE)
_UNIVERSAL = re.compile(
    r"(?<!\w)(?:immer|nie|niemals|jeder|jede|jedes|jeden|jedem|alle|allen|aller|alles)(?!\w)", re.IGNORECASE
)
# Verallgemeinerung, die immer zählt.
_GENERALIZATION = re.compile(
    r"(?<!\w)(?:man|gilt|gelten|galt|überall|grundsätzlich|generell|pauschal|ausnahmslos|egal|"
    r"bei\s+allen|für\s+alle|für\s+jede[nrs]?)(?!\w)",
    re.IGNORECASE,
)
# Gruppenobjekte und Wirkungsverben: verallgemeinern nur, wenn der Satz nicht vom eigenen Fall spricht.
_GENERALIZATION_WEAK = re.compile(
    r"(?<!\w)(?:kunden|kundinnen|firmen|unternehmen|menschen|betriebe|leute|"
    r"funktioniert|funktionieren|klappt|klappen|wirkt|wirken|hilft|helfen)(?!\w)",
    re.IGNORECASE,
)
_OWN_CASE = re.compile(r"(?<!\w)(?:bei\s+uns|bei\s+mir|in\s+unsere[mrn]?|unsere[mrns]?|unser)(?!\w)", re.IGNORECASE)


def _sentences(text: str) -> list[str]:
    plain = _LINE_PREFIX.sub("", text or "")
    return [s.strip() for s in _SENTENCE_SPLIT.split(plain) if s and s.strip()]


def _is_release_relevant(sentence: str) -> bool:
    if any(p.search(sentence) for p in _QUANTIFIED):
        return True
    if _ABSOLUTE.search(sentence):
        return True
    if not _UNIVERSAL.search(sentence):
        return False
    if _GENERALIZATION.search(sentence):
        return True
    return bool(_GENERALIZATION_WEAK.search(sentence) and not _OWN_CASE.search(sentence))


def release_relevant_claims(text: str) -> list[str]:
    """Die Sätze im Text, die eine freigaberelevante Behauptung enthalten, in Textreihenfolge.

    Leere Liste heißt: nichts, was die automatische Freigabe aufhalten muss."""
    out: list[str] = []
    for sentence in _sentences(text):
        if _is_release_relevant(sentence) and sentence not in out:
            out.append(sentence)
    return out


__all__ = ["release_relevant_claims"]
