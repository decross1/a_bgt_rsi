# Frozen research evidence inventory

`tools/research_inventory_view.py` renders a local, filterable HTML table from an
explicit inventory. It verifies the selected inventory digest, all source bytes,
referenced raw rows, and the declared coverage. It imports no runtime modules
and executes no model source. The inventory and frozen sources remain private;
only this renderer, tests, and documentation belong in a public code range.

The caller supplies classifications and the expected item set. These checks
establish consistency with those inputs, not source authentication or research
validity. The caller controls trusted snapshot ancestry and lifecycle. No OS
confinement or race-free filesystem claim is made by this renderer.

Each item carries its recorded evidence-ladder level, separate binding status,
explicit disposition, last evidence, next requirement, confidence and sources.
The table's timestamp is the latest member observation, not an administrative
cluster-event timestamp or proof of scientific confirmation. Ledger timestamps
are separate fields in the companion inventory.
An L1/L2 label cannot establish novelty or effect validity. Missing binding is
not falsity; killed and negative outcomes remain visible. L3 requires a precisely
bound claim, valid experiment, relevant controls, independent confirmation and
scope-correct evidence, not merely a nonempty cross-tier payload. Experiment
tiers and governance tiers remain separate from evidence-ladder labels.

The view is a frozen development artifact, not a live runtime dashboard. It
does not infer “running” from stale activity or promote an item. The caller
must supply a new pinned inventory to refresh it. Historical iterations stay
in the companion JSON; the table shows current clusters, including inactive
ones. Search, status filtering and the L1/L2 filter run entirely in the browser
without external assets, network requests or interpreting source text as HTML.

Invoke with an explicit inventory path, its `--sha256`, a private `--snapshot`
directory and a new `--output` path. Existing outputs are never overwritten.
The renderer is independent of any generated progress-worker candidate; an
unaccepted candidate must not be represented as repaired by this view.
