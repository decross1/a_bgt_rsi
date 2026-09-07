import { describe, expect, it, vi } from "vitest";
import type { LadderCluster } from "../src/types/schemas";
import {
  buildThesisFamilies,
  matchesFamilyRecord,
} from "../src/components/ladder/thesisModel";

const REPRESENTATION_TOPIC =
  "Representation in Peer Selection: A Liquid Democracy Perspective";
const POWER_TOPIC =
  "Power in Liquid Democracy: A Network Centrality Approach";

function cluster(
  id: string,
  members: string[] | null,
  overrides: Partial<LadderCluster> = {},
): LadderCluster {
  return {
    cluster_id: id,
    stem: `Stem for ${id}`,
    status: "open",
    evidence_level: "L0",
    members,
    member_count: members?.length ?? 0,
    ...overrides,
  };
}

function iteration(
  id: string,
  topic: unknown,
  hypothesis = `Hypothesis for ${id}`,
): Record<string, unknown> {
  return {
    iteration_id: id,
    seed: { topic },
    hypothesis: { text: hypothesis },
    started_at: "2026-09-07T00:00:00Z",
    ended_at: "2026-09-07T00:01:00Z",
  };
}

function identityProjection(result: ReturnType<typeof buildThesisFamilies>) {
  return result.families.map((family) => ({
    id: family.id,
    recordIds: family.records.map((record) => record.id),
    topicLabels: family.topicLabels,
  }));
}

describe("buildThesisFamilies", () => {
  it("groups one exact normalized topic with order-independent identities", () => {
    const killed = cluster("cl-killed", ["iter-a"], {
      status: "killed",
      evidence_level: "L1",
      kill_reason: { code: "negative_result", detail: "claim did not survive" },
    });
    const surfaced = cluster("cl-surfaced", ["iter-b"], {
      status: "surfaced",
      evidence_level: "L4",
    });
    const rowA = iteration("iter-a", "  Shared\n\tTopic  ");
    const rowB = iteration("iter-b", "Shared Topic");

    const reversed = buildThesisFamilies(
      [surfaced, killed],
      { iterations: [rowB, rowA] },
    );
    const forward = buildThesisFamilies(
      [killed, surfaced],
      { iterations: [rowA, rowB] },
    );

    expect(identityProjection(reversed)).toEqual(identityProjection(forward));
    expect(reversed.families).toHaveLength(1);
    expect(reversed.families[0]).toMatchObject({
      id: "topic:Shared Topic",
      title: "Shared Topic",
      basis: "exact iteration seed.topic",
      topicLabels: ["Shared Topic"],
    });
    expect(reversed.families[0].records.map((record) => record.id)).toEqual([
      "cl-killed",
      "cl-surfaced",
    ]);

    const killedRecord = reversed.records.find((record) => record.id === "cl-killed");
    const surfacedRecord = reversed.records.find(
      (record) => record.id === "cl-surfaced",
    );
    expect(killedRecord?.cluster).toBe(killed);
    expect(killedRecord?.cluster.status).toBe("killed");
    expect(killedRecord?.cluster.evidence_level).toBe("L1");
    expect(killedRecord?.iterations[0].source).toBe(rowA);
    expect(surfacedRecord?.cluster).toBe(surfaced);
    expect(surfacedRecord?.cluster.evidence_level).toBe("L4");
  });

  it("uses only the two explicit liquid-democracy topics for the curated collection", () => {
    const rows = [
      iteration("iter-representation", REPRESENTATION_TOPIC),
      iteration("iter-power", POWER_TOPIC),
      iteration("iter-prefix", `${POWER_TOPIC}: An Extension`),
      iteration("iter-case", POWER_TOPIC.toLowerCase()),
    ];
    const result = buildThesisFamilies(
      [
        cluster("cl-prefix", ["iter-prefix"]),
        cluster("cl-power", ["iter-power"]),
        cluster("cl-case", ["iter-case"]),
        cluster("cl-representation", ["iter-representation"]),
      ],
      rows,
    );

    const curated = result.families.find(
      (family) => family.id === "collection:liquid-democracy",
    );
    expect(curated).toMatchObject({
      title: "Liquid democracy",
      basis: "curated topic collection — association only",
      topicLabels: [POWER_TOPIC, REPRESENTATION_TOPIC],
    });
    expect(curated?.records.map((record) => record.id)).toEqual([
      "cl-power",
      "cl-representation",
    ]);
    expect(curated?.records.every(
      (record) => record.association === "curated-topic-collection",
    )).toBe(true);

    expect(result.families.some(
      (family) => family.id === `topic:${POWER_TOPIC}: An Extension`,
    )).toBe(true);
    expect(result.families.some(
      (family) => family.id === `topic:${POWER_TOPIC.toLowerCase()}`,
    )).toBe(true);
  });

  it("keeps mixed, missing, unsupported, and absent members individual", () => {
    const rows = [iteration("iter-a", "Topic A"), iteration("iter-b", "Topic B")];
    const result = buildThesisFamilies(
      [
        cluster("cl-a", ["iter-a"]),
        cluster("cl-b", ["iter-b"]),
        cluster("cl-mixed", ["iter-a", "iter-b"]),
        cluster("cl-missing", ["iter-does-not-exist"]),
        cluster("cl-paper", ["paper:2608.13085"]),
        cluster("cl-no-members", []),
        cluster("cl-null-members", null),
      ],
      { iterations: rows },
    );

    expect(result.families.find((family) => family.id === "topic:Topic A")?.records)
      .toHaveLength(1);
    expect(result.families.find((family) => family.id === "topic:Topic B")?.records)
      .toHaveLength(1);

    const mixed = result.records.find((record) => record.id === "cl-mixed");
    expect(mixed).toMatchObject({
      association: "individual",
      topics: ["Topic A", "Topic B"],
      missingMembers: [],
    });
    expect(mixed?.reason).toMatch(/multiple exact topics/i);
    expect(result.families.find((family) => family.id === "record:cl-mixed")?.records)
      .toHaveLength(1);

    const missing = result.records.find((record) => record.id === "cl-missing");
    expect(missing?.association).toBe("individual");
    expect(missing?.missingMembers).toEqual(["iter-does-not-exist"]);
    expect(missing?.reason).toMatch(/missing iteration record/i);

    const paper = result.records.find((record) => record.id === "cl-paper");
    expect(paper?.association).toBe("individual");
    expect(paper?.missingMembers).toEqual(["paper:2608.13085"]);
    expect(paper?.reason).toMatch(/unsupported member/i);

    expect(result.records.find((record) => record.id === "cl-no-members")?.reason)
      .toMatch(/no members/i);
    expect(result.records.find((record) => record.id === "cl-null-members")?.reason)
      .toMatch(/missing or malformed/i);
    expect(result.records).toHaveLength(7);
    expect(result.families.flatMap((family) => family.records)).toHaveLength(7);
  });

  it("coalesces identical duplicate rows and duplicate cluster members", () => {
    const first = {
      iteration_id: "iter-duplicate",
      seed: { topic: "Duplicate-safe topic" },
      hypothesis: { text: "Same claim" },
    };
    const sameWithDifferentKeyOrder = {
      hypothesis: { text: "Same claim" },
      seed: { topic: "Duplicate-safe topic" },
      iteration_id: "iter-duplicate",
    };
    const result = buildThesisFamilies(
      [cluster("cl-duplicate", ["iter-duplicate", "iter-duplicate"])],
      [first, sameWithDifferentKeyOrder],
    );

    expect(result.issues).toEqual([]);
    expect(result.records[0]).toMatchObject({
      association: "exact-topic",
      topics: ["Duplicate-safe topic"],
      missingMembers: [],
    });
    expect(result.records[0].iterations).toHaveLength(1);
    expect(result.records[0].iterations[0].source).toBe(first);
  });

  it("refuses every join to a conflicting duplicate iteration id", () => {
    const result = buildThesisFamilies(
      [cluster("cl-conflict", ["iter-conflict"])],
      [
        iteration("iter-conflict", "Same topic", "Claim one"),
        iteration("iter-conflict", "Same topic", "Claim two"),
      ],
    );

    expect(result.records[0].association).toBe("individual");
    expect(result.records[0].iterations).toEqual([]);
    expect(result.records[0].missingMembers).toEqual(["iter-conflict"]);
    expect(result.records[0].reason).toMatch(/conflicting duplicate/i);
    expect(result.issues).toContain(
      'Conflicting duplicate iteration_id "iter-conflict"; no joins to that ID are trusted.',
    );
  });

  it("rejects malformed payload fields without string coercion or network work", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const malformedRows: unknown = {
        iterations: [
          null,
          { iteration_id: 41, seed: { topic: "Numeric id" } },
          iteration("iter-number-topic", 42),
          iteration("unknown-id", "Would otherwise join"),
        ],
      };
      const result = buildThesisFamilies(
        [
          cluster("cl-number-topic", ["iter-number-topic"]),
          cluster("cl-unknown", ["unknown-id"]),
          {
            ...cluster("cl-member-shape", ["iter-number-topic"]),
            members: ["iter-number-topic", 7] as unknown as string[],
          },
        ],
        malformedRows,
      );

      expect(result.records.every((record) => record.association === "individual"))
        .toBe(true);
      expect(result.records[0].topics).not.toContain("42");
      expect(result.issues).toContain("Ignored 1 malformed iteration row.");
      expect(result.issues).toContain("Ignored 2 rows with an invalid iteration_id.");
      expect(result.issues).toContain(
        'Iteration "iter-number-topic" has no valid seed.topic; joins to it are not trusted.',
      );
      expect(fetchSpy).not.toHaveBeenCalled();

      const badEnvelope = buildThesisFamilies(
        [cluster("cl-envelope", ["iter-a"])],
        { iterations: "not-an-array" },
      );
      expect(badEnvelope.records[0].association).toBe("individual");
      expect(badEnvelope.issues).toEqual([
        "Iteration rows payload is malformed; expected an array or an iterations array.",
      ]);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("matchesFamilyRecord", () => {
  it("matches IDs, topics, hypotheses, and recorded paper text case-insensitively", () => {
    const source = {
      ...iteration("iter-search", "Consensus Voting", "Directional Drift Claim"),
      retrieval: {
        neighbors: [
          {
            title: "Graph Voting Paper",
            chunk_text: "A rare abstract phrase about diffusion.",
          },
          { title: 99, chunk_text: null },
          "malformed neighbor",
        ],
      },
      evidence: { summary: "Evidence stays available for detail" },
      critique: { rationale: "Recorded critique" },
    };
    const result = buildThesisFamilies(
      [cluster("CL-Search", ["iter-search"])],
      [source],
    );
    const record = result.records[0];

    expect(record.iterations[0]).toMatchObject({
      id: "iter-search",
      topic: "Consensus Voting",
      hypothesis: "Directional Drift Claim",
      paperText: ["Graph Voting Paper", "A rare abstract phrase about diffusion."],
      evidenceText: ["Evidence stays available for detail", "Recorded critique"],
    });
    expect(record.iterations[0].source).toBe(source);
    expect(matchesFamilyRecord(record, "cl-search")).toBe(true);
    expect(matchesFamilyRecord(record, "CONSENSUS VOTING")).toBe(true);
    expect(matchesFamilyRecord(record, "directional drift")).toBe(true);
    expect(matchesFamilyRecord(record, "graph voting paper")).toBe(true);
    expect(matchesFamilyRecord(record, "RARE ABSTRACT PHRASE")).toBe(true);
    expect(matchesFamilyRecord(record, "Evidence stays available")).toBe(false);
    expect(matchesFamilyRecord(record, "")).toBe(true);
    expect(matchesFamilyRecord(record, "not present")).toBe(false);
  });
});


describe("source cluster identity faults", () => {
  it("isolates duplicate and missing IDs with stable unique presentation keys, preserving every raw row", () => {
    const open = cluster("cl-same", ["iter-open"]);
    const killed = cluster("cl-same", ["iter-killed"], { status: "killed", kill_reason: { code: "negative", detail: "Keep this negative" } });
    const noId = { ...cluster("cl-temp", ["iter-open"]), cluster_id: undefined } as unknown as LadderCluster;
    const input = [open, killed, noId, { ...noId }];
    const rows = [iteration("iter-open", "Shared"), iteration("iter-killed", "Shared")];
    const result = buildThesisFamilies(input, rows);
    expect(result.records).toHaveLength(4);
    expect(new Set(result.records.map((r) => r.key)).size).toBe(4);
    expect(new Set(result.families.map((f) => f.id)).size).toBe(4);
    expect(result.records.every((r) => r.association === "individual")).toBe(true);
    expect(result.issues.join(" ")).toMatch(/duplicate.*cluster|cluster.*duplicate/i);
    expect(result.issues.join(" ")).toMatch(/missing.*cluster|cluster.*missing/i);
    for (const raw of input) expect(result.records.filter((r) => r.cluster === raw)).toHaveLength(1);
    const reverse = buildThesisFamilies([...input].reverse(), [...rows].reverse());
    expect(result.records.map((r) => r.key).sort()).toEqual(reverse.records.map((r) => r.key).sort());
    expect(result.records.filter((r) => r.cluster.cluster_id === "cl-same").every((r) => r.id === "cl-same")).toBe(true);
  });
});


it("does not transfer identity between idless local fixture rows after reordering", () => {
  const a = { ...cluster("unused", ["iter-a"]), cluster_id: undefined, stem: "Same display stem" } as unknown as LadderCluster;
  const b = { ...cluster("unused", ["iter-b"]), cluster_id: undefined, stem: "Same display stem" } as unknown as LadderCluster;
  const rows = [iteration("iter-a", "A", "Claim A"), iteration("iter-b", "B", "Claim B")];
  const before = buildThesisFamilies([a, b], rows);
  const after = buildThesisFamilies([b, a], rows);
  for (const record of before.records) {
    expect(after.records.find((next) => next.key === record.key)?.cluster).toBe(record.cluster);
  }
});
