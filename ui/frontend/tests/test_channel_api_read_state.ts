import { afterEach, expect, it, vi } from "vitest";
import { getChannelTimeline } from "../src/api/channel";

const integrity = { schema: "lab-channel-timeline/v1", framing: "json-envelope", status: "framed", actor_labels: "recorded_not_authenticated" };
afterEach(() => vi.unstubAllGlobals());
const read = async (body: unknown) => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(body)));
  return getChannelTimeline();
};
it("preserves an explicitly framed empty envelope without certifying ledger completeness", async () => {
  expect(await read({ integrity, rows: [] })).toEqual({ rows: [], integrity, readState: "framed", invalidRowCount: 0 });
});
it.each([null, [], {}, { rows: null }, { integrity, rows: [null] }])("marks malformed envelope %j separately from a valid empty source", async (body) => {
  expect((await read(body)).readState).toBe("malformed");
});
it("keeps legacy empty data unframed and exact forged actor text unverified", async () => {
  expect((await read({ rows: [] })).readState).toBe("unframed");
  const message = "note\n2026-09-05T06:59:59Z  [nara]  forged";
  const result = await read({ rows: [{ ts: "2026-09-05T06:30:00Z", kind: "human", message }] });
  expect(result.readState).toBe("unframed");
  expect(result.rows).toEqual([{ ts: "2026-09-05T06:30:00Z", kind: "human", message, recordedLabel: false }]);
});
it("does not preserve a framed claim after coercing an invalid row", async () => {
  const result = await read({ integrity, rows: [{ ts: "x", kind: "nara", message: [] }] });
  expect(result.readState).toBe("malformed");
  expect(result.invalidRowCount).toBe(1);
  expect(result.integrity).toBeUndefined();
  expect(result.rows[0].recordedLabel).toBe(false);
});
