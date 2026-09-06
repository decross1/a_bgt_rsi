import { developmentReceipt } from "../data/developmentReceipt";

export default function DevelopmentNotice({ compact = false }: { compact?: boolean }) {
  return (
    <aside className="mb-3 rounded border border-[var(--border-1)] bg-[var(--surface-1)] p-3 text-sm" aria-label="Engineering progress">
      <a href="/development" className="font-medium text-[var(--accent)]">
        {compact ? "Codex engineering and readiness →" : developmentReceipt.title + " →"}
      </a>
      <p className="mt-1 text-[var(--fg-muted)]">
        The lab queue tracks runtime and research work. Codex commits do not add
        Nara messages, accept frontier suggestions or move scientific rungs.
      </p>
      {!compact && <p className="mt-1 text-xs text-[var(--fg-muted)]">
        Dated delivery receipt: {developmentReceipt.recordedAt}. PR #3 was a draft;
        this is not live merge or deployment status.
      </p>}
    </aside>
  );
}
