# 050: Sichtbare Timeline entfernen

Stand 20.10.2026, Lane W (Phase 5). Bezug: `docs/MASTER-PROMPT-LAUNCH.md` Abschnitt 1 (Produktentscheidung),
`docs/REVIEW-MASTER-PROMPT-LAUNCH.md` Abschnitt 9 (Erstens), `docs/decisions/000-auftrag.md`.

**Problem.** Die Detailseite eines Clips hatte einen Reiter „Schnitt“ mit einer vollständigen Timeline:
Griffe an Anfang und Ende, Teilen, Teile entfernen, Rückgängig, Zoom, Wellenform, Filmstreifen, eine
Effektspur (Zoom hinein, Zoom heraus) und eine Musikspur mit eigenem Upload. Das widerspricht der
verbindlichen Produktentscheidung: chopstr ist eine Freigabe, kein Editor; was früher ein Mensch am Band
repariert hätte, muss die Pipeline liefern. Die Review verlangt zugleich, dass „Timeline raus“ nicht
stillschweigend andere Korrekturen mitnimmt.

**Alternativen.** (a) Timeline hinter einen Profi-Schalter legen. (b) Nur die Grenzgriffe entfernen,
Effekte und Musik behalten. (c) Den ganzen Reiter „Schnitt“ entfernen und die Korrekturen ohne Timeline
ausdrücklich behalten.

**Evidenz.** Inventur der Web-App: `ClipDetail.tsx` (Reiter Schnitt), `timeline/Timeline.tsx` (993 Zeilen),
`Wellenform.tsx`, `Lineal.tsx`, `useFilmstreifen.ts`, `EffektListe.tsx`, `MusikListe.tsx`, die Routen
`clips/[clipId]/schnitt`, `effekte`, `musik`, `musik/datei` und die Bibliotheken `lib/clips/schnitt.ts`,
`effekte.ts`, `musik.ts` dienten nur dieser Timeline. Der Worker liest `clips.composition`,
`clips.effekte` (`workers/chopstr_worker/activities/render.py:90`, `_load_effekte` ab Zeile 363, setzt beim
ersten Render automatische Effekte) und `clips.musik` (`render.py:91`, `_load_musik` ab Zeile 391); die
Spalten stammen aus den Migrationen 0015 und 0017 (`packages/schema/CLIPS.md`).

**Unsicherheit.** Ob Redakteure die Grenzgriffe vermissen, ist ungemessen; Gate 5 (Upload bis Freigabe
unter 10 Minuten) wird es zeigen. Ein Clip, dessen Grenze die Pipeline falsch setzt, lässt sich jetzt nur
ablehnen oder an die Redaktion geben, nicht mehr retten.

**Entscheidung.** (c). Entfernt sind der Reiter „Schnitt“, Timeline, Wellenform, Lineal, Filmstreifen,
Effekt- und Musiklisten, die Schnitt-, Effekt- und Musiklogik der Live-Vorschau, die vier Routen, die drei
Bibliotheken und ihre Tests (`timeline`, `lineal`, `schnitt`, `effekte`, `musik`). `timecode` lebt in
`apps/web/lib/clips/timecode.ts` weiter (Test `tests/timecode.test.ts`). Es bleiben, weil sie keine Grenze
verschieben: Reiter „Text“ (Wörter korrigieren, aus dem Untertitel nehmen, Sprecher ändern), Reiter
„Untertitel“ (CaptionStudio), Reiter „Bildausschnitt“ (Zeitmarken, Reframe), die Vorschau mit einem
Positionsregler, der nur den Abspielkopf bewegt, das zuletzt geclippte Video, HookStudio unter
`/experimente` und weitere Fassungen in anderen Formaten.

**Konsequenzen.** Die Datenbankfelder bleiben, nur die Oberfläche geht: `clips.composition`,
`clips.effekte` und `clips.musik` liest der Worker beim Render. Schon gesetzte Effekte und Musik wirken
weiter; neue Effekte setzt nur noch die Automatik des Renderers, eigene Musik lässt sich nicht mehr
hochladen. Die Live-Vorschau zeigt Zoom-Effekte, Musik und übersprungene Stellen nicht mehr; was der
Renderer daraus macht, zeigt „Zuletzt geclippt“. Die Verlängern/Kürzen-Route
`candidates/[cid]/revise` (Satzgrenzen, API) bleibt bestehen; aus der Oberfläche ist sie nicht erreichbar.

*Produkt.* Das Versprechen „Upload, Briefing, Kandidaten, annehmen oder ablehnen“ stimmt jetzt mit der
Oberfläche überein; die Produktseite sagt nicht mehr, man ziehe Anfang und Ende zurecht.

*Redaktion.* Wer einen Clip für falsch geschnitten hält, entscheidet: ablehnen mit Grund oder an die
Redaktion geben. Das macht Schnittfehler als Lernsignal sichtbar, statt sie am Band zu verstecken.

*Engineering.* Rund 3.000 Zeilen in gelöschten Dateien (mit Tests) und weitere rund 700 in Detailseite und Vorschau weniger, kein zweiter Schnittweg neben der Pipeline.
Der Worker bleibt unverändert; eine spätere Bereinigung von `effekte` und `musik` ist eine eigene
Entscheidung mit Migration.
