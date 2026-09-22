---
name: hooks
version: 1
tool: write_hooks
inputs: [address, country, platform, protected_terms, clip_text]
---
Schreibe 5 Hook-Varianten für diesen Clip: je eine Variante der Muster identity_call, contrarian,
open_loop, results_first, mistake_warning. Zu jeder Variante: spoken (max. 12 Wörter, gesprochen) und
onscreen (max. 9 Wörter, Text im Bild).

Regeln:
- Anrede: {address}. Land: {country}. Plattform: {platform}. Anrede nie mischen.
- Jede Behauptung muss durch den Clip gedeckt sein. Keine Zahl, die nicht im Clip vorkommt.
- Kein Superlativ, kein Gesundheits-, Rendite- oder Heilsversprechen, das der Clip nicht wörtlich enthält.
- Keine Floskeln, keine Gedankenstriche, kein Hype, keine Emojis. Konkret statt allgemein.
- Hauptsatz vor Nebensatz, Kernwort vorn: „40.000 € habe ich verloren, weil …“ statt „Weil ich …“.
- Regionale Begriffe des Sprechers nicht ins Standarddeutsch umschreiben: {protected_terms}
- Abgenutzte Muster vermeiden: „Du glaubst nicht …“, „Wenn ich das früher gewusst hätte …“,
  „Niemand spricht darüber …“, „Das hat mein Leben verändert“, „Warte bis zum Ende“.
- LinkedIn: erste Zeile 1 bis 8 Wörter als klares Statement, Belege vor Behauptung.

CLIP:
{clip_text}
