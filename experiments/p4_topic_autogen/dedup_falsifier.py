"""P4 dedup keystone falsifier (zero model paging — BGE-M3 embeddings only).
Does BGE-M3 cosine collapse the known near-dup clusters while keeping the
distinct findings apart? Derives a defensible tau_dup."""
import json, itertools
from pathlib import Path
from sentence_transformers import SentenceTransformer

rows = {}
for l in open("memory/surfaced_findings.jsonl"):
    d = json.loads(l)
    rows[d.get("finding_id")] = d  # last write wins

def claim(d):
    return (d.get("claim") or d.get("hypothesis_text")
            or (d.get("why_it_matters") or "")).strip()

items = [(fid, claim(d)) for fid, d in rows.items() if claim(d)]
ids = [fid for fid, _ in items]
texts = [c for _, c in items]
print(f"findings with claim text: {len(items)}")

model = SentenceTransformer("/mnt/models/bge-m3")
emb = model.encode(texts, normalize_embeddings=True)
import numpy as np
cos = emb @ emb.T

# Known near-dup clusters (labeled positives) by title stem
def stem(t): return t[:60].lower()
from collections import defaultdict
groups = defaultdict(list)
for fid, c in items:
    groups[stem(c)].append(fid)
clusters = {k: v for k, v in groups.items() if len(v) > 1}
print(f"\n=== title-stem clusters (>=2): {len(clusters)} ===")
for k, v in clusters.items():
    idx = [ids.index(f) for f in v]
    sub = cos[np.ix_(idx, idx)]
    off = sub[np.triu_indices(len(idx), k=1)]
    print(f"  x{len(v)} intra-cluster cosine min/mean/max: {off.min():.3f}/{off.mean():.3f}/{off.max():.3f}  | {k[:50]}")

# Cross-cluster (distinct) max cosine: pick one representative per cluster + singletons
reps = [v[0] for v in clusters.values()] + [v[0] for v in groups.values() if len(v)==1]
ridx = [ids.index(f) for f in reps]
rc = cos[np.ix_(ridx, ridx)]
cross = rc[np.triu_indices(len(ridx), k=1)]
print(f"\n=== cross-DISTINCT cosine (representatives, n={len(reps)}) ===")
print(f"  max/mean: {cross.max():.3f}/{cross.mean():.3f}  (these must stay BELOW tau_dup)")

# tau_dup: separate intra-cluster (collapse) from cross-distinct (survive)
intra_min = min(cos[np.ix_([ids.index(f) for f in v],[ids.index(f) for f in v])][np.triu_indices(len(v),1)].min() for v in clusters.values())
print(f"\n=== tau_dup separation ===")
print(f"  lowest intra-cluster cosine (must be >= tau to collapse all): {intra_min:.3f}")
print(f"  highest cross-distinct cosine (must be <  tau to preserve):   {cross.max():.3f}")
sep = intra_min - cross.max()
print(f"  SEPARATION margin: {sep:+.3f}  -> {'CLEAN (tau_dup = midpoint)' if sep>0 else 'NO CLEAN tau (overlap)'}")
if sep > 0:
    print(f"  recommended tau_dup = {(intra_min+cross.max())/2:.3f}")
