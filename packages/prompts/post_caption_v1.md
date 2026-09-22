---
name: post_caption
version: 1
tool: write_post_caption
inputs: [address, country, platform, tone_adjectives, banned_phrases, clip_text, hook_onscreen]
---
Schreibe den Post-Text zu diesem Clip für {platform}.

Ton: {tone_adjectives}. Anrede: {address}. Land: {country}.
Gesperrte Phrasen: {banned_phrases}

Plattformregeln:
- TikTok/Reels: informell, direkt, 1 bis 3 kurze Zeilen, kein Hashtag-Teppich.
- YouTube Shorts: Titel bis 60 Zeichen plus ein Satz Beschreibung.
- LinkedIn: professionell, erste Zeile 1 bis 8 Wörter als Statement, dann 3 bis 6 kurze Absätze mit
  Beleg vor Behauptung, keine Emojis, Frage oder Einladung zum Gespräch am Ende. Keine Zahl ohne Beleg im Clip.

Der Post darf keine Aussage enthalten, die nicht im Clip vorkommt. Er wiederholt den On-Screen-Hook
nicht wörtlich: {hook_onscreen}

CLIP:
{clip_text}
