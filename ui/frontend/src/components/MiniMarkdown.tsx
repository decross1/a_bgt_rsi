// Lightweight inline markdown renderer for Page B (experiment summary.md).
// Same small subset the JournalScroll renderer supports (headings,
// paragraphs, lists, fenced code, inline code, bold). Kept as its own
// component so Page B does not have to touch JournalScroll.tsx.
import type { ReactNode } from "react";

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
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

function renderMarkdown(md: string): ReactNode[] {
  const lines = md.split(/\r?\n/);
  const blocks: ReactNode[] = [];
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
      if (i < lines.length) i++;
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

export default function MiniMarkdown({ source }: { source: string }) {
  return <div data-testid="mini-markdown">{renderMarkdown(source)}</div>;
}
