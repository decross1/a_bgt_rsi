# Mia reduced-vocabulary image overlay

These are the exact sources used for the CPU-only child image build on
2026-09-15. The original Mia image remains unchanged. Registration and image
construction do not constitute GPU/runtime qualification.

The builder checks the exact parent image, stock MTP module, upstream patch,
47,149 vocabulary IDs and file SHA, then builds with network disabled. A fresh
local base tag is checked against the parent image ID before and after the
build, and the child's root-filesystem layer prefix must match that parent.
The initial direct `FROM sha256:...` attempt failed because Docker interpreted
it as a repository name; its log was retained in the artifact store.

The patch script is from the pinned Mia recipe; the stock module retains its
vLLM Apache-2.0 SPDX attribution. Their byte identity is required by the
registered runtime, so linting does not rewrite them.

The completed build receipt is outside Git at
`runtime/mia-reduced47k-image-build/IMAGE_BUILD_RECEIPT.json` under the Flash
research artifact root. The literal image/spec binding lives in
`../reduced_profile_literal.py`. `build_reduced_overlay.py` refuses an existing
receipt output or existing child tag; it cannot silently overwrite a prior
build. GPU use goes through the normal qualification supervisor and rollback.
