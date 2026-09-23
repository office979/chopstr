/* Produktbild für die Landingpage, aus HTML statt Screenshot: lädt ohne Bilddatei, bleibt scharf und passt sich an.
 * Links ein gefundener Moment mit Begründung, rechts die Handy-Vorschau mit Untertitel. Rein dekorativ. */
export function ProductMockup() {
  return (
    <div aria-hidden="true" className="relative mx-auto w-full max-w-[1040px] select-none text-left">
      <div className="absolute -inset-x-10 -top-10 bottom-0 rounded-[48px] bg-brand/20 blur-3xl" />
      <div className="relative overflow-hidden rounded-[28px] border border-white/10 bg-[#07070f]/90">
        {/* Fensterleiste */}
        <div className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
          <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
          <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
          <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
          <span className="mx-auto hidden rounded-md bg-white/[0.06] px-10 py-1 font-mono text-[11px] text-text-3 sm:block">app.chopstr.eu</span>
        </div>

        <div className="grid gap-4 p-4 sm:p-6 md:grid-cols-[1fr_220px] md:gap-6">
          <div className="flex min-w-0 flex-col gap-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-text">Podcast Folge 12 · 6 gute Clips gefunden</p>
              <span className="hidden rounded-md bg-white/[0.06] px-2 py-1 text-[11px] text-text-2 sm:block">1:02:00</span>
            </div>

            {/* Ausgewählter Moment */}
            <div className="rounded-[18px] border border-ai-soft/40 bg-ai/10 p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-text">Was eine offene Stelle wirklich kostet</p>
                <span className="shrink-0 font-mono text-xs text-ai-soft">00:41 lang</span>
              </div>
              <p className="mt-2 line-clamp-2 text-[13px] leading-relaxed text-text-2">
                „Eine unbesetzte Stelle kostet im Mittelstand schnell 30.000 Euro. Nicht, weil jemand fehlt, sondern weil alle anderen die Arbeit mitmachen.“
              </p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <Tag>Beginnt mit einer klaren Aussage</Tag>
                <Tag>Satz ist vollständig</Tag>
                <Tag>Zahl als Beleg</Tag>
              </div>
              <div className="mt-4 flex gap-2">
                <span className="rounded-full bg-text px-3.5 py-1.5 text-xs font-medium text-black">Nehmen</span>
                <span className="rounded-full border border-white/15 px-3.5 py-1.5 text-xs text-text-2">Länger</span>
                <span className="rounded-full border border-white/15 px-3.5 py-1.5 text-xs text-text-2">Kürzer</span>
              </div>
            </div>

            {/* Weitere Clips */}
            {["Warum Stellenanzeigen niemand liest", "Der teuerste Fehler im Bewerbungsgespräch"].map((t, i) => (
              <div key={t} className="flex items-center justify-between gap-3 rounded-[14px] border border-white/10 bg-white/[0.03] px-4 py-3">
                <p className="truncate text-[13px] text-text-2">{t}</p>
                <span className="shrink-0 font-mono text-[11px] text-text-3">{i === 0 ? "00:28" : "00:52"}</span>
              </div>
            ))}

            {/* Zeitleiste */}
            <div className="mt-1 flex h-8 items-end gap-[3px]">
              {BARS.map((h, i) => (
                <span
                  key={i}
                  className={i >= 22 && i <= 30 ? "flex-1 rounded-sm bg-ai-soft/80" : "flex-1 rounded-sm bg-white/10"}
                  style={{ height: `${h}%` }}
                />
              ))}
            </div>
          </div>

          {/* Handy-Vorschau */}
          <div className="mx-auto hidden w-[200px] md:block">
            <div className="relative aspect-[9/16] overflow-hidden rounded-[26px] border border-white/15 bg-[linear-gradient(180deg,#141432_0%,#0a0a18_55%,#05050c_100%)]">
              <div className="absolute inset-x-6 top-[22%] h-[38%] rounded-full bg-white/[0.06] blur-md" />
              <div className="absolute left-1/2 top-[20%] h-16 w-16 -translate-x-1/2 rounded-full bg-white/10" />
              <div className="absolute left-1/2 top-[34%] h-24 w-28 -translate-x-1/2 rounded-t-[40px] bg-white/[0.07]" />
              <p className="absolute inset-x-3 top-4 rounded-md bg-black/60 px-2 py-1.5 text-center text-[11px] font-semibold leading-tight text-white">
                30.000 Euro für einen leeren Stuhl?
              </p>
              <p className="absolute inset-x-4 bottom-[18%] text-center text-[15px] font-bold leading-tight text-white">
                kostet schnell <span className="rounded bg-[#ffd700] px-1 text-black">30.000</span> Euro
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Tag({ children }: { children: React.ReactNode }) {
  return <span className="rounded-md bg-white/[0.07] px-2 py-1 text-[11px] text-text-2">{children}</span>;
}

const BARS = [18, 30, 22, 40, 26, 34, 20, 44, 30, 24, 38, 28, 52, 36, 30, 46, 34, 26, 40, 58, 44, 50, 72, 88, 76, 94, 82, 90, 70, 80, 64, 38, 30, 42, 26, 34, 48, 30, 22, 36, 28, 40, 24, 32];
