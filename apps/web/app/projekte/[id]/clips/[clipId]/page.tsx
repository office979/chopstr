import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { stilPruefen } from "@/lib/clips/caption-style";
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

/* Ein einzelner Clip: Vorschau und Text. Der Schnitt (verlängern, kürzen, Grenzen verschieben)
 * steht hier bewusst nicht, er ist zurückgestellt. */
export default async function ClipPage({ params }: Props) {
  const { id, clipId } = await params;
  const session = await requireSession();
  const repo = getRepo();
  const [source, clip] = await Promise.all([repo.getSource(id), repo.getClip(clipId)]);
  if (!source || !clip || clip.source_id !== id) notFound();

  const publishing = getPublishingRepo();
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
         * die es nicht mehr gibt, und die sollen nicht in die Oberfläche durchschlagen. */
        captionStyle={stilPruefen(extras[0]?.caption_style)}
        captionPresets={captionPresets.map((p) => ({ id: p.id, name: p.name, style: p.style }))}
      />
    </PageShell>
  );
}
