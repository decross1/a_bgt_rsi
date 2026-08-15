// ChannelRefs — the /channel reference chips (revamp R4). An id the apparatus
// wrote into a message (cl-* / iter-* / sf-*) becomes a clickable chip that
// PEEKS at the object; the object itself is never inlined into the thread —
// the thread stays a conversation, the ladder/dossier stay the full surfaces.
//
// Two renderings, one chip:
//   RefText    — plain bodies (human turns, event lines) get INLINE chips.
//   RefChipRow — markdown bodies keep MiniMarkdown verbatim (it is shared with
//                the journal/experiment readers and R4 does not get to fork
//                it), so their ids are collected into one chip row beneath.
import { refSegments } from "./channelModel";
import type { ChannelRef } from "./channelModel";

export function RefChip({
  refItem,
  onOpen,
}: {
  refItem: ChannelRef;
  onOpen: (r: ChannelRef) => void;
}) {
  return (
    <button
      type="button"
      className="chn-ref"
      data-testid="channel-ref-chip"
      data-ref-kind={refItem.kind}
      data-ref-id={refItem.id}
      title={`peek at this ${refItem.kind}`}
      onClick={() => onOpen(refItem)}
    >
      {refItem.id}
    </button>
  );
}

export function RefText({
  text,
  onOpen,
}: {
  text: string;
  onOpen: (r: ChannelRef) => void;
}) {
  const segments = refSegments(text);
  return (
    <>
      {segments.map((seg, i) =>
        seg.t === "ref" ? (
          <RefChip key={`r-${i}`} refItem={seg.ref} onOpen={onOpen} />
        ) : (
          <span key={`t-${i}`}>{seg.value}</span>
        ),
      )}
    </>
  );
}

export function RefChipRow({
  refs,
  onOpen,
}: {
  refs: ChannelRef[];
  onOpen: (r: ChannelRef) => void;
}) {
  if (refs.length === 0) return null;
  return (
    <div className="chn-refrow" data-testid="channel-voice-refs">
      <span>refs</span>
      {refs.map((r) => (
        <RefChip key={r.id} refItem={r} onOpen={onOpen} />
      ))}
    </div>
  );
}
