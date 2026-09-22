import "server-only";
import { Writable } from "node:stream";

/* Streamender multipart/form-data-Parser für den direkten Upload (lokaler Testmodus). Request.formData() würde die
 * ganze Datei im Speicher halten; hier laufen die Bytes eines Datei-Teils direkt in einen Writable (Dateisystem plus
 * SHA-256), Textfelder werden gesammelt (max. 64 KB je Feld). Der Parser ist selbst ein Writable und passt damit in
 * stream/promises pipeline(Readable.fromWeb(request.body), parser). */

export interface MultipartFile {
  field: string;
  filename: string;
  contentType: string;
}

export interface MultipartHandlers {
  onField(name: string, value: string): void;
  /* Liefert die Senke für die Datei-Bytes; sie wird nach dem Teil beendet (end) */
  onFile(file: MultipartFile): Writable;
  maxFieldBytes?: number;
}

export function multipartBoundary(contentType: string | null): string | null {
  if (!contentType) return null;
  const m = /multipart\/form-data\s*;.*boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentType);
  const b = (m?.[1] ?? m?.[2] ?? "").trim();
  return b || null;
}

function parseHeaders(raw: string): { name: string; filename: string | null; contentType: string } {
  let name = "";
  let filename: string | null = null;
  let contentType = "application/octet-stream";
  for (const line of raw.split("\r\n")) {
    const idx = line.indexOf(":");
    if (idx < 0) continue;
    const key = line.slice(0, idx).trim().toLowerCase();
    const value = line.slice(idx + 1).trim();
    if (key === "content-disposition") {
      const n = /(?:^|;)\s*name="([^"]*)"/i.exec(value);
      const f = /(?:^|;)\s*filename="([^"]*)"/i.exec(value);
      if (n) name = n[1];
      if (f) filename = f[1];
    } else if (key === "content-type") {
      contentType = value;
    }
  }
  return { name, filename, contentType };
}

type State = "preamble" | "headers" | "body" | "done";

export class MultipartParser extends Writable {
  private buffer: Buffer = Buffer.alloc(0);
  private state: State = "preamble";
  private readonly firstDelimiter: Buffer;
  private readonly delimiter: Buffer;
  private fieldName = "";
  private fieldValue: Buffer[] = [];
  private fieldBytes = 0;
  private sink: Writable | null = null;
  private readonly maxFieldBytes: number;

  constructor(boundary: string, private readonly handlers: MultipartHandlers) {
    super();
    this.firstDelimiter = Buffer.from(`--${boundary}`);
    this.delimiter = Buffer.from(`\r\n--${boundary}`);
    this.maxFieldBytes = handlers.maxFieldBytes ?? 64 * 1024;
  }

  _write(chunk: Buffer, _encoding: BufferEncoding, callback: (error?: Error | null) => void): void {
    this.buffer = this.buffer.length ? Buffer.concat([this.buffer, chunk]) : chunk;
    this.consume()
      .then(() => callback())
      .catch((error: unknown) => callback(error instanceof Error ? error : new Error(String(error))));
  }

  _final(callback: (error?: Error | null) => void): void {
    if (this.state !== "done") {
      callback(new Error("Multipart-Body unvollständig"));
      return;
    }
    callback();
  }

  private async consume(): Promise<void> {
    for (;;) {
      if (this.state === "done") {
        this.buffer = Buffer.alloc(0);
        return;
      }
      if (this.state === "preamble") {
        const idx = this.buffer.indexOf(this.firstDelimiter);
        if (idx < 0) {
          /* Präambel verwerfen, nur den möglichen Anfang des Delimiters behalten */
          const keep = Math.min(this.buffer.length, this.firstDelimiter.length - 1);
          this.buffer = this.buffer.subarray(this.buffer.length - keep);
          return;
        }
        const after = idx + this.firstDelimiter.length;
        if (this.buffer.length < after + 2) return;
        if (this.buffer[after] === 0x2d && this.buffer[after + 1] === 0x2d) {
          this.state = "done";
          continue;
        }
        this.buffer = this.buffer.subarray(after + 2);
        this.state = "headers";
        continue;
      }
      if (this.state === "headers") {
        const idx = this.buffer.indexOf("\r\n\r\n");
        if (idx < 0) {
          if (this.buffer.length > 16 * 1024) throw new Error("Multipart-Header zu lang");
          return;
        }
        const headers = parseHeaders(this.buffer.subarray(0, idx).toString("utf8"));
        this.buffer = this.buffer.subarray(idx + 4);
        this.fieldName = headers.name;
        this.fieldValue = [];
        this.fieldBytes = 0;
        this.sink = headers.filename != null ? this.handlers.onFile({ field: headers.name, filename: headers.filename, contentType: headers.contentType }) : null;
        /* Fehler kommen über die write/end-Callbacks zurück; ohne Listener würde 'error' den Prozess beenden */
        this.sink?.on("error", () => undefined);
        this.state = "body";
        continue;
      }
      /* body */
      const idx = this.buffer.indexOf(this.delimiter);
      if (idx < 0) {
        const keep = this.delimiter.length - 1;
        if (this.buffer.length <= keep) return;
        const data = this.buffer.subarray(0, this.buffer.length - keep);
        this.buffer = this.buffer.subarray(this.buffer.length - keep);
        await this.emitBody(data);
        return;
      }
      const data = this.buffer.subarray(0, idx);
      const after = idx + this.delimiter.length;
      if (this.buffer.length < after + 2) return;
      await this.emitBody(data);
      await this.endPart();
      if (this.buffer[after] === 0x2d && this.buffer[after + 1] === 0x2d) {
        this.state = "done";
        continue;
      }
      this.buffer = this.buffer.subarray(after + 2);
      this.state = "headers";
    }
  }

  private async emitBody(data: Buffer): Promise<void> {
    if (!data.length) return;
    if (this.sink) {
      const sink = this.sink;
      await new Promise<void>((resolve, reject) => {
        sink.write(Buffer.from(data), (error) => (error ? reject(error) : resolve()));
      });
      return;
    }
    this.fieldBytes += data.length;
    if (this.fieldBytes > this.maxFieldBytes) throw new Error(`Feld ${this.fieldName} ist zu lang`);
    this.fieldValue.push(Buffer.from(data));
  }

  private async endPart(): Promise<void> {
    if (this.sink) {
      const sink = this.sink;
      this.sink = null;
      await new Promise<void>((resolve, reject) => {
        sink.end((error?: Error | null) => (error ? reject(error) : resolve()));
      });
      return;
    }
    this.handlers.onField(this.fieldName, Buffer.concat(this.fieldValue).toString("utf8"));
    this.fieldValue = [];
  }
}
