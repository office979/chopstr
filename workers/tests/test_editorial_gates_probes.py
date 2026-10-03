"""Regressionsproben aus dem Review AP4 (87 Proben): Fehlalarm- und Recall-Erwartung je Gate.

Kategorie S: typische Clip-Anfänge (Fehlalarmprobe), R: Recall-Fälle nach Master-Prompt 27. Jede Probe ist
``(id, kategorie, Sätze, first, last, erwartete Treffer)``; Sprecher A fragt, B ist der Gast. Ziel aus dem
Review: Fehlalarme je Gate unter 10 Prozent auf den S-Sätzen, Recall der R-Sätze mindestens 80 Prozent. Die
Proben stammen wörtlich aus dem Review-Skript; Dialektproben (CH, AT) sind markiert.
"""

from __future__ import annotations

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import dach_nlp
from chopstr_worker.pipeline import editorial_gates as G

A, B = "A", "B"
GATES = [k for k in G.GATE_KEYS if k not in G.FLAG_ONLY]
MAX_FALSE_ALARM_RATE = 0.10
MIN_RECALL = 0.80

# (id, kategorie, Sätze, first, last, erwartete Treffer)
PROBES = [  # fmt: skip
 # --- typische Clip-Anfaenge (ein Satz plus neutraler Folgesatz) ---
 ("S01","S",[(B,"Das heißt, wir müssen die Preise jedes Jahr neu verhandeln."),(B,"Wir machen das jeden Januar.")],0,1,{"back_reference"}),
 ("S02","S",[(B,"Das Problem ist, dass viele Gründer ihre Kosten nie durchrechnen."),(B,"Wir haben das selbst erlebt.")],0,1,set()),
 ("S03","S",[(B,"Das war für uns der teuerste Fehler im ganzen Jahr."),(B,"Wir haben daraus gelernt.")],0,1,{"back_reference"}),
 ("S04","S",[(B,"Das war für uns ein Schock, als die Bank im März angerufen hat."),(B,"Wir hatten keine Reserve.")],0,1,set()),
 ("S05","S",[(B,"Das Wichtigste ist, dass man vorher rechnet."),(B,"Wer nicht rechnet, verliert Geld.")],0,1,set()),
 ("S06","S",[(B,"Die Frage ist, wie lange man so etwas durchhält."),(B,"Bei uns waren es drei Jahre.")],0,1,set()),
 ("S07","S",[(B,"Es gibt in jeder Branche Leute, die ihre Preise unterschätzen."),(B,"Bei uns im Handwerk ist das besonders schlimm.")],0,1,set()),
 ("S08","S",[(B,"Sie müssen wissen, dass wir damals nur zu dritt waren."),(B,"Ein Büro hatten wir auch keins.")],0,1,set()),
 ("S09","S",[(B,"Sie müssen sich das so vorstellen: Wir hatten kein Lager und kein Geld."),(B,"Trotzdem haben wir angefangen.")],0,1,set()),
 ("S10","S",[(B,"Ihr kennt das bestimmt: Man steht morgens auf und hat schon zwanzig Mails."),(B,"Genau so ging es mir jahrelang.")],0,1,set()),
 ("S11","S",[(B,"Ihr kennt das Problem mit den Lieferzeiten."),(B,"Wir haben es mit zwei Lieferanten gelöst.")],0,1,set()),
 ("S12","S",[(B,"Wir haben 2019 die Preise um 30 Prozent gesenkt."),(B,"Ein halbes Jahr später war die Marge weg.")],0,1,set()),
 ("S13","S",[(B,"Wir haben das zwei Jahre lang gemacht."),(B,"Am Ende hatten wir mehr Retouren.")],0,1,{"back_reference"}),
 ("S14","S",[(B,"Wir haben damals alles auf eine Karte gesetzt."),(B,"Es ist gut gegangen.")],0,1,set()),
 ("S15","S",[(B,"Er hat mir den Schlüssel gegeben und ist gegangen."),(B,"Ich stand allein im Büro.")],0,1,{"unresolved_pronoun"}),
 ("S16","S",[(B,"Mein Vater hat mir den Schlüssel gegeben, und er ist einfach gegangen."),(B,"Ich stand allein im Büro.")],0,1,set()),
 ("S17","S",[(B,"Thomas hat damals gesagt, er kündigt sofort."),(B,"Zwei Wochen später war er weg.")],0,1,set()),
 ("S18","S",[(B,"Ich habe gekündigt, und das war die beste Entscheidung meines Lebens."),(B,"Heute habe ich drei Angestellte.")],0,1,set()),
 ("S19","S",[(B,"Ihr Unternehmen braucht einen klaren Preis für jede Leistung."),(B,"Ohne Preis kein Vertrauen.")],0,1,set()),
 ("S20","S",[(B,"Das ist so: Wer nicht rechnet, verliert."),(B,"Ich habe es selbst erlebt.")],0,1,set()),
 ("S21","S",[(B,"Das muss man sich mal vorstellen: drei Jahre ohne einen Tag Urlaub."),(B,"Heute würde ich das nicht mehr machen.")],0,1,set()),
 ("S22","S",[(B,"Dieses Jahr haben wir zum ersten Mal Gewinn gemacht."),(B,"Ein kleiner, aber immerhin.")],0,1,set()),
 ("S23","S",[(B,"Ihr müsst euch vorstellen, wir hatten null Kunden."),(B,"Null.")],0,1,set()),
 ("S24","S",[(B,"Du musst dir das so vorstellen: kein Geld, kein Team, kein Plan."),(B,"Und trotzdem haben wir angefangen.")],0,1,set()),
 ("S25","S",[(B,"Dem Kunden ist das völlig egal."),(B,"Er will nur, dass es funktioniert.")],0,1,set()),
 ("S26","S",[(B,"Der war damals schon pleite."),(B,"Wir haben es nur nicht gewusst.")],0,1,{"back_reference"}),
 ("S27","S",[(B,"Die haben uns einfach nie bezahlt."),(B,"Drei Rechnungen, alle offen.")],0,1,{"back_reference"}),
 ("S28","S",[(B,"Deren Chef hat uns dann persönlich angerufen."),(B,"Das war ungewöhnlich.")],0,1,{"unresolved_pronoun"}),
 ("S29","S",[(B,"Was ich gelernt habe: Preise sind Positionierung."),(B,"Billig ist keine Strategie.")],0,1,set()),
 ("S30","S",[(B,"Und genau das hat uns am Ende gerettet."),(B,"Ohne die Reserve wären wir pleite gewesen.")],0,1,{"back_reference"}),
 ("S31","S",[(B,"Ganz ehrlich: Das hat mich drei Jahre meines Lebens gekostet."),(B,"Ich würde es trotzdem wieder tun.")],0,1,{"back_reference"}),
 ("S32","S",[(B,"Preise sind Positionierung."),(B,"Viele Gründer verstehen das erst nach Jahren."),(B,"Wie gesagt, Preise sind Positionierung.")],0,2,set()),
 ("S33","S",[(B,"Grundsätzlich ist es so, dass wir jede Offerte zweimal prüfen."),(B,"Das spart uns viel Ärger.")],0,1,set()),  # CH Offerte
 ("S34","S",[(B,"Wir haben das Znüni für alle gestrichen, und es hat niemanden gestört."),(B,"Ehrlich nicht.")],0,1,set()),  # CH
 ("S35","S",[(B,"Heuer haben wir das erste Mal eine Jause für alle bestellt."),(B,"Die Stimmung war sofort besser.")],0,1,set()),  # AT
 ("S36","S",[(B,"Das ist halt so bei uns in Wien."),(B,"Man redet nicht über Geld.")],0,1,{"back_reference"}),  # AT, Rueckverweis
 ("S37","S",[(B,"Es war ein Montag, als die Bank anrief."),(B,"Ich weiß es noch genau.")],0,1,set()),
 ("S38","S",[(B,"Am Ende zählt nur, was auf dem Konto ist."),(B,"Alles andere ist Eitelkeit.")],0,1,set()),
 ("S39","S",[(B,"Weißt du, was das größte Problem ist?"),(B,"Die meisten fragen nie nach dem Preis.")],0,1,set()),  # rhetorisch, Monolog
 ("S40","S",[(B,"Kennt ihr das?"),(B,"Man arbeitet zwölf Stunden und am Ende bleibt nichts.")],0,1,set()),  # Monolog an Publikum
 ("S41","S",[(B,"Und wissen Sie, was dann passiert ist?"),(B,"Der Kunde hat sich nie wieder gemeldet.")],0,1,set()),  # foermlich, Monolog
 ("S42","S",[(B,"Das ist doch verrückt, oder?"),(B,"Wir zahlen mehr Miete als Löhne.")],0,1,{"back_reference"}),
 ("S43","S",[(B,"Wir wollten später mehr verdienen als unsere Eltern."),(B,"Das hat auch geklappt.")],0,1,set()),
 ("S44","S",[(B,"Wie man so schön sagt:"),(B,"Zeit ist Geld."),(B,"Bei uns stimmt das wirklich.")],1,2,set()),
 ("S45","S",[(B,"Gib nie mehr aus, als du einnimmst."),(B,"Das ist die einzige Regel, die zählt.")],0,1,set()),
 ("S46","S",[(B,"Wir haben die Preise erhöht."),(B,"Und das hat uns keinen einzigen Kunden gekostet, ich übertreibe nicht.")],0,0,set()),
 ("S47","S",[(B,"Preise sind Positionierung."),(B,"Das haben viele Gründer noch nicht verstanden.")],0,0,set()),
 ("S48","S",[(B,"Wir stellen nur noch nach Haltung ein."),(B,"Und das klappt nicht immer, aber meistens sehr gut.")],0,0,{"boundary_negation_condition"}),
 ("S49","S",[(B,"Natürlich haben wir am Anfang massiv Fehler beim Preis gemacht."),(B,"Jeder macht die.")],0,1,set()),  # Antwort ohne Frage davor
 ("S50","S",[(A,"Wie lange hast du für den Umbau gebraucht?"),(A,"Und was hat dich der Umbau gekostet?"),(B,"Drei Jahre und gut 200.000 Euro."),(B,"Das war es aber wert.")],0,3,set()),  # Doppelfrage
 ("S51","S",[(B,"Wir haben die Preise gesenkt."),(B,"Genauer gesagt haben wir die Preise im Frühjahr um zehn Prozent gesenkt.")],0,0,set()),
 ("S52","S",[(B,"Die Kunden sagen uns jede Woche, dass sie den Service lieben."),(B,"Das stimmt nicht immer, aber meistens.")],0,0,{"boundary_negation_condition"}),
 # --- Recall-Faelle Master-Prompt 27 ---
 ("R01","R",[(B,"Rabatte zum Jahresende lohnen sich."),(B,"Zumindest nicht für kleine Läden.")],0,0,{"boundary_negation_condition"}),
 ("R02","R",[(B,"Die Vier-Tage-Woche ist für jeden Betrieb das Richtige."),(B,"Nicht bei uns.")],0,0,{"boundary_negation_condition"}),
 ("R03","R",[(B,"Wir empfehlen die Vier-Tage-Woche."),(B,"Aber nur, wenn die Abläufe dokumentiert sind.")],0,0,{"boundary_negation_condition"}),
 ("R04","R",[(B,"Wenn ihr ein kleines Team habt, gilt:"),(B,"Die Vier-Tage-Woche lohnt sich sofort.")],1,1,{"boundary_negation_condition"}),
 ("R05","R",[(B,"Wir würden sofort expandieren."),(B,"Falls das Geld reicht.")],0,0,{"boundary_negation_condition"}),
 ("R06","R",[(B,"Homeoffice funktioniert für alle."),(B,"Es sei denn, ihr habt Schichtbetrieb.")],0,0,{"boundary_negation_condition"}),
 ("R07","R",[(B,"Wir sprechen vor jeder Preisänderung mit Stammkunden."),(B,"Außer im Sommer.")],0,0,{"boundary_negation_condition"}),
 ("R08","R",[(B,"Die Vier-Tage-Woche funktioniert."),(B,"Aber nöd im Detailhandel.")],0,0,{"boundary_negation_condition"}),  # CH
 ("R09","R",[(B,"Eine Kassa brauchst du heute nicht mehr."),(B,"Na, im Heurigen schon.")],0,0,{"boundary_negation_condition"}),  # AT "na" = nein
 ("R10","R",[(B,"Online-Werbung bringt gar nichts."),(B,"Nie.")],0,0,set()),  # Verstaerkung, kein Fehlalarm erwartet
 ("R11","R",[(B,"Werbung braucht man eigentlich gar nicht."),(B,"Ich korrigiere mich."),(B,"Werbung braucht man schon, nur weniger als früher.")],0,0,{"later_correction"}),
 ("R12","R",[(B,"Werbung braucht man eigentlich gar nicht."),(B,"Ich muss mich korrigieren."),(B,"Werbung braucht man schon, nur weniger als früher.")],0,0,{"later_correction"}),
 ("R13","R",[(B,"Wir hatten vierzehn Filialen."),(B,"Sorry, ich meinte natürlich vier Filialen, nicht vierzehn.")],0,0,{"later_correction","boundary_negation_condition"}),
 ("R14","R",[(B,"Werbung braucht man eigentlich gar nicht."),(B,"Nein, Quatsch."),(B,"Werbung braucht man schon, nur gezielter.")],0,0,{"later_correction"}),
 ("R15","R",[(B,"Werbung braucht man eigentlich gar nicht."),(B,"Das stimmt so nicht ganz."),(B,"Werbung braucht man schon, nur gezielter.")],0,0,{"later_correction","boundary_negation_condition"}),
 ("R16","R",[(B,"Wir hatten 400 Kunden im ersten Jahr."),(B,"Korrektur: Es waren 40 Kunden im ersten Jahr.")],0,0,{"later_correction"}),
 ("R17","R",[(B,"Mein früherer Chef hat immer gesagt:"),(B,"Kaltakquise ist tot.")],1,1,{"reported_speech"}),
 ("R18","R",[(B,"Viele Berater erzählen einem dann:"),(B,"Ihr müsst unbedingt auf TikTok.")],1,1,{"reported_speech"}),
 ("R19","R",[(B,"Viele sagen, Kaltakquise ist tot."),(B,"Das sehe ich komplett anders.")],0,0,{"reported_speech"}),
 ("R20","R",[(B,"Die Konkurrenz behauptet, Kaltakquise ist tot."),(B,"Stimmt aber nicht.")],0,0,{"reported_speech","boundary_negation_condition"}),
 ("R21","R",[(B,"Laut unserem Steuerberater lohnt sich die GmbH nie."),(B,"Das ist falsch.")],0,0,{"reported_speech"}),
 ("R22","R",[(B,"Er ist ja offensichtlich kein guter Chef."),(B,"Das sieht man an der Fluktuation.")],0,1,{"unresolved_pronoun"}),
 ("R23","R",[(B,"Sie hat dann jede Schicht selbst mitgemacht."),(B,"Auch nachts.")],0,1,{"unresolved_pronoun"}),
 ("R24","R",[(B,"Ihm war das völlig egal."),(B,"Hauptsache, der Umsatz stimmt.")],0,1,{"unresolved_pronoun","back_reference"}),
 ("R25","R",[(A,"Hast du jemals überlegt, die Firma zu verkaufen?"),(B,"Nein, nie ernsthaft.")],1,1,{"speaker_turn"}),
 ("R26","R",[(A,"Würdest du es wieder machen?"),(B,"Sofort.")],1,1,{"speaker_turn"}),
 ("R27","R",[(A,"Was war dein größter Fehler?"),(A,"Ich frage, weil viele Hörer gerade gründen.")],0,1,{"open_question_unanswered"}),
 ("R28","R",[(A,"Und der größte Fehler?"),(A,"Ich frage, weil viele Hörer gerade gründen.")],0,1,{"open_question_unanswered"}),
 ("R29","R",[(B,"Wir haben alles durchgerechnet."),(B,"Und was kam am Ende heraus?")],0,1,{"open_question_unanswered"}),
 ("R30","R",[(B,"Die Marge war weg."),(B,"Gleich erkläre ich, warum.")],0,1,{"forward_reference"}),
 ("R31","R",[(B,"Das Ergebnis war eindeutig:")],0,0,{"forward_reference"}),
 ("R32","R",[(B,"Dazu komme ich später noch."),(B,"Erst die Zahlen.")],0,1,{"forward_reference"}),
 ("R33","R",[(B,"Davon kann ich nur abraten."),(B,"Es kostet zu viel.")],0,1,{"back_reference"}),
 ("R34","R",[(A,"Kennst du das Problem?"),(B,"Ja."),(A,"Und wie hast du es gelöst?"),(B,"Mit einem festen Plan.")],2,3,set()),
 ("R35","R",[(B,"Das isch eifach so, mir händ kei Ziit gha."),(B,"Punkt.")],0,1,{"back_reference"}),  # CH Mundart
]


@pytest.fixture(autouse=True)
def no_spacy(monkeypatch):
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)


def _failed(turns, first, last) -> set[str]:
    words, sents = G.from_sentence_texts([{"speaker": s, "text": t} for s, t in turns])
    return set(G.run_gates(words, sents, first, last, editorial.load(2))["failed"])


def test_there_are_87_probes():
    assert len(PROBES) == 87
    assert len({p[0] for p in PROBES}) == 87


@pytest.mark.parametrize(("pid", "cat", "turns", "first", "last", "expected"), PROBES, ids=[p[0] for p in PROBES])
def test_probe(pid, cat, turns, first, last, expected):
    assert _failed(turns, first, last) == expected


def test_false_alarm_rate_and_recall_per_gate():
    stats = {g: {"fp": 0, "neg": 0, "tp": 0, "pos": 0} for g in GATES}
    for _pid, cat, turns, first, last, expected in PROBES:
        got = _failed(turns, first, last)
        for g in GATES:
            if cat == "S" and g not in expected:
                stats[g]["neg"] += 1
                stats[g]["fp"] += g in got
            if cat == "R" and g in expected:
                stats[g]["pos"] += 1
                stats[g]["tp"] += g in got
    for g, s in stats.items():
        assert s["fp"] / max(s["neg"], 1) < MAX_FALSE_ALARM_RATE, (g, s)
        if s["pos"]:
            assert s["tp"] / s["pos"] >= MIN_RECALL, (g, s)
