// DossierReader (/dossier/:id) — the reader's KIND-GATE + fence pins, PORTED
// from the retired tests/test_todo_kind_gating.tsx (the /todo cockpit died in
// UI simplification S2; the reader inherited the invariants):
//
//   - an ITERATION dossier (gate_verdict) → GateVerdictForm is the ONLY
//     disposition (+ the verbatim CLI-fallback block); every finding-keyed
//     form is ABSENT; the interrogation is reveal-gated;
//   - a FINDING dossier (finding_review) → the finding-keyed form set renders;
//     GateVerdictForm is ABSENT;
//   - a BUBBLE dossier → BubbleAckForm only; NO interrogation at any phase;
//   - a STATE-GATE / unknown / HOSTILE kind → NEITHER keyed family — only the
//     kind-agnostic DeferForm + CalibrationCapture;
//   - the CHAT panes NEVER expose a disposition (the verdict fence);
//   - the forms render UNCONDITIONALLY (no resolution-locked element;
//     calibration is opt-in and gates nothing);
//   - an id NOT in the live queue resolves its kind from the sf-*/iter-*
//     prefix (the index's resolved-history rows).
//
// Network is stubbed by URL (mirrors the retired suite). The attest capability
// probe answers LIVE so the self-gating forms actually render their testids —
// letting presence AND absence be asserted by id.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import DossierReader from "../src/routes/DossierReader";
import { AVAILABILITY_LIVE, AVAILABILITY_STUB } from "../src/fixtures/todo";
import { resetAttestCapabilityCache } from "../src/api/attest";
import type { CockpitAvailability } from "../src/types/todo";
import type { HumanTodoItem } from "../src/types/schemas";

const GATE_VERDICT_ITEM: HumanTodoItem = {
  kind: "gate_verdict",
  id: "iter-2026-06-14-002",
  title: "Verdict needed: novel_on_02 over-gated by primary R0",
};
const FINDING_REVIEW_ITEM: HumanTodoItem = {
  kind: "finding_review",
  id: "sf-2026-06-14-001",
  title: "Finding: shading is dominated under VCG (survives 2/3)",
  evidence_level: "L4",
};
const BUBBLE_ACK_ITEM: HumanTodoItem = {
  kind: "bubble_ack",
  id: "bubble-2026-06-14-001",
  title: "Bubble: coordinator raised a degraded-signal note",
};
const STATE_GATE_ITEM: HumanTodoItem = {
  kind: "state_gate",
  id: "gate-d049-ratification",
  title: "State-file gate: D-049 scheduled cycles await ratification",
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  } as unknown as Response;
}

beforeEach(() => {
  vi.stubGlobal("fetch", async (url: unknown) => {
    const u = String(url);
    if (u.endsWith("/api/todo/concurrency")) return jsonResponse(200, { active: false });
    if (u.endsWith("/api/human_todo")) return jsonResponse(200, { items: [], counts: {} });
    // LIVE attest capability so the self-gating forms (gate_verdict /
    // finding_review / bubble_ack / defer) render their form testids.
    if (u.endsWith("/api/attest/available"))
      return jsonResponse(200, {
        available: true,
        actions: {
          gate_verdict: true,
          finding_review: true,
          bubble_ack: true,
          defer: true,
        },
      });
    // The tutor + journey self-fetches degrade in place (found:false).
    if (u.includes("/api/finding/"))
      return jsonResponse(200, { found: false, finding_id: "x" });
    if (u.includes("/journey"))
      return jsonResponse(200, { found: false, iteration_id: "x", iteration: null });
    if (u.endsWith("/api/coordinator/cycles")) return jsonResponse(200, { cycles: [] });
    if (u.includes("/api/todo/"))
      return jsonResponse(200, { status: "stub", would_run: ["<read-only>"] });
    return jsonResponse(404, {});
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  // The attest capability is cached module-level per page-load; reset it so a
  // live-capability test does not leak into the next.
  resetAttestCapabilityCache();
});

function renderReader(
  id: string,
  items: HumanTodoItem[],
  availability: CockpitAvailability = AVAILABILITY_LIVE,
) {
  return render(
    <MemoryRouter initialEntries={[`/dossier/${encodeURIComponent(id)}`]}>
      <Routes>
        <Route
          path="/dossier/:id"
          element={<DossierReader availability={availability} items={items} />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

// The keyed FORM testids, grouped by the family their id is keyed for.
const ITERATION_KEYED = ["gate-verdict-form"] as const;
const FINDING_KEYED = [
  "finding-review-form",
  "directive-signoff-field",
  "authorize-fix-form",
  "spawn-topic-form",
  "abstain-form",
] as const;

// The interrogation surfaces: the section, its reveal button, the revealed
// wrapper, and the two chat panes.
const AUX_SURFACES = [
  "dossier-interrogate",
  "reveal-interrogation",
  "dossier-aux-interactive",
  "tutor-chat-pane",
  "two-voice-chat-pane",
] as const;

function expectNoKeyedForms() {
  for (const id of ITERATION_KEYED) expect(screen.queryByTestId(id)).toBeNull();
  for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();
}

function expectNoAux() {
  for (const id of AUX_SURFACES) expect(screen.queryByTestId(id)).toBeNull();
}

// An interrogable dossier PRE-reveal: section + button present, panes hidden.
function expectAuxRevealableTrioHidden() {
  expect(screen.getByTestId("dossier-interrogate")).toBeInTheDocument();
  expect(screen.getByTestId("reveal-interrogation")).toBeInTheDocument();
  expect(screen.queryByTestId("dossier-aux-interactive")).toBeNull();
  expect(screen.queryByTestId("tutor-chat-pane")).toBeNull();
  expect(screen.queryByTestId("two-voice-chat-pane")).toBeNull();
}

async function revealInterrogation() {
  fireEvent.click(screen.getByTestId("reveal-interrogation"));
  await waitFor(() =>
    expect(screen.getByTestId("dossier-aux-interactive")).toBeInTheDocument(),
  );
}

describe("DossierReader — the U5 kind-gate, ported", () => {
  it("an ITERATION dossier shows GateVerdictForm ONLY (+ the verbatim CLI fallback)", async () => {
    renderReader(GATE_VERDICT_ITEM.id, [GATE_VERDICT_ITEM]);

    // The disposition footer renders UNCONDITIONALLY.
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-locked")).toBeNull();

    // ITERATION-keyed form present (self-gates on the LIVE attest capability —
    // async, so waitFor its testid).
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    // The CLI fallback block ported verbatim from the retired modal.
    const cli = screen.getByTestId("dossier-gate-cli");
    expect(cli).toHaveTextContent(
      ".venv-chroma/bin/python -m orchestrator.gate_cli --iteration-id iter-2026-06-14-002",
    );
    expect(cli).toHaveTextContent("<valid|invalid|needs_revision>");

    // FINDING-keyed forms ABSENT — no iteration_id reaches them.
    for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();

    // The iteration is interrogable: reveal-gated panes, GateVerdictForm stays
    // the ONLY disposition after the reveal (the fence).
    expectAuxRevealableTrioHidden();
    await revealInterrogation();
    expect(screen.getByTestId("tutor-chat-pane")).toBeInTheDocument();
    expect(screen.getByTestId("two-voice-chat-pane")).toBeInTheDocument();
    for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();
    expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument();

    // Kind-agnostic surfaces.
    await waitFor(() =>
      expect(screen.getByTestId("defer-form")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
  });

  it("a FINDING dossier shows the finding-keyed set; GateVerdictForm is ABSENT", async () => {
    renderReader(FINDING_REVIEW_ITEM.id, [FINDING_REVIEW_ITEM]);

    await waitFor(() =>
      expect(screen.getByTestId("finding-review-form")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("directive-signoff-field")).toBeInTheDocument();
    expect(screen.getByTestId("authorize-fix-form")).toBeInTheDocument();
    expect(screen.getByTestId("spawn-topic-form")).toBeInTheDocument();
    expect(screen.getByTestId("abstain-form")).toBeInTheDocument();

    // No iteration-keyed disposition, no CLI gate fallback.
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(screen.queryByTestId("dossier-gate-cli")).toBeNull();

    // Reveal-gated interrogation; the panes carry the REAL finding id.
    expectAuxRevealableTrioHidden();
    await revealInterrogation();
    const aux = screen.getByTestId("dossier-aux-interactive");
    const twoVoice = within(aux).getByTestId("two-voice-chat-pane");
    expect(
      within(twoVoice).getByText(/directed at both · sf-2026-06-14-001/),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
  });

  it("a BUBBLE dossier shows BubbleAckForm only — no keyed family, NO interrogation", async () => {
    renderReader(BUBBLE_ACK_ITEM.id, [BUBBLE_ACK_ITEM]);
    await waitFor(() =>
      expect(screen.getByTestId("bubble-ack-form")).toBeInTheDocument(),
    );
    expectNoKeyedForms();
    expectNoAux();
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("defer-form")).toBeInTheDocument(),
    );
  });

  it("a STATE-GATE dossier is defer-ONLY: neither keyed family, no interrogation", async () => {
    renderReader(STATE_GATE_ITEM.id, [STATE_GATE_ITEM]);
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
    expectNoKeyedForms();
    expectNoAux();
    expect(screen.queryByTestId("bubble-ack-form")).toBeNull();
    await waitFor(() =>
      expect(screen.getByTestId("defer-form")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("defer-only-note")).toBeInTheDocument();
  });
});

describe("DossierReader — HOSTILE kind values all route to OTHER", () => {
  const HOSTILE_KINDS: ReadonlyArray<readonly [string, unknown]> = [
    ["null", null],
    ["a number", 42],
    ["an object", { kind: "finding_review" }],
    ["an array", ["finding_review"]],
    ["empty string", ""],
    ["whitespace-padded finding_review", "  finding_review  "],
    ["wrong-case GATE_VERDICT", "GATE_VERDICT"],
    ["an unknown string", "totally_made_up_kind"],
    ["a boolean", true],
  ];

  for (const [label, kind] of HOSTILE_KINDS) {
    it(`kind = ${label} → NEITHER keyed family renders, no aux, no crash`, () => {
      // A NON-prefixed id so the prefix fallback cannot re-key the family —
      // the hostile kind itself is what the gate must route to "other".
      const item = {
        id: "hostile-0001",
        kind: kind as HumanTodoItem["kind"],
        title: "hostile-kind probe row",
      } as HumanTodoItem;
      renderReader("hostile-0001", [item]);
      expect(screen.getByTestId("dossier-reader")).toBeInTheDocument();
      expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
      expectNoKeyedForms();
      expectNoAux();
      expect(screen.queryByTestId("bubble-ack-form")).toBeNull();
      // The kind-agnostic calibration capture still renders — never a blank
      // dossier. No garbage leaked from a non-string kind.
      expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
      expect(screen.queryByText(/\[object Object\]/)).toBeNull();
    });
  }
});

describe("DossierReader — prefix fallback for ids NOT in the live queue", () => {
  it("an sf-* id resolves as a FINDING dossier (queue miss)", async () => {
    renderReader("sf-legacy-0031", []);
    // The header says the kind was read from the id.
    expect(screen.getByTestId("dossier-kind")).toHaveTextContent("finding_review");
    await waitFor(() =>
      expect(screen.getByTestId("finding-review-form")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
  });

  it("an iter-* id resolves as an ITERATION dossier (queue miss — the resolved history rows)", async () => {
    renderReader("iter-2026-06-10-001", []);
    expect(screen.getByTestId("dossier-kind")).toHaveTextContent("gate_verdict");
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();
  });

  it("an unprefixed unknown id degrades honestly: unknown kind, defer-less, no keyed family", () => {
    renderReader("mystery-id-0001", []);
    expect(screen.getByTestId("dossier-kind-unknown")).toBeInTheDocument();
    expectNoKeyedForms();
    expectNoAux();
    // DeferForm owns its own frozen-enum gate — an unknown kind renders no
    // defer either (deferKindOf → null); calibration keeps the page usable.
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
  });
});

describe("DossierReader — the forms render UNCONDITIONALLY (calibration is opt-in)", () => {
  it("recording the OPTIONAL calibration changes nothing about which forms render", async () => {
    renderReader(GATE_VERDICT_ITEM.id, [GATE_VERDICT_ITEM]);
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-locked")).toBeNull();
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );

    // Record a blind calibration.
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "survives the attack panel 2/3" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("calibration-captured")).toBeInTheDocument(),
    );
    // The form set is unchanged; calibration revealed nothing hidden.
    expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument();
    for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();
    // Calibration did NOT reveal the interrogation either (independent gates).
    expectAuxRevealableTrioHidden();
  });
});

describe("DossierReader — the chat NEVER exposes a disposition (the fence)", () => {
  it("inside the revealed panes: no verdict-shaped control exists; the forms stay outside", async () => {
    renderReader(FINDING_REVIEW_ITEM.id, [FINDING_REVIEW_ITEM]);
    await revealInterrogation();
    const aux = screen.getByTestId("dossier-aux-interactive");
    // No verdict/disposition control inside either pane.
    for (const re of [
      /valid/i,
      /invalid/i,
      /needs_revision/i,
      /sign[\s_-]?off/i,
      /authorize/i,
      /abstain/i,
      /approve/i,
      /reject/i,
    ]) {
      expect(within(aux).queryByRole("button", { name: re })).toBeNull();
    }
    // The panes' only buttons are the send + addressee controls.
    const buttons = within(aux).getAllByRole("button").map((b) => b.textContent);
    for (const label of buttons) {
      expect(label).toMatch(/^(send|send turn|defender|attacker|both)$/);
    }
    // The tutor pane cites the tutor fence; the two-voice pane cites D-044.
    expect(within(aux).getByTestId("tutor-chat-fence-note")).toHaveTextContent(
      /D-053/,
    );
    expect(within(aux).getByTestId("two-voice-fence-note")).toHaveTextContent(
      /D-044/,
    );
  });
});

describe("DossierReader — capability wiring (lifted from Todo.tsx)", () => {
  it("LIVE capability flows through: AbstainForm enables with a note", async () => {
    renderReader(FINDING_REVIEW_ITEM.id, [FINDING_REVIEW_ITEM], AVAILABILITY_LIVE);
    await waitFor(() =>
      expect(screen.getByTestId("abstain-form")).toBeInTheDocument(),
    );
    const abstain = screen.getByTestId("abstain-form");
    fireEvent.change(within(abstain).getByLabelText(/abstain note/i), {
      target: { value: "revisit after R0 fix" },
    });
    await waitFor(() =>
      expect(
        within(abstain).getByRole("button", { name: /^abstain$/i }),
      ).not.toBeDisabled(),
    );
  });

  it("STUB capability keeps the gated forms honestly disabled", async () => {
    renderReader(FINDING_REVIEW_ITEM.id, [FINDING_REVIEW_ITEM], AVAILABILITY_STUB);
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-form")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("authorize-fix-stub")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /authorize fix/i })).toBeDisabled();
    // The chat panes sit disabled too (two_voice_chat:false).
    await revealInterrogation();
    expect(screen.getByTestId("tutor-chat-send")).toBeDisabled();
    expect(screen.getByTestId("two-voice-send")).toBeDisabled();
  });
});

describe("DossierReader — header + spine", () => {
  it("renders the header (id · kind · title), the journey spine, and the concurrency guard slot", () => {
    renderReader(GATE_VERDICT_ITEM.id, [GATE_VERDICT_ITEM]);
    const header = screen.getByTestId("dossier-header");
    expect(header).toHaveTextContent("iter-2026-06-14-002");
    expect(within(header).getByTestId("dossier-kind")).toHaveTextContent(
      "gate_verdict",
    );
    expect(header).toHaveTextContent(
      "Verdict needed: novel_on_02 over-gated by primary R0",
    );
    // The journey spine mounts (its own suite owns the internals).
    expect(screen.getByTestId("pipeline-journey")).toBeInTheDocument();
    // The tutor overview mounts pre-reveal (the trimmed TutorPanel).
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-considerations")).toBeNull();
  });

  it("the deferred sky chip renders on a deferred dossier", () => {
    renderReader("sf-def-01", [
      {
        kind: "finding_review",
        id: "sf-def-01",
        title: "deferred one",
        deferred: true,
      },
    ]);
    expect(screen.getByTestId("todo-deferred-tag")).toHaveTextContent(
      /deferred to dev session/i,
    );
  });
});
