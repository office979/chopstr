"""Häufige deutsche Wörter (Grundwortschatz), kleingeschrieben.

Für die Transkriptkorrektur (``transcript_fix.heuristic_edits``): ein Wort aus dieser Liste ist nie die Quelle
eines unscharfen Lexikon-Treffers. Sonst wird in einem Podcast aus jedem „wieder“ ein „Wieser“ und aus jedem
„Leiter“ ein „Leitner“ (Review R1-09). Nur Wörter ab vier Buchstaben, kürzere prüft die Heuristik ohnehin
nicht. Bewusst eine feste Liste im Code statt eines Wörterbuchs als Abhängigkeit; ergänzen, wenn ein
Fehlvorschlag auffällt.
"""

from __future__ import annotations

COMMON_DE: frozenset[str] = frozenset("""
aber abend abends acht alle allein allem allen aller alles also alter anders andere anderen anderer anfang
arbeit arbeiten arbeitet auch auto autos baum beide beiden beim bein bereits beruf besser beste besten bild
bilder bitte bleiben bleibt blick boden brauche brauchen braucht bringen bringt buch bücher dabei dachte
dafür daher damals damit danach dank danke dann daran darauf darum dass davon dazu denen denke denken denn
deren derzeit deshalb dessen dich dicht diese diesem diesen dieser dieses ding dinge doch dort draußen drei
drin drinnen dritte durch eben ebenso ecke eher eigen eigene eigenen eigentlich eine einem einen einer eines
einfach einige einmal eins ende endlich erst erste ersten euch euro eure euren etwas fahren fahrt fall falls
falsch familie farbe fast fehler feld fenster ferner fertig feuer film finde finden findet firma fragen
frage fragt frau frauen frei freund freunde freut früh früher fünf führen führt ganz ganze ganzen gar
geben gegen gehen geht geld gemacht genau genug gerade gern gerne gesagt geschichte gestern gewesen gibt
ging glaube glauben gleich gott grad große großen grund gruppe gute guten habe haben halb halt hand hast
hatte hatten haus hause heißt helfen heute hier hilft hinten hinter hoch hoffe holen hören immer innen
jahr jahre jahren jede jedem jeden jeder jedes jemand jetzt jung junge kaum kein keine keinem keinen keiner
kennen kennt kind kinder klar klein kleine kleinen kommen kommt konnte konnten kopf kosten kostet kraft
kunde kunden kurz lage land lange langsam lassen lasst lässt laufen läuft leben lehrer leicht leider
leiten leiter leute lieber liebe liegt links lösung machen macht mädchen mann mal manchmal mann männer
markt mehr meine meinem meinen meiner meines meinte meinung meist meisten mensch menschen mich mindestens
mittag mitte möchte möchten mögen moment monat morgen müssen muss musste mutter nach nachher nacht nahe
name natürlich neben nehmen nein neue neuen neun nicht nichts noch nochmal nummer oben oder offen ohne
okay ordnung papa paar person plan platz plötzlich problem projekt punkt rechts recht reden regel richtig
ruhig sache sachen sagen sagt sagte satz schau schauen schlecht schließlich schnell schon schön schreiben
schule schwer sechs sehen sehr seid sein seine seinem seinen seiner seit seite selber selbst sich sicher
sieben sieht sind singen sitzen soll sollen sollte sondern sonst sowas sowie später spiel spielen spricht
stadt stand stark statt stehen steht stelle stellen stimme stimmt straße stück stunde suchen tage tagen
teil teile thema tisch tochter treffen trotzdem tun über überall übrigens uhr umso unten unter unsere
unseren unser vater viel viele vielen vielleicht vier voll völlig vorbei vorher vorne wagen wahr während
wann warum was weil weiter weiß weit welche welchem welchen welcher welt wenig wenige wenn werden wichtig
wieder wiederum wiese wieso will wird wirklich wissen woche wochen wohl wollen wollte wort worte wurde
wurden zahl zahlen zehn zeigen zeigt zeit zeiten ziel ziemlich zimmer zuerst zukunft zurück zusammen zwar
zwei zweite zwischen
""".split())

__all__ = ["COMMON_DE"]
