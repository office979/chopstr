---
name: score_clip
version: 2
tool: score_clip
inputs: [audience, platform, candidate_numbered, policy]
policy: clip_policy_v1
weights: {standalone: 0.20, hook: 0.20, offene_frage: 0.15, spezifitaet: 0.15, emotion: 0.15, aufloesung: 0.10, zielgruppe: 0.05}
---
Zielgruppe: {audience}
Plattform: {platform}

REDAKTIONELLE GRUNDLAGE (das ist der Massstab, nichts anderes):
{policy}

CLIP-KANDIDAT (Satznummern in eckigen Klammern):
{candidate_numbered}

Bewerte den Kandidaten ausschliesslich nach der Grundlage oben. Was dort nicht steht, zählt nicht.

PFLICHTKRITERIEN (Gates):
- unresolved_references: wörtliche Stellen mit Bezug auf Nicht-Gezeigtes (Pronomen ohne Bezug, „wie gesagt“,
  „das von vorhin“, „diese Grafik“). Leer, wenn keine.
- needs_earlier_context: true, wenn der Einstieg ohne vorherige Sätze nicht verständlich ist.
- ends_before_answer: true, wenn der Clip vor der Antwort, vor der Auflösung oder vor einem „aber“ endet.

RUBRIK: Bewerte jedes der sieben Kriterien der Grundlage einzeln, ganzzahlig auf ihrer Skala
(0 bis 2, nicht 0 bis 10). Halte dich an die Anker: 0 ist die untere Beschreibung, der Höchstwert
die obere. Der Mittelwert gilt für alles dazwischen, er ist nicht der Ausweg bei Unsicherheit.
Die sieben Schlüssel heissen genau so wie in der Rubrik oben und stehen so im Antwortschema.
Kein Kriterium auslassen.

Zu jedem Kriterium gehört ein Feld `<schluessel>_evidence`: ein wörtliches Zitat aus dem
Kandidaten, das genau diese Punktzahl trägt. Nicht umschreiben, nicht kürzen, nicht erfinden;
das Zitat wird gegen den Kandidatentext geprüft. Gibt es keine Stelle, die den Wert trägt, ist
der Wert zu hoch.

FLAGS:
- is_humor: true bei Pointen und Witz (immer menschliche Prüfung).
- sensitive_topic: Gesundheit, Recht oder Finanzen mit Rat- oder Renditecharakter.
- suggested_title_card: max. 8 Wörter Kontext, nur wenn der Einstieg sonst unverständlich bleibt, sonst leer.
- why: ein Satz Klartext für die Redaktion, der das schwächste und das stärkste Kriterium nennt,
  z. B. „Steht für sich und endet auf der Pointe, aber ohne Zahl oder Namen.“
