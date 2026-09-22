import { badRequest } from "@/lib/api/errors";

/* Kleiner JSON-Schema-Prüfer (Bordmittel, kein zod): reicht für die Request-Bodies der öffentlichen API.
 * Die Schemata stammen aus lib/api/openapi.ts, so bleibt Dokumentation und Prüfung eine Quelle.
 * Unterstützt: type (auch Listen mit "null"), enum, const, required, properties, additionalProperties: false,
 * minLength, maxLength, pattern, format (uuid, uri, date-time, email), minimum, maximum, items, minItems, maxItems. */

export interface JsonSchema {
  type?: string | string[];
  description?: string;
  enum?: readonly unknown[];
  const?: unknown;
  required?: readonly string[];
  properties?: Record<string, JsonSchema>;
  additionalProperties?: boolean | JsonSchema;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  format?: "uuid" | "uri" | "date-time" | "email";
  minimum?: number;
  maximum?: number;
  items?: JsonSchema;
  minItems?: number;
  maxItems?: number;
  default?: unknown;
  example?: unknown;
  nullable?: boolean;
  $ref?: string;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function typeOf(v: unknown): string {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  if (typeof v === "number") return Number.isInteger(v) ? "integer" : "number";
  return typeof v;
}

function matchesType(v: unknown, t: string): boolean {
  const actual = typeOf(v);
  if (t === "number") return actual === "number" || actual === "integer";
  return actual === t;
}

export interface ValidationIssue {
  path: string;
  message: string;
}

export function validate(value: unknown, schema: JsonSchema, path = "body", issues: ValidationIssue[] = [], resolve?: (ref: string) => JsonSchema | undefined): ValidationIssue[] {
  if (schema.$ref && resolve) {
    const target = resolve(schema.$ref);
    if (target) return validate(value, target, path, issues, resolve);
  }
  const types = schema.type ? (Array.isArray(schema.type) ? schema.type : [schema.type]) : [];
  const allowNull = schema.nullable || types.includes("null");
  if (value === null) {
    if (!allowNull) issues.push({ path, message: "darf nicht null sein" });
    return issues;
  }
  if (types.length && !types.some((t) => matchesType(value, t))) {
    issues.push({ path, message: `muss vom Typ ${types.filter((t) => t !== "null").join(" oder ")} sein` });
    return issues;
  }
  if (schema.enum && !schema.enum.includes(value)) {
    issues.push({ path, message: `muss einer der Werte ${schema.enum.map(String).join(", ")} sein` });
    return issues;
  }
  if (schema.const !== undefined && value !== schema.const) {
    issues.push({ path, message: `muss ${String(schema.const)} sein` });
    return issues;
  }
  if (typeof value === "string") {
    if (schema.minLength != null && value.trim().length < schema.minLength) issues.push({ path, message: `mindestens ${schema.minLength} Zeichen` });
    if (schema.maxLength != null && value.length > schema.maxLength) issues.push({ path, message: `höchstens ${schema.maxLength} Zeichen` });
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) issues.push({ path, message: "hat nicht das erwartete Format" });
    if (schema.format === "uuid" && !UUID_RE.test(value)) issues.push({ path, message: "muss eine UUID sein" });
    if (schema.format === "email" && !EMAIL_RE.test(value)) issues.push({ path, message: "muss eine E-Mail-Adresse sein" });
    if (schema.format === "date-time" && Number.isNaN(Date.parse(value))) issues.push({ path, message: "muss ein Zeitpunkt nach ISO 8601 sein" });
    if (schema.format === "uri") {
      try {
        new URL(value);
      } catch {
        issues.push({ path, message: "muss eine gültige URL sein" });
      }
    }
  }
  if (typeof value === "number") {
    if (schema.minimum != null && value < schema.minimum) issues.push({ path, message: `mindestens ${schema.minimum}` });
    if (schema.maximum != null && value > schema.maximum) issues.push({ path, message: `höchstens ${schema.maximum}` });
  }
  if (Array.isArray(value)) {
    if (schema.minItems != null && value.length < schema.minItems) issues.push({ path, message: `mindestens ${schema.minItems} Einträge` });
    if (schema.maxItems != null && value.length > schema.maxItems) issues.push({ path, message: `höchstens ${schema.maxItems} Einträge` });
    if (schema.items) value.forEach((item, i) => validate(item, schema.items as JsonSchema, `${path}[${i}]`, issues, resolve));
  }
  if (typeOf(value) === "object") {
    const obj = value as Record<string, unknown>;
    for (const key of schema.required ?? []) {
      if (obj[key] === undefined) issues.push({ path: `${path}.${key}`, message: "ist Pflicht" });
    }
    for (const [key, sub] of Object.entries(schema.properties ?? {})) {
      if (obj[key] !== undefined) validate(obj[key], sub, `${path}.${key}`, issues, resolve);
    }
    if (schema.additionalProperties === false) {
      for (const key of Object.keys(obj)) {
        if (!(schema.properties ?? {})[key]) issues.push({ path: `${path}.${key}`, message: "ist kein bekanntes Feld" });
      }
    }
  }
  return issues;
}

export function formatIssues(issues: ValidationIssue[]): string {
  return issues
    .slice(0, 5)
    .map((i) => `${i.path.replace(/^body\.?/, "") || "body"} ${i.message}`)
    .join("; ");
}

/* Liest den JSON-Body und prüft ihn gegen das Schema; leerer Body zählt als {} */
export async function readJsonBody<T = Record<string, unknown>>(request: Request, schema: JsonSchema | null, resolve?: (ref: string) => JsonSchema | undefined): Promise<T> {
  let raw = "";
  try {
    raw = await request.text();
  } catch {
    throw badRequest("Body konnte nicht gelesen werden.");
  }
  let value: unknown = {};
  if (raw.trim()) {
    try {
      value = JSON.parse(raw);
    } catch {
      throw badRequest("Ungültiger JSON-Body.", "invalid_json");
    }
  }
  if (schema) {
    const issues = validate(value, schema, "body", [], resolve);
    if (issues.length) throw badRequest(`Eingaben prüfen: ${formatIssues(issues)}.`, "validation_failed");
  }
  return value as T;
}
