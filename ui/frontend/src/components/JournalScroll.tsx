// LOOP_V0 journal scroll. Loads a journal markdown via
// /api/loop_v0/journal/{id} and renders it. Lightweight inline renderer —
// supports the small subset of markdown the journal_writer_stub emits
// (headings, paragraphs, lists, fenced code, inline code, bold). No new
// dependencies; the journal entries are short and the apparatus controls
// their shape.
import { useEffect, useState } from "react";
import { getJournalEntry } from "../api/http";
import type { JournalResponse } from "../types/schemas";

interface Props {
  iterationId?: string | null;
  initial?: JournalResponse | null;
}

function renderInline(text: string): React.ReactNode[] {
  // Handle `code` and **bold** inline. Anything else passes through.
  const nodes: React.ReactNode[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const token = m[0];
    if (token.startsWith("`")) {
      nodes.push(
        <code
          key={`c-${i++}`}
          className="rounded bg-zinc-950 px-1 font-mono text-[12px] text-zinc-300"
        >
          {token.slice(1, -1)}
        </code>,
      );
    } else {
      nodes.push(
        <strong key={`b-${i++}`} className="font-semibold text-zinc-100">
          {token.slice(2, -2)}
        </strong>,
      );
    }
    last = m.index + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function renderMarkdown(md: string): React.ReactNode[] {
  const lines = md.split(/\r?\n/);
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.startsWith("```")) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        code.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++; // consume closing fence
      blocks.push(
        <pre
          key={key++}
          className="my-2 overflow-x-auto rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[12px] text-zinc-300"
        >
          {code.join("\n")}
        </pre>,
      );
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      const level = h[1].length;
      const content = h[2];
      const cls =
        level === 1
          ? "mt-3 text-lg font-semibold text-zinc-100"
          : level === 2
            ? "mt-3 text-base font-semibold text-zinc-200"
            : "mt-2 text-sm font-medium text-zinc-300";
      blocks.push(
        <div key={key++} className={cls}>
          {renderInline(content)}
        </div>,
      );
      i++;
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*]\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={key++} className="my-1 list-disc pl-5 text-sm text-zinc-300">
          {items.map((item, j) => (
            <li key={j}>{renderInline(item)}</li>
          ))}
        </ul>,
      );
      continue;
    }
    // paragraph: take consecutive non-empty, non-block lines
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,6})\s+/.test(lines[i]) &&
      !lines[i].startsWith("```") &&
      !/^[-*]\s+/.test(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={key++} className="my-1 text-sm leading-relaxed text-zinc-300">
        {renderInline(para.join(" "))}
      </p>,
    );
  }
  return blocks;
}

export default function JournalScroll({ iterationId, initial }: Props) {
  const [data, setData] = useState<JournalResponse | null>(initial ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== undefined) return;
    if (!iterationId) {
      setData(null);
      setError(null);
      return;
    }
    let active = true;
    setError(null);
    getJournalEntry(iterationId)
      .then((d) => {
        if (active) setData(d);
      })
      .catch((e) => {
        if (active) {
          setData(null);
          setError(String(e));
        }
      });
    return () => {
      active = false;
    };
  }, [iterationId, initial]);

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="journal-scroll"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Journal entry
        </h2>
        <span className="text-[10px] text-zinc-600">
          /api/loop_v0/journal/{"{id}"}
        </span>
        {data && (
          <span className="ml-auto font-mono text-[10px] text-zinc-500">
            {data.path}
          </span>
        )}
      </div>

      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}

      {!iterationId && !data && !error && (
        <div className="mt-2 text-sm text-zinc-500">
          Select an iteration from the list to read its journal entry.
        </div>
      )}

      {data && (
        <div className="mt-2 max-h-[60vh] overflow-y-auto">
          {renderMarkdown(data.content)}
        </div>
      )}
    </div>
  );
}
