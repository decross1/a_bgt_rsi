# Public reconstruction of the 2026-08-19 evaluation baseline

The production loop-memory, idea-ledger, feedback ledger, and iteration cache
are ignored, append-only operational stores. They are **not** copied into this
public test fixture. Publishing their lock-time prefixes would disclose large
amounts of unrelated retrieved paper text and internal research prose.

`weekly_upgrade_baseline_reconstruct.py` instead creates small temporary inputs
from benchmark artifacts that were already committed:

- the critic-calibration manifest and metadata;
- the committed critic override-audit report;
- the re-adjudication manifest; and
- the public red-team control fixtures.

The critic selector reconstruction retains all 26 selected rows and their
recorded replay envelopes exactly. Unselected rows retain only public IDs,
selection classes, and one-line synthetic placeholders needed to preserve the
locked pool and exclusion census.

The audit reconstruction inverts the committed per-row audit table into the
minimal fields consumed by `build_rows`. Its cluster membership is synthetic
except for each published latest iteration; it preserves the committed member
counts, latest-row selection, and no-ordering-ambiguity result. No original
cluster-membership claim is made.

The re-adjudication reconstruction retains the exact 88 public target rows and
the public refined-cluster sidecars. Other killed/open clusters are synthetic
and preserve only the published aggregate inventory.

`provenance.json` distinguishes the original source pins recorded in the lock
artifacts from hashes of these derived temporary inputs. Tests compare exact
scientific rows and normalized metadata; they never claim the reconstruction
is byte-identical to the ignored source stores.
