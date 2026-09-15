# Current campaign and research history

Research pages should open on the active campaign. The archival snapshot keeps
v0/v1 evidence retrievable; it does not delete source ledgers or resolve pending
human decisions. An explicit All research view exposes that retained history.

The UI sends `research_scope=active` to research list endpoints. Unqualified API
requests retain their historical all-record behavior. The active scope validates
the immutable campaign pointer and exact record links. Unknown or broken source
identity must not silently show global history. IDs must be globally unique;
time or topic similarity never establishes membership.

Iterations and findings are selected by explicit campaign links. A legacy/mixed
idea collection cannot donate its prior title, rung or disposition to the new
campaign; its independently linked iterations remain in Record library.
Experiment summaries must identify the campaign rather than inheriting a result
through a reused experiment ID. Global safety gates remain visible regardless
of research scope; a scoped empty queue does not mean that all lab gates cleared.

Scope controls must be visible on Research, Record library, Evaluations and the
Now page. Changing scope must clear or partition polling state before rendering,
so cached history cannot flash into the current view. Direct historical dossier
links remain readable and must state that the record belongs to history.

Validation covers active versus all rows, duplicate identities, malformed or
missing activation/source evidence, mixed collections, preserved safety gates,
unchanged source bytes, and live current/history navigation on desktop/mobile.

## Operator behavior

Choose **Current campaign** for the active v2 program. Choose **All research
history** to inspect retained v0/v1 work and other campaign records. The URL is
the selection authority: `?research_scope=all` is explicit history; the default
is current. Research, Record library, Evaluations and Now preserve that choice
through navigation. Changing it reloads the page and partitions polling state.

A current view can legitimately be empty: campaign activation does not itself
create an iteration, an experiment result, or a validated finding. A broken
campaign pointer or unreadable source is an error, not a measured zero. Absent
append-only sources are treated as not yet written. The operations graph remains
an explicitly labeled history of all recorded operations.

Current experiment list verdicts come only from their admitted campaign-linked
JSON summary. Detail pages are an explicit source/history library: historical
Markdown, trial files and journals have no automatic claim to campaign identity.
Before a new controlled experiment is admitted, its producer must write the
exact campaign link into its result summary. Reusing an old experiment ID or a
similar topic does not establish that link.

New coordinator bubbles receive campaign metadata from the coordinator's
validated single-topic campaign context. Model-authored requests cannot supply
that authority. Campaign bubbles with a recorded step use that step as their
queue/acknowledgement identity, so two questions in one cycle remain distinct.
Existing whole-cycle acknowledgements retain their meaning. Multi-topic campaign
bubbles remain unlinked until a validated topic-selection contract exists.

Idea collections are admitted only when every member is a uniquely identified
current-campaign iteration. Individual ledger events do not yet carry campaign
identity; this is a membership-based projection, not new independent evidence
certification. Mixed collections stay in history, while their current iterations
remain independently accessible. No gate, finding or old result is deleted,
resolved or promoted by switching the view.
