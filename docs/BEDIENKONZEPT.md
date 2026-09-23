# Bedienkonzept

Stand: 23.09.2026. Etappen 1 und 2 sind umgesetzt, Etappen 3 und 4 stehen aus.

Dieses Dokument legt fest, wie chopstr bedient wird. Es steht über der bestehenden
Oberfläche: wo die heutige App abweicht, wird die App geändert, nicht dieses Dokument.

`docs/ENTSCHEIDUNGEN.md` regelt, was das Produkt tut. Dieses Dokument regelt, wie ein
Mensch es benutzt.

---

## 1. Die Entscheidung, die alles andere bestimmt

**Zielgruppe ist ab sofort der Laie, nicht der Redakteur.**

Maßstab: Eine Person ohne Video-, Marketing- oder Software-Vorwissen, etwa 13 Jahre alt,
öffnet chopstr zum ersten Mal und kommt ohne Hilfe zu einem fertigen Clip.

Das ist eine Neuausrichtung. Die bisherige Doku beschreibt als Zielgruppe
"Agenturen, Redakteur:innen" und setzt Urteilskompetenz voraus
(Transkriptfehler erkennen, Kandidaten mit Begründung ablehnen, Hooks selbst schreiben).
Diese Annahme gilt nicht mehr für die Oberfläche.

**Was sich dadurch ändert:**

| Bisher | Ab jetzt |
|---|---|
| Nutzer entscheidet, wir fragen | Wir entscheiden sinnvoll, Nutzer kann ändern |
| Fachbegriff, weil er präzise ist | Alltagswort, Fachbegriff höchstens in Klammern |
| Alle Informationen sichtbar, Nutzer filtert | Eine Information sichtbar, Rest auf Anfrage |
| Warnung zeigen, Nutzer versteht schon | Warnung nur, wenn der Nutzer handeln kann |

**Was sich nicht ändert:** Keine Funktion wird gelöscht. Alles Gebaute bleibt erreichbar.
Es rückt nur aus dem Weg.

---

## 2. Die Persona

**Lena, 13.** Hat ein Video von einem Vortrag ihres Vaters. Will daraus etwas für TikTok.
Kennt TikTok, kennt YouTube. Kennt nicht: Transkript, Diarisierung, LUFS, Reframe,
Rubrik, Gate, Payoff, Preset, Provenienz, Kandidat.

**Lenas Fragen in dieser Reihenfolge:**

1. Wo lade ich das Video hoch?
2. Wie lange dauert das?
3. Was hat der Computer gefunden?
4. Ist das gut? Nehme ich das?
5. Wie sieht das fertig aus?
6. Wie kriege ich es auf mein Handy?

**Jede Seite der App beantwortet genau eine dieser Fragen.** Wenn eine Seite zwei
beantwortet, wird sie geteilt. Wenn eine Seite keine beantwortet, gehört sie nicht in
den Hauptweg.

---

## 3. Das Rückgrat: fünf Schritte

Die App hat einen einzigen Hauptweg. Er ist auf jeder Seite des Hauptwegs sichtbar,
oben, immer gleich.

```
①  Video hochladen
②  Text prüfen          (überspringbar, standardmäßig übersprungen)
③  Momente auswählen     ← hier entsteht der Wert
④  Feinschliff           (überspringbar)
⑤  Fertig und posten
```

**Regeln für die Schrittleiste:**

- Erledigte Schritte: Haken, anklickbar, man kann zurück.
- Aktueller Schritt: hell hervorgehoben.
- Kommende Schritte: gedimmt, nicht anklickbar, aber sichtbar. Lena soll wissen,
  was noch kommt, bevor sie anfängt.
- Schritt 2 und 4 tragen sichtbar das Wort "optional".
- Die Leiste erscheint nur innerhalb eines Projekts. Auf Übersichtsseiten nicht.

**Warum genau diese fünf:** Sie bilden die tatsächlichen Mensch-Gates ab. Die Pipeline
hat zwei Punkte, an denen ein Mensch zwingend entscheiden muss (Kandidaten-Review,
optional Gast-Freigabe). Alles andere ist Warten oder Feinschliff. Die Leiste macht
sichtbar, dass Schritt 3 der einzige ist, der wirklich Arbeit bedeutet.

---

## 4. Die Hauptnavigation

**Heute:** `Projekte · Upload · Markenprofil · Entwickler` plus ein Knopf "Neues Projekt".

**Neu:** Drei Einträge. Mehr nicht.

```
Meine Videos        Aussehen        Auswertung
```

| Eintrag | Führt zu | Enthält |
|---|---|---|
| **Meine Videos** | Projektliste (Startseite) | Alle Projekte, Knopf "Neues Video" |
| **Aussehen** | bisher "Markenprofil" | Farben, Logo, Schrift, Wörterbuch |
| **Auswertung** | neue Sammelseite | Serien, Experimente, Berichte |

**Was verschwindet aus der Hauptnavigation:**

- **"Entwickler"** wandert nach Einstellungen. API-Dokumentation ist nichts, was Lena
  im Hauptmenü braucht. Sie bleibt vollständig erhalten unter
  `Einstellungen > Für Entwickler`.
- **"Upload"** entfällt als eigener Eintrag. Es gibt nur noch den Knopf "Neues Video"
  auf der Startseite. Ein Weg, nicht zwei.

**Was neu sichtbar wird:**

- **Serien, Experimente, Berichte** sind heute nur über einen Knopf auf der Clips-Seite
  eines einzelnen Projekts erreichbar. Drei fertig gebaute Bereiche, praktisch
  unauffindbar. Sie bekommen mit "Auswertung" einen festen Platz.

**Begründung "Auswertung" statt drei Einträgen:** Lena braucht am Anfang keinen davon.
Sie sollen sichtbar sein, aber nicht mit dem Hauptweg konkurrieren. Ein Eintrag, drei
Unterseiten.

---

## 5. Seite für Seite

Für jede Seite gilt: **eine Aufgabe, ein Hauptknopf.** Der Hauptknopf ist der einzige
weiße Knopf auf der Seite. Alles andere ist Ghost-Pill oder Textlink.

### 5.1 Startseite: Meine Videos

**Aufgabe:** Lena sieht, was sie hat, und startet etwas Neues.

- Pro Video eine Karte: Standbild, Titel, Dauer, **ein** Statussatz in Alltagssprache.
- Statussätze ersetzen die technischen Zustände:

| Technisch | Was Lena liest |
|---|---|
| `uploading` | Wird hochgeladen |
| `ingesting` | Wird vorbereitet |
| `transcribing` | Computer hört zu |
| `analyzing` | Computer sucht gute Stellen |
| `scoring` | Computer bewertet die Stellen |
| `ready`, keine Entscheidung | **4 Momente gefunden. Jetzt auswählen** |
| `ready`, Clips gerendert | 3 Clips fertig |
| `failed` | Etwas ist schiefgegangen. Nochmal versuchen |

- Ein Knopf pro Karte, nicht fünf. Der Knopf zeigt den **nächsten sinnvollen Schritt**.
  Heute zeigt die Karte bis zu fünf gleichwertige Knöpfe
  (Clips, Transkript, Review, Details, Löschen). Das ist eine Entscheidung, die Lena
  nicht treffen kann und nicht treffen soll.
- Löschen verschwindet aus der Karte und wandert in die Projektseite.
- Leerer Zustand: großer Knopf "Erstes Video hochladen" plus ein Satz, was passiert.

### 5.2 Schritt 1: Video hochladen

**Aufgabe:** Datei rein, sonst nichts.

Die heutige Upload-Seite verlangt vor dem Hochladen: Titel, Markenprofil, Datei,
Rechtestatus, bei Fremdmaterial drei weitere Felder, eine Pflicht-Checkbox, plus fünf
Felder Redaktions-Briefing. **Das ist eine Formular-Wand vor dem ersten Erfolgserlebnis.**

**Neu, in dieser Reihenfolge:**

1. **Nur das Ablegefeld.** Groß, mittig. "Video hierher ziehen".
2. Sobald die Datei liegt, startet der Upload sofort. Titel wird aus dem Dateinamen
   vorbelegt und ist änderbar.
3. **Eine** Frage darunter, während schon hochgeladen wird:
   "Ist das dein eigenes Video?" mit zwei Knöpfen: `Ja, meins` / `Nein, von jemand anderem`.
   Bei "Nein" klappen die drei Felder für Urheber auf. Bei "Ja" passiert nichts weiter.
4. Das Redaktions-Briefing entfällt an dieser Stelle vollständig. Es wandert als
   "Wünsche angeben (optional)" in Schritt 3, wo es sinnvoll wird, weil Lena dann sieht,
   was der Computer gefunden hat.

**Rechtsbestätigung:** Bleibt Pflicht, aber als eine Frage mit zwei Knöpfen statt als
Dropdown plus Checkbox. Die juristische Wirkung ist identisch, der Audit-Eintrag auch.

### 5.3 Warten: die Fortschrittsanzeige

**Aufgabe:** Lena weiß, dass etwas passiert und wie lange es noch dauert.

Die heutige PipelineLive-Komponente ist technisch gut (Server-Sent Events, Live-Updates,
sechs Schritte). Sie benennt die Schritte nur falsch.

| Technisch | Was Lena liest |
|---|---|
| Prüfung & Extraktion | Video wird vorbereitet |
| Transkription | Der Computer hört zu und schreibt mit |
| Sprechertrennung | Wer spricht wann |
| Sprachanalyse | Sätze werden sortiert |
| Kandidaten | Gute Stellen werden gesucht |
| Bereit | Fertig |

**Zusätzlich:** Eine Restzeit-Schätzung. "Noch etwa 4 Minuten." Ohne sie ist jede
Wartezeit gefühlt endlos. Die Schätzung kann grob sein, sie muss nur da sein.

**Detailzeilen wie "56 Wörter in 1 Fenstern" oder "Sprechertrennung übersprungen:
HF_TOKEN fehlt (pyannote)"** verschwinden aus der Hauptansicht. Siehe Abschnitt 7.

### 5.4 Schritt 2: Text prüfen (optional)

**Aufgabe:** Falsch verstandene Wörter korrigieren.

Wird standardmäßig **übersprungen**. Lena landet nach dem Warten direkt in Schritt 3.
Der Weg hierher bleibt über die Schrittleiste offen.

Wenn sie herkommt:

- Nur Wörter mit niedriger Konfidenz sind markiert, alles andere ist normaler Text.
- Über dem Text steht **ein** Satz: "Der Computer war sich bei 1 Wort unsicher.
  Klick es an, wenn es falsch ist."
- Das Modellkürzel `whisper-large-v3-turbo-german-int8_float32` verschwindet aus der
  Ansicht. Es gehört in die Detailansicht.
- Der Schalter "Füllwörter entfernen" bekommt ein Beispiel statt einer Zahl:
  heute steht dort "0 harte Füller, 0 Vorschläge. Modalpartikeln bleiben."

### 5.5 Schritt 3: Momente auswählen

**Das ist die wichtigste Seite der App.** Hier entsteht der gesamte Wert.

**Aufgabe:** Lena entscheidet pro gefundenem Moment: nehmen oder nicht.

**Aufbau:** Links die Vorschau, rechts genau **ein** Moment. Nicht eine Liste. Einer.
Darunter zwei große Knöpfe: `Nehmen` und `Überspringen`. Darüber ein Zähler:
"Moment 2 von 4".

**Was pro Moment zu sehen ist:**

1. Die Videostelle, abspielbar, automatisch am richtigen Punkt.
2. Der gesprochene Satz als Text.
3. **Ein** Qualitätssatz in Worten, keine Zahl:
   - 8 bis 10: "Sehr stark"
   - 6 bis 8: "Stark"
   - 4 bis 6: "Geht so"
   - unter 4: wird gar nicht erst gezeigt
4. Falls etwas dagegen spricht: **ein** Satz, was.

**Was verschwindet aus der Hauptansicht:**
Rubrik-Einzelwerte, "5 von 5 Pflichtkriterien", "Payoff zuerst" als Strukturlabel,
"Heuristik ohne Sprachmodell", die Zahl 6,7 als Zahl, Story-Graph. Alles bleibt unter
"Warum dieser Moment?" erreichbar. Eure Kernversprechen "jede Auswahl wird erklärt"
bleibt damit erfüllt, nur auf Abruf statt als Wand.

**Nach "Nehmen":** Keine Plattform-Auswahl. chopstr rendert **standardmäßig nur
Hochformat** (9:16, gilt für TikTok, Reels und Shorts gleichzeitig). LinkedIn (4:5)
ist ein Zusatz, den Lena in Schritt 5 anfordern kann, wenn sie es braucht.

**Das ist die wichtigste einzelne Vereinfachung in diesem Konzept.** Sie halbiert die
Clip-Anzahl, die Renderkosten und die Komplexität von Schritt 5, ohne eine Funktion
zu verlieren.

**Tastenkürzel** (J/K/A/R) bleiben, werden aber nicht mehr als Hinweiszeile angezeigt.
Sie stehen unter "Tastenkürzel" am Seitenfuß.

### 5.6 Schritt 4: Feinschliff (optional)

**Aufgabe:** Text im Video ändern, Bildausschnitt korrigieren.

Ist heute das "Hook-Studio" und über die Clip-Karte verstreut. Wird zusammengeführt.

- Zwei Dinge, mehr nicht: **Text im Video** und **Bildausschnitt**.
- Die fünf KI-Hook-Varianten werden als Vorschläge zum Anklicken gezeigt, nicht als
  Liste zum Vergleichen. Ein Klick übernimmt, das Feld bleibt frei editierbar.
- Wortgrenzen (12 gesprochen, 9 auf dem Bild) werden als Restzähler gezeigt, nicht als
  Fehlermeldung nach dem Tippen.
- "Neu rendern" heißt **"Änderungen übernehmen"**.

### 5.7 Schritt 5: Fertig und posten

**Aufgabe:** Clip ansehen, runterladen oder posten.

**Heute der größte Bruch:** vier nahezu identische Spalten, je vierzehn Bedienelemente,
sechzehn Warnungen, über sechzig anklickbare Dinge auf einem Bildschirm für einen
einzigen Moment.

**Neu: die Bühne.**

```
                    ┌─────────────────────┐
   Hochformat       │                     │      Quer (LinkedIn)
   ●────────────    │      Ein Video      │     ────────────○
                    │        groß         │
                    │                     │
                    └─────────────────────┘

                    [  Herunterladen  ]        ← der eine weiße Knopf

                    Posten auf TikTok, Reels, Shorts
                    Jemanden fragen, bevor es rausgeht
                    Text oder Bild ändern
                    Details für Profis  ▸
```

- **Ein** Video, groß. Format-Umschalter darüber.
- **Ein** Hauptknopf: `Herunterladen`. Er funktioniert immer und ist der
  verlässliche Ausweg, wenn alles andere zu kompliziert wird.
- Alles Weitere als Textlinks darunter, in der Reihenfolge, in der Lena es braucht.
- SRT und VTT verschwinden von der Oberfläche. Sie liegen unter "Details für Profis".
  Lena weiß nicht, was eine SRT-Datei ist, und braucht sie nicht.

**"2 Gates offen" wird abgeschafft.** Ersetzt durch eine Klartext-Liste, die sagt,
was fehlt und wohin man klickt:

```
Noch nicht bereit zum Posten:
  ○ Vertrag fehlt          → Jetzt annehmen
  ○ Freigabe fehlt         → Freigabe anfordern
```

Ein Sackgassen-Badge wird zu zwei erledigbaren Aufgaben. Wenn nichts offen ist,
steht die Liste nicht da.

---

## 6. Die Clip-Karte: von 14 auf 5

Zur Nachvollziehbarkeit, was heute pro Plattform-Spalte steht und was davon bleibt.

| Heute | Neu |
|---|---|
| Abspielen | bleibt (die Bühne selbst) |
| Status-Haken + "Gerendert" | bleibt, als ein Wort |
| "-16,4 LUFS, -1,5 dBTP" | Details für Profis |
| Warnung C2PA | Abschnitt 7, Klasse C |
| Warnung Reframe/Detektor | Abschnitt 7, Klasse C |
| "Zu schnell (20 Z/s)" ×2 | Abschnitt 7, Klasse B, zusammengefasst |
| Gast-Freigabe anfordern | bleibt, als Textlink |
| MP4 / SRT / VTT | nur MP4, als Hauptknopf "Herunterladen" |
| Hook-Studio | bleibt, als "Text oder Bild ändern" |
| Neu rendern | in Schritt 4 integriert |
| Ton-aus-Vorschau | entfällt, Vorschau ist standardmäßig stumm |
| Löschen | Details für Profis |
| Bildausschnitt (Dropdown) | in Schritt 4 integriert |
| Serie zuordnen (Dropdown) | Details für Profis |
| Veröffentlichen + Gates-Badge | "Posten auf ..." plus Klartext-Liste |

**14 Elemente je Spalte × 4 Spalten = 56.** Neu: **5 sichtbare Elemente insgesamt.**

---

## 7. Warnungen: drei Klassen

Der heutige Hauptgrund für den Eindruck "unfertig": Die App beschwert sich
ununterbrochen über ihren eigenen Serverzustand, in derselben Farbe, in der sie echte
Nutzeraufgaben anzeigt. Drei von vier Warnungen auf der Clips-Seite kann der Nutzer
gar nicht beheben.

**Ab sofort gilt vor jeder Meldung die Frage: Kann der Nutzer daraufhin etwas tun?**

### Klasse A: Nutzer muss handeln

Farbe Orange, wie im Design-System festgelegt. Immer mit klickbarer Lösung.

Beispiele: Vertrag nicht angenommen, Freigabe fehlt, Kontingent aufgebraucht.

### Klasse B: Nutzer kann handeln, muss aber nicht

Neutral, unaufdringlich, mit Vorschlag.

Beispiel heute: "Zu schnell (20 Z/s): 'verloren,'".
Neu: "Zwei Untertitel laufen schnell durch. Kürzen?" mit einem Knopf, der es tut.

### Klasse C: Systemzustand, Nutzer kann nichts tun

**Erscheint nicht in der Hauptansicht.** Gehört unter "Details für Profis" und in die
Server-Logs.

Beispiele: "C2PA übersprungen: c2patool nicht installiert",
"Reframe: neutraler Crop, kein Detektor",
"Sprechertrennung übersprungen: HF_TOKEN fehlt (pyannote)".

**Wichtig, damit das keine Verschlechterung ist:** Eure Entscheidung P6 verlangt
ausdrücklich, dass fehlende Fähigkeiten sichtbar bleiben und nicht stillschweigend
übergangen werden. Das bleibt erfüllt. Die Information verschwindet nicht, sie wandert
an die Stelle, wo die Person sitzt, die etwas damit anfangen kann. Zusätzlich
erscheint sie einmal pro Projekt statt einmal pro Clip pro Plattform.

### Der AVV-Banner

Steht heute auf allen 29 Routen über der Hauptüberschrift und wird nie erledigt.
Er trainiert Nutzer darauf, orange zu ignorieren, und entwertet damit Klasse A.

**Neu:** Er erscheint an genau zwei Stellen, an denen er Konsequenzen hat:
auf der Startseite als einmalige Karte und in Schritt 5 als Punkt in der
"Noch nicht bereit"-Liste. Sonst nirgends.

---

## 8. Wortliste

Verbindlich für alle Oberflächentexte. Links ist der heutige Wortlaut aus der
laufenden App.

### Hauptbegriffe

| Heute | Neu |
|---|---|
| Projekt | Video |
| Quelle | Video |
| Kandidat | Moment |
| Kandidaten prüfen | Momente auswählen |
| Clip | Clip (bleibt, ist bekannt) |
| Markenprofil | Aussehen |
| Transkript | Text |
| Review | Auswählen |
| Hook | Text im Video |
| Hook-Studio | Text oder Bild ändern |
| Render / rendern | erstellen |
| Neu rendern | Änderungen übernehmen |
| Export | Herunterladen |
| Gast-Freigabe | Jemanden fragen |
| Workspace | Team |

### Bewertung und Status

| Heute | Neu |
|---|---|
| DACH-QUALITÄT 6,7 | Stark |
| 5 von 5 Pflichtkriterien | Alles geprüft |
| 2 Gates offen | Noch nicht bereit zum Posten (mit Liste) |
| Payoff zuerst | Pointe am Anfang |
| Behauptung prüfen | Enthält eine Behauptung. Stimmt sie? |
| Heuristik ohne Sprachmodell | Ohne KI gefunden |
| Bereit | Fertig |
| Gerendert | Fertig |

### Technische Angaben

| Heute | Neu |
|---|---|
| -16,4 LUFS, -1,5 dBTP | Lautstärke passt |
| Zu schnell (20 Z/s) | Untertitel laufen schnell durch |
| Reframe: neutraler Crop | Bildausschnitt: Mitte |
| C2PA übersprungen | (nicht anzeigen, Klasse C) |
| SHA-256 | (nicht anzeigen, Klasse C) |
| deterministischer Plan | (Formulierung streichen) |
| 9:16 | Hochformat |
| 4:5 | Quer |
| 56 Wörter in 1 Fenstern | (nicht anzeigen) |

### Tonfall

- Du-Form, wie bereits im Produkt üblich.
- Aktiv statt passiv: "Der Computer sucht gute Stellen", nicht "Stellen werden gesucht".
- Keine Gedankenstriche, keine Emojis, keine Hype-Wörter. Gilt weiterhin
  (`README.md`, Arbeitsregeln).
- Jeder Fehlertext nennt: was passiert ist, und was Lena jetzt tun kann. Zwei Sätze.
- Keine Anleitungen. Wenn ein Satz Anleitung nötig ist, ist die Bedienung falsch.

---

## 9. Details für Profis

Ein einheitlicher aufklappbarer Bereich, gleiche Stelle, gleiche Beschriftung, auf
jeder Seite des Hauptwegs. Zugeklappt als Voreinstellung. Merkt sich den Zustand
nicht, ist also bei jedem Besuch wieder zu.

**Inhalt je Seite:**

| Seite | Drin |
|---|---|
| Video (Projekt) | SHA-256, Auflösung, Dateigröße, Löschfrist, Rechtestatus, Modellnamen, Löschen |
| Text | Modellkürzel, Konfidenzwerte, Versionshistorie |
| Momente auswählen | Rubrik-Einzelwerte, Story-Graph, Belegzitate, Gates im Detail |
| Feinschliff | alle fünf Hook-Varianten nebeneinander, Linter-Ausgabe |
| Fertig | LUFS, dBTP, Render-Plan, C2PA-Status, SRT, VTT, Serie zuordnen, Klasse-C-Meldungen |

**Das ist kein Verlust.** Für die ursprüngliche Zielgruppe der Agentur-Redakteure ist
alles einen Klick entfernt und an einer vorhersehbaren Stelle, statt wie heute über
die Seite verteilt.

---

## 10. Was mit den B2B-Funktionen passiert

Die Neuausrichtung auf Laien betrifft die Oberfläche des Hauptwegs. Diese Bereiche
gehören nicht dahin und werden geordnet, nicht vereinfacht:

| Bereich | Wohin |
|---|---|
| Rollen, Mitglieder, Einladungen | Einstellungen > Team. Unverändert. |
| API-Schlüssel, Webhooks, Entwicklerdoku, MCP | Einstellungen > Für Entwickler. Unverändert. |
| Abrechnung, Tarife | Einstellungen > Abrechnung. Unverändert. |
| AVV, TOMs, Subprozessoren | Seitenfuß plus die zwei Stellen aus Abschnitt 7. |
| Audit-Log, Löschung, Export | Einstellungen. Unverändert. |
| Sovereign-Tarif | Unverändert. Ist eine Vertriebsfrage, keine Oberflächenfrage. |
| Serien, Experimente, Berichte | Neu unter "Auswertung" in der Hauptnavigation. |

**Bewusst offen:** Ob Lena als Privatperson überhaupt die richtige zahlende Zielgruppe
ist, oder ob die Laien-Oberfläche vor allem dazu dient, dass in einer Agentur auch
Praktikanten und Kunden das Werkzeug bedienen können. Das ist eine Positionierungsfrage
für Ferdi, keine Designfrage. Das Konzept funktioniert in beiden Fällen.

---

## 11. Der erste Lauf

Heute landet ein neuer Nutzer auf einer leeren Projektliste mit einem orangen
Vertragshinweis darüber. Das ist der erste Eindruck.

**Neu, genau drei Sätze plus ein Knopf:**

```
        chopstr macht aus langen Videos kurze Clips.

   Du lädst ein Video hoch, der Computer sucht die besten
   Stellen, du wählst aus. Dauert etwa fünf Minuten.

              [  Erstes Video hochladen  ]
```

Keine Tour, kein Assistent, kein Zwangsdialog. Eure Design-Grundsätze sprechen von
"Zurückhaltung als Premium", das gilt auch hier.

---

## 12. Reihenfolge der Umsetzung

Vier Etappen. Jede einzeln abnehmbar, jede bringt für sich schon etwas.

### Etappe 1: Sprache (umgesetzt am 23.09.2026)

Nur Texte. Kein Struktureingriff, kein Risiko.

- Wortliste aus Abschnitt 8 überall anwenden
- Statussätze der Projektliste
- Pipeline-Schrittnamen
- "2 Gates offen" durch Klartext-Liste ersetzen

Danach ist die App verständlich, aber noch unübersichtlich.

### Etappe 2: Warnungen und Details (umgesetzt)

- Die drei Warnklassen aus Abschnitt 7 eingeführt
- Klasse C in "Details für Profis" verschoben (C2PA, Prüfsumme, Modellnamen, Messwerte)
- Vertragshinweis von allen Seiten auf zwei Stellen reduziert
- Einheitlicher Profi-Bereich als `components/ui/ProDetails.tsx`, überall gleich beschriftet

Danach wirkt die App fertig, auch wenn die Wege noch nicht stimmen.

### Etappe 3: Navigation und Schrittleiste

- Hauptnavigation auf drei Einträge
- "Auswertung" als Sammelseite
- Schrittleiste auf allen Projektseiten
- Projektkarte auf einen Knopf reduzieren

Danach weiß der Nutzer jederzeit, wo er ist und was als Nächstes kommt.

### Etappe 4: Die Seiten selbst

Der größte Eingriff, deshalb zuletzt.

- Upload auf Ablegefeld plus eine Frage
- Momente auswählen: einer statt Liste, Hochformat als Voreinstellung
- Schritt 5: die Bühne statt vier Spalten
- Feinschliff zusammenführen

Danach ist das Konzept umgesetzt.

**Nach jeder Etappe:** Die App läuft lokal, du siehst es dir an, wir korrigieren.
Kein Push auf main ohne dein Kommando.

---

## 12b. Was seit der Fassung vom 23.09.2026 dazugekommen ist

Nicht Teil der vier Etappen, aber in derselben Nacht gebaut und am echten Video geprüft:

- **Hochformat-Schalter** beim Annehmen eines Moments, standardmäßig an. Aus behält der Clip das
  Format der Quelle, ohne Beschnitt und ohne Push-in. Ersetzt teilweise die offene Frage 1: nicht
  "nur 9:16", sondern "9:16, wenn du nichts anderes sagst".
- **One-Word-Untertitel** als Standard für TikTok, Reels und Shorts (Presets `*_words`).
  LinkedIn bleibt mehrwortig und ruhig. Der SRT/VTT-Beiwagen bleibt bewusst gruppiert.
- **Langsamer Push-in** je Einstellung (8 Prozent), nur wenn umgerahmt wird.
- **Zwei Entwicklerwerkzeuge** (`ingest_local.py`, `accept_local.py`), damit die Kette ohne
  Browser prüfbar ist.

## 13. Offene Fragen an Ferdi

1. **Hochformat als Voreinstellung.** Teilweise erledigt: Der Schalter steht, Standard ist Hochformat.
   Offen bleibt, ob ein angenommener Moment weiterhin alle vier Plattformen auf einmal rendert oder
   nur die Standard-Plattform, und der Rest auf Anfrage. Das betrifft Renderkosten und Abrechnung.

2. **Briefing verschieben.** Die fünf Felder des Redaktions-Briefings sollen vom
   Upload nach Schritt 3 wandern. Die Story-Engine nutzt das Briefing heute aber
   bereits bei `detect_candidates`, also vor Schritt 3. Entweder das Briefing bleibt
   beim Upload (dann eingeklappt als "Wünsche angeben"), oder die Kandidatensuche
   läuft bei Änderung erneut. Ich empfehle eingeklappt beim Upload.

3. **Positionierung.** Bleibt der bezahlende Kunde die Agentur, und Lena ist die
   Praktikantin darin? Oder zielt ihr auf Privatpersonen? Das ändert nichts am
   Konzept, aber einiges an Abrechnung und Preisseite.

4. **Wortliste.** Bitte einmal durchgehen. Besonders: "Video" statt "Projekt",
   "Moment" statt "Kandidat", "Aussehen" statt "Markenprofil". Diese drei prägen
   die halbe Oberfläche.
