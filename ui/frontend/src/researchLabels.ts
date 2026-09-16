function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function cleanText(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== ""
    ? value.trim().replace(/\s+/g, " ")
    : null;
}

function quotedField(value: string, field: string): string | null {
  const marker = `"${field}"`;
  const markerAt = value.lastIndexOf(marker);
  if (markerAt < 0) return null;
  const colonAt = value.indexOf(":", markerAt + marker.length);
  if (colonAt < 0) return null;
  let start = colonAt + 1;
  while (/\s/.test(value[start] ?? "")) start += 1;
  if (value[start] !== '"') return null;
  let escaped = false;
  for (let index = start + 1; index < value.length; index += 1) {
    const character = value[index];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (character === "\\") {
      escaped = true;
      continue;
    }
    if (character !== '"') continue;
    const literal = value.slice(start, index + 1);
    try {
      return cleanText(JSON.parse(literal));
    } catch {
      // Preserve producer backslashes outside JSON's escape set while decoding
      // the standard escapes needed for readable selected prose.
      const inner = literal.slice(1, -1);
      let decoded = "";
      for (let offset = 0; offset < inner.length; offset += 1) {
        if (inner[offset] !== "\\" || offset + 1 >= inner.length) {
          decoded += inner[offset];
          continue;
        }
        const next = inner[offset + 1];
        const mapped: Record<string, string> = {
          '"': '"', "\\": "\\", "/": "/", b: "\b", f: "\f",
          n: "\n", r: "\r", t: "\t",
        };
        if (next === "u" && /^[0-9a-fA-F]{4}$/.test(inner.slice(offset + 2, offset + 6))) {
          decoded += String.fromCharCode(Number.parseInt(inner.slice(offset + 2, offset + 6), 16));
          offset += 5;
        } else if (mapped[next] !== undefined) {
          decoded += mapped[next];
          offset += 1;
        } else {
          decoded += `\\${next}`;
          offset += 1;
        }
      }
      return cleanText(decoded);
    }
  }
  return null;
}

/** Resolve a producer hypothesis without showing a serialized candidate envelope. */
export function iterationQuestion(value: unknown): string | null {
  const row = record(value);
  const hypothesis = record(row?.hypothesis);
  const raw = cleanText(hypothesis?.text);
  if (raw === null) return null;
  if (raw.startsWith("{")) {
    try {
      const parsed = record(JSON.parse(raw));
      const chosen = cleanText(parsed?.chosen);
      if (chosen !== null) return chosen;
    } catch {
      const chosen = quotedField(raw, "chosen");
      if (chosen !== null) return chosen;
    }
  }
  return raw;
}

function shortenedQuestion(question: string): string {
  const withoutLead = question.replace(/^(in|against|when)\s+/i, "");
  const clause = withoutLead.split(/\s+(?:because|whereas|compared to|is caused by)\s+/i)[0];
  if (clause.length <= 92) return clause.replace(/[.,;:]$/, "");
  const cut = clause.slice(0, 89).replace(/\s+\S*$/, "");
  return `${cut}…`;
}

/**
 * Concise labels are deterministic transformations of the received hypothesis.
 * The three current labels are guarded by both exact iteration identity and
 * evidence-bearing phrases, so a changed source falls back to its own text.
 */
export function iterationDisplayTitle(value: unknown): string | null {
  const row = record(value);
  const id = cleanText(row?.iteration_id);
  const question = iterationQuestion(row);
  if (question === null) return null;
  const lower = question.toLowerCase();
  if (
    id === "iter-2026-09-15-007"
    && lower.includes("exact focal and pooled payoffs")
    && lower.includes("oracle-consistent actions")
  ) return "Payoff arithmetic and strategic consistency";
  if (
    id === "iter-2026-09-15-008"
    && lower.includes("seat-indexed action table")
    && lower.includes("word-list representation")
  ) return "Seat-indexed action tables";
  if (
    id === "iter-2026-09-15-009"
    && lower.includes("future retaliation")
    && lower.includes("joint-payoff objective")
  ) return "Future retaliation and joint payoff";
  return shortenedQuestion(question);
}

export function collectionDisplayTitle(values: unknown[]): string | null {
  const titles = values.map(iterationDisplayTitle).filter((title): title is string => title !== null);
  if (titles.length === 0) return null;
  const titleSet = new Set(titles);
  if (
    titleSet.has("Payoff arithmetic and strategic consistency")
    && titleSet.has("Seat-indexed action tables")
    && titleSet.has("Future retaliation and joint payoff")
  ) return "Strategic consistency: arithmetic, action tables, and retaliation";
  return titles.length === 1 ? titles[0] : `${titles[0]} + ${titles.length - 1} related questions`;
}
