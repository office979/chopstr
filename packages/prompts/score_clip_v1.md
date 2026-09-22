---
name: score_clip
version: 1
tool: score_clip
inputs: [audience, platform, candidate_numbered]
weights: {hook: 0.30, payoff: 0.25, specificity: 0.20, tension: 0.15, audience_fit: 0.10}
---
Zielgruppe: {audience}
Plattform: {platform}

CLIP-KANDIDAT (Satznummern in eckigen Klammern):
{candidate_numbered}

Bewerte streng nach der DACH-Rubrik.

PFLICHTKRITERIEN (Gates):
- unresolved_references: wörtliche Stellen mit Bezug auf Nicht-Gezeigtes (Pronomen ohne Bezug, „wie gesagt“,
  „das von vorhin“, „diese Grafik“). Leer, wenn keine.
- needs_earlier_context: true, wenn der Einstieg ohne vorherige Sätze nicht verständlich ist.
- ends_before_answer: true, wenn der Clip vor der Antwort, vor der Auflösung oder vor einem „aber“ endet.

SCORES 0 bis 10, jeder mit einem wörtlichen Belegzitat aus dem Kandidaten:
- hook (Einstieg stoppt einen kalten Zuschauer in 3 Sekunden)
- payoff (Auflösung, Erkenntnis, Zahl oder Entscheidung ist im Clip enthalten)
- specificity (Zahlen, Verfahren, Namen statt Allgemeinplätze)
- tension (Widerspruch, offene Frage, Wendepunkt)
- audience_fit (passt zur Zielgruppe und Plattform)

FLAGS:
- is_humor: true bei Pointen und Witz (immer menschliche Prüfung).
- sensitive_topic: Gesundheit, Recht oder Finanzen mit Rat- oder Renditecharakter.
- suggested_title_card: max. 8 Wörter Kontext, nur wenn der Einstieg sonst unverständlich bleibt, sonst leer.
- why: ein Satz Klartext für die Redaktion, z. B. „Kernaussage in 38 Sekunden vollständig, Einstieg mit
  klarer Gegenposition, passt für LinkedIn.“
