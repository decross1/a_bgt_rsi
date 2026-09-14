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
