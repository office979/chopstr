"use client";

import { useId, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { MAX_DB, MIN_DB, lautstaerkeWort, type Musik } from "@/lib/clips/musik";

/* Musik unter den Clip legen: auswählen, lauter, leiser, weg.
 *
 * Wie bei den Effekten steht hier NUR, was in der Zeitleiste nicht geht. Die Stelle im Stück wird
 * dort gewählt, durch Verschieben der Musikspur - das ist das eine, wofür eine Zeitachse da ist.
 * Hier bleiben: welches Stück, wie laut, und ob die Musik unter der Sprache weichen soll.
 *
 * DIE BIBLIOTHEK IST NOCH LEER. Epidemic Sound braucht einen Partnervertrag, bis dahin antwortet
 * ihre Schnittstelle auf alles mit „Unauthorized". Das steht auch so da - ein Auswahlfeld, das
 * sich öffnen lässt und nichts enthält, ist schlimmer als der Satz, warum.
 */
export function MusikListe({
  musik,
  canEdit,
  laeuft,
  fehler,
  onAendern,
  onHochladen,
}: {
  musik: Musik | null;
  canEdit: boolean;
  /* Ein Hochladen ist unterwegs. */
  laeuft: boolean;
  fehler: string | null;
  onAendern: (naechste: Musik | null) => void;
  onHochladen: (datei: File) => void;
}) {
  const id = useId();
  const dateiId = useId();
  const feld = useRef<HTMLInputElement | null>(null);
  const [zieht, setZieht] = useState(false);

  return (
    <GlassCard padding="md" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-base font-semibold">Musik</h3>
          <p className="mt-0.5 text-sm text-text-2">
            {musik
              ? "Die Stelle im Stück wählst du in der Zeitleiste, indem du die Musikspur verschiebst."
              : "Ein eigenes Stück unter den Clip legen. Es läuft vom Anfang bis zum Ende des Clips."}
          </p>
        </div>

        {canEdit && musik && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onAendern(null)}
            className="shrink-0 border-danger/60 text-danger hover:bg-danger/15"
          >
            Entfernen
          </Button>
        )}
      </div>

      {musik ? (
        <>
          <p className="truncate text-sm text-text" title={musik.name}>
            {musik.name}
          </p>

          <label htmlFor={id} className="flex flex-col gap-1.5">
            <span className="flex flex-wrap items-baseline justify-between gap-2 text-sm text-text-2">
              Lautstärke
              {/* Dezibel UND ein Wort: „-18 dB" sagt einem Laien nichts, „leise" schon. Und die
                  Zahl bleibt, weil sie für den, der sie kennt, genauer ist. */}
              <span className="text-text">
                {lautstaerkeWort(musik.lautstaerke_db)}{" "}
                <span className="font-mono tabular-nums text-text-3">{musik.lautstaerke_db.toFixed(1)} dB</span>
              </span>
            </span>
            <input
              id={id}
              type="range"
              min={MIN_DB}
              max={MAX_DB}
              step={0.5}
              value={musik.lautstaerke_db}
              disabled={!canEdit}
              onChange={(e) => onAendern({ ...musik, lautstaerke_db: Number(e.target.value) })}
              className="w-full accent-brand"
            />
          </label>

          <label className="flex items-start gap-2 text-sm text-text-2">
            <input
              type="checkbox"
              checked={musik.ducking}
              disabled={!canEdit}
              onChange={(e) => onAendern({ ...musik, ducking: e.target.checked })}
              className="mt-0.5 h-4 w-4 accent-brand"
            />
            <span>
              Unter der Stimme leiser werden
              <span className="block text-xs text-text-3">
                Die Musik weicht, wenn gesprochen wird, und kommt in den Pausen zurück. Ohne das ist
                sie in den Pausen zu leise und unter den Worten zu laut.
              </span>
            </span>
          </label>
        </>
      ) : (
        <p className="text-sm text-text-3">
          Eine Bibliothek zum Auswählen gibt es noch nicht: dafür braucht chopstr einen
          Partnervertrag mit Epidemic Sound. Eigene Musik geht schon.
        </p>
      )}

      {canEdit && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setZieht(true);
          }}
          onDragLeave={() => setZieht(false)}
          onDrop={(e) => {
            e.preventDefault();
            setZieht(false);
            const d = e.dataTransfer.files?.[0];
            if (d) onHochladen(d);
          }}
          className={`transition-soft flex flex-wrap items-center justify-between gap-2 rounded-inner border border-dashed px-3 py-2.5 ${
            zieht ? "border-brand bg-brand/10" : "border-line"
          }`}
        >
          <span className="text-sm text-text-2">
            {laeuft ? "Wird hochgeladen" : musik ? "Anderes Stück hierher ziehen" : "Musik hierher ziehen"}
            <span className="block text-xs text-text-3">MP3, WAV, M4A, OGG oder FLAC, bis 40 MB.</span>
          </span>
          <label htmlFor={dateiId} className="shrink-0">
            <input
              ref={feld}
              id={dateiId}
              type="file"
              accept="audio/mpeg,audio/mp3,audio/wav,audio/x-wav,audio/mp4,audio/aac,audio/x-m4a,audio/ogg,audio/flac,audio/x-flac"
              className="sr-only"
              onChange={(e) => {
                const d = e.target.files?.[0];
                /* Zurücksetzen, sonst löst dieselbe Datei beim zweiten Mal nichts aus. */
                e.target.value = "";
                if (d) onHochladen(d);
              }}
            />
            <Button size="sm" variant="ghost" disabled={laeuft} onClick={() => feld.current?.click()}>
              Datei wählen
            </Button>
          </label>
        </div>
      )}

      {fehler && <p className="text-sm text-attention">{fehler}</p>}

      {canEdit && (
        <p className="text-xs text-text-3">
          Für eigene Musik brauchst du die Rechte daran. chopstr prüft das nicht — wie jedes
          Schnittprogramm.
        </p>
      )}
    </GlassCard>
  );
}
