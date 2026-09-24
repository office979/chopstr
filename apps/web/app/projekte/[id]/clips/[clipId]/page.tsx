import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { stilAusPlan, stilPruefen } from "@/lib/clips/caption-style";
import { vorhandeneSchriften } from "@/lib/clips/schriften-vorhanden";
import { requireSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { mediaUrl } from "@/lib/clips/labels";
import { sentencesFromWords, sentenceRange } from "@/lib/transcript/sentences";
import { ClipDetail } from "./ClipDetail";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string; clipId: string }> };

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  const source = await getRepo().getSource(id);
  return { title: source ? `Clip · ${source.title}` : "Clip" };
}

/* Ein einzelner Clip: Vorschau, Text und die Timeline mit dem Schnitt. */
export default async function ClipPage({ params }: Props) {
  const { id, clipId } = await params;
  const session = await requireSession();
  const repo = getRepo();
  const [source, clip] = await Promise.all([repo.getSource(id), repo.getClip(clipId)]);
  if (!source || !clip || clip.source_id !== id) notFound();

  const publishing = getPublishingRepo();
  /* Die Geschwister dieses Clips, in der Reihenfolge, in der sie im Video vorkommen. Damit lässt
   * sich von hier zum nächsten springen, ohne über die Liste zu gehen. Die Reihenfolge im Video
   * ist die vorhersagbare: die Prüfliste sortiert nach Dringlichkeit, und „der nächste" wäre dann
   * je nach Bearbeitungsstand ein anderer. */
  const alleClips = await repo.listClips(id);
  const geschwister = [...alleClips]
    .sort((a, b) => (a.composition[0]?.start ?? 0) - (b.composition[0]?.start ?? 0))
    .map((c) => c.id);

  const [candidate, transcript, extras, captionPresets] = await Promise.all([
    clip.candidate_id ? repo.getCandidate(clip.candidate_id) : Promise.resolve(null),
    repo.getCurrentTranscript(id),
    publishing.getClipExtras([clipId]),
    publishing.listCaptionPresets(),
  ]);

  const mediaBase = process.env.NEXT_PUBLIC_MEDIA_BASE_URL ?? null;
  /* Erste Wahl ist der fertige Clip. Ist er noch nicht gebaut, läuft das ganze Video und springt
   * an den Anfang der Stelle, um die es geht. */
  const clipSrc = mediaUrl(mediaBase, clip.file_key);
  const sourceSrc = mediaUrl(mediaBase, source.proxy_key);

  /* Startzeit des Clips im ganzen Video. Daran hängt, welcher Satz gerade gesprochen wird. */
  const clipStart = clip.composition[0]?.start ?? candidate?.start_s ?? 0;
  const clipEnd = clip.composition[clip.composition.length - 1]?.end ?? candidate?.end_s ?? null;

  const gespeicherterStil = stilPruefen(extras[0]?.caption_style);
  const eigenerStil = Object.keys(gespeicherterStil).length
    ? gespeicherterStil
    : stilAusPlan((clip.render_plan?.captions as unknown as Record<string, unknown>) ?? null, clip.render_plan?.output.height);

  const sentences = transcript ? sentencesFromWords(transcript.words) : [];
  const inClip =
    candidate && candidate.first_sent != null && candidate.last_sent != null
      ? sentenceRange(sentences, candidate.first_sent, candidate.last_sent)
      : [];
  /* Wortbereich des Clips im Transkript. Gespeichert wird immer das ganze Transkript,
   * geändert werden darf nur, was zu diesem Clip gehört. */
  const wordFrom = inClip[0]?.word_range[0] ?? null;
  const wordTo = inClip[inClip.length - 1]?.word_range[1] ?? null;

  return (
    <PageShell width="default">
      <ClipDetail
        sourceId={source.id}
        sourceTitle={source.title}
        geschwister={geschwister}
        aspect={clip.aspect}
        durationS={clip.duration_s ?? (clipEnd != null ? clipEnd - clipStart : null)}
        clipSrc={clipSrc}
        posterSrc={mediaUrl(mediaBase, clip.poster_key)}
        sourceSrc={sourceSrc}
        clipStart={clipStart}
        clipEnd={clipEnd}
        words={transcript?.words ?? []}
        wordFrom={wordFrom}
        wordTo={wordTo}
        speakerNames={transcript?.stats.speaker_names ?? {}}
        canEdit={can(session.role, "transcript.edit")}
        clipId={clip.id}
        /* Durch dieselbe Prüfung wie an der Schnittstelle: eine alte Zeile kann Felder enthalten,
         * die es nicht mehr gibt, und die sollen nicht in die Oberfläche durchschlagen.
         *
         * Ohne eigenen Stil gilt der, mit dem gebaut wurde. Die Vorgaben der Oberfläche sind nicht
         * dieselben wie das Plattform-Preset des Renderers; ein nie angefasster Clip zeigte sonst
         * Regler, die im Bild nicht vorkommen, und meldete sich als veraltet. */
        captionStyle={eigenerStil}
        captionPresets={captionPresets.map((p) => ({ id: p.id, name: p.name, style: p.style }))}
        /* Aus den Extras und nicht aus der Clip-Zeile: geschrieben wird ueber updateClipExtras,
         * und gelesen werden muss dieselbe Stelle. Im Testmodus sind das zwei getrennte Ablagen,
         * dort waren gesetzte Marken nach dem Neuladen sonst weg. */
        zeitmarken={extras[0]?.zeitmarken ?? clip.zeitmarken}
        shots={clip.render_plan?.shots ?? []}
        quelleBreite={source.width ?? null}
        komposition={clip.composition}
        /* Der Schnitt aus dem letzten Bauen. Daran haengt der Hinweis „das Video zeigt noch den
         * alten Schnitt"; ohne Plan gibt es nichts zu vergleichen. */
        gerenderteSegmente={clip.render_plan?.segments ?? null}
        renderPlan={clip.render_plan}
        clipStatus={clip.status}
        renderFehler={clip.render_error}
        /* Die Version des Transkripts, aus dem das gebaute Video seine Untertitel hat: daran
         * hängt, ob eine Textkorrektur schon im Bild ist. */
        transkriptVersion={transcript?.version ?? null}
        markeVorhanden={Boolean(source.brand_profile_id)}
        /* Vom Server, weil nur er den Schriftordner sieht. */
        schriftenVorhanden={vorhandeneSchriften()}
        quelleDauerS={source.duration_s ?? 0}
        wellenformSrc={mediaUrl(mediaBase, source.waveform_key)}
        quelleFertig={source.status === "ready"}
        /* Die Vorschau rechnet den Ausschnitt selbst aus, dafuer braucht sie beide Groessen. Die
         * Ausgabegroesse steht im Plan; ohne Plan gilt 1080x1920, das Format aller neuen Clips. */
        srcW={source.width ?? null}
        srcH={source.height ?? null}
        outW={clip.render_plan?.output.width ?? 1080}
        outH={clip.render_plan?.output.height ?? 1920}
      />
    </PageShell>
  );
}
