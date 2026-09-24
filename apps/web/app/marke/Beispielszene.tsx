"use client";

import { useMemo } from "react";
import { SilentPreview, type PreviewFont } from "@/components/clips/SilentPreview";
import type { Aspect, CaptionCard, CaptionPreset, Platform } from "@/lib/repo/types";

/* Ein Beispielsatz, an dem sich alles beurteilen lässt: ein Eigenname, eine Zahl, ein langes
 * Kompositum. Kurze Beispielwörter sehen immer gut aus und sagen deshalb nichts. */
const SATZ = [
  { text: "Eine unbesetzte Stelle", keyword: "unbesetzte" },
  { text: "kostet vierzehntausend Euro", keyword: "vierzehntausend" },
  { text: "im Monat.", keyword: "Monat." },
];

const ASPEKT_JE_PLATTFORM: Record<Platform, Aspect> = {
  tiktok: "9:16",
  reels: "9:16",
  shorts: "9:16",
  linkedin: "4:5",
};

interface Props {
  plattform: Platform;
  preset: CaptionPreset | string;
  hookText: string | null;
  bauchbinde: { name: string; role: string } | null;
  highlightColor?: string;
  font: PreviewFont | null;
  /* Das Logo als Wasserzeichen, wie es der Renderer oben rechts setzt. */
  logoUrl: string | null;
  logoAn: boolean;
}

/* Wie ein Clip mit diesem Profil aussieht.
 *
 * Bisher stand hier eine Liste von Feldern: drei Farbwähler, ein Schriftname, ein Schalter für
 * die Bauchbinde. Ob das zusammen funktioniert, sah man erst am fertigen Clip. Die Szene zeigt
 * alles an einem Bild: Untertitel im gewählten Stil, Einstieg, Bauchbinde, Schrift und Logo.
 *
 * Es ist kein Render, sondern eine Nachstellung mit denselben Maßen wie im Ausgabeformat
 * (lib/clips/presets, Spiegel des Workers). Das steht auch darunter. */
export function Beispielszene({ plattform, preset, hookText, bauchbinde, highlightColor, font, logoUrl, logoAn }: Props) {
  const karten = useMemo<CaptionCard[]>(
    () =>
      SATZ.map((s, i) => ({
        start: 1 + i * 1.6,
        end: 1 + i * 1.6 + 1.5,
        lines: [s.text],
        keyword: s.keyword,
      })),
    [],
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="relative mx-auto w-full max-w-[300px]">
        <SilentPreview
          aspect={ASPEKT_JE_PLATTFORM[plattform]}
          preset={preset}
          durationS={6}
          cards={karten}
          hookText={hookText}
          titleCard={null}
          highlightColor={highlightColor}
          lowerThird={bauchbinde}
          font={font}
        />
        {/* Das Wasserzeichen sitzt beim Renderen oben rechts in der sicheren Fläche. Hier
          * dieselbe Ecke, damit sichtbar wird, ob es dem Text in die Quere kommt. */}
        {logoAn && logoUrl && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={logoUrl}
            alt=""
            className="pointer-events-none absolute right-[8%] top-[7%] h-auto w-[18%] object-contain opacity-90"
          />
        )}
      </div>
      <p className="text-center text-xs text-text-3">
        Nachgestellt mit denselben Maßen wie im fertigen Clip. Kein echter Export.
      </p>
    </div>
  );
}
