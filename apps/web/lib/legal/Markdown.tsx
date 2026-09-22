import type { ReactNode } from "react";

/* Kleiner Markdown-Renderer für die Rechtstexte (Überschriften, Absätze, Zitate, Listen, Tabellen, Fett).
 * Kein HTML-Passthrough: alles wird als Text gerendert. */

function inline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\*\*(.+?)\*\*|`([^`]+)`/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] != null) out.push(<strong key={`${keyPrefix}-b${i}`}>{m[1]}</strong>);
    else out.push(<code key={`${keyPrefix}-c${i}`} className="font-mono text-[0.9em]">{m[2]}</code>);
    last = m.index + m[0].length;
    i += 1;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function tableRows(lines: string[]): string[][] {
  return lines
    .filter((l) => !/^\|\s*-{2,}/.test(l))
    .map((l) =>
      l
        .replace(/^\||\|$/g, "")
        .split("|")
        .map((c) => c.trim()),
    );
}

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;
  const next = () => `md-${key++}`;

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      const k = next();
      const text = inline(heading[2], k);
      if (level === 1) blocks.push(<h1 key={k} className="mb-6 text-3xl font-semibold tracking-[var(--tracking-display)] sm:text-4xl">{text}</h1>);
      else if (level === 2) blocks.push(<h2 key={k} className="mb-3 mt-8 text-xl font-medium">{text}</h2>);
      else blocks.push(<h3 key={k} className="mb-2 mt-6 text-lg font-medium">{text}</h3>);
      i += 1;
      continue;
    }
    if (line.startsWith("|")) {
      const rows: string[] = [];
      while (i < lines.length && lines[i].startsWith("|")) rows.push(lines[i++]);
      const [head, ...body] = tableRows(rows);
      const k = next();
      blocks.push(
        <div key={k} className="my-4 overflow-x-auto rounded-inner border border-line">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-text-2">
              <tr>
                {head.map((c, ci) => (
                  <th key={ci} className="px-4 py-3 font-medium">
                    {inline(c, `${k}-h${ci}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {body.map((r, ri) => (
                <tr key={ri} className="align-top">
                  {r.map((c, ci) => (
                    <td key={ci} className="px-4 py-3 text-text">
                      {inline(c, `${k}-${ri}-${ci}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (line.startsWith(">")) {
      const quote: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) quote.push(lines[i++].replace(/^>\s?/, ""));
      const k = next();
      blocks.push(
        <blockquote key={k} className="my-4 rounded-inner border border-attention/50 bg-attention/10 px-4 py-3 text-sm text-text">
          {inline(quote.join(" "), k)}
        </blockquote>,
      );
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && (/^[-*]\s+/.test(lines[i]) || /^\s{2,}\S/.test(lines[i]))) {
        if (/^[-*]\s+/.test(lines[i])) items.push(lines[i].replace(/^[-*]\s+/, ""));
        else items[items.length - 1] += ` ${lines[i].trim()}`;
        i += 1;
      }
      const k = next();
      blocks.push(
        <ul key={k} className="my-3 flex list-disc flex-col gap-1.5 pl-5 text-[15px] text-text">
          {items.map((it, ii) => (
            <li key={ii}>{inline(it, `${k}-${ii}`)}</li>
          ))}
        </ul>,
      );
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\||>|[-*]\s)/.test(lines[i])) para.push(lines[i++].trim());
    const k = next();
    blocks.push(
      <p key={k} className="my-3 text-[15px] leading-relaxed text-text">
        {inline(para.join(" "), k)}
      </p>,
    );
  }
  return <div className="legal-doc">{blocks}</div>;
}
