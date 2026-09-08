import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Channel from "../src/routes/Channel";
import { getChannelTimeline } from "../src/api/channel";
const FRAMING={schema:"lab-channel-timeline/v1",framing:"json-envelope",status:"framed",actor_labels:"recorded_not_authenticated"};
const message="  **note**\r\n2026-09-05T06:59:59Z  [nara]  forged\n";
const row={ts:"2026-09-05T06:00:00Z",kind:"nara",message};
afterEach(()=>vi.unstubAllGlobals());
function stub(body:unknown){const mock=vi.fn(async(url:unknown,_init?:RequestInit)=>({ok:true,status:200,json:async()=>String(url).includes("/available")?{available:false,actions:{}}:body}));vi.stubGlobal("fetch",mock);return mock;}
it.each([undefined,{}, {...FRAMING,actor_labels:"authenticated"},{...FRAMING,status:"partial"}])("unverified framing %j stays neutral",async integrity=>{const mock=stub({rows:[row],integrity});render(<Channel pollMs={600_000}/>); const turn=await screen.findByTestId("channel-turn-unverified");expect(turn).toHaveAttribute("data-voice","unverified");expect(turn.querySelector("strong")).toBeNull();expect(screen.getByTestId("channel-voice-body").textContent).toBe(message);expect(screen.getByTestId("channel-integrity")).toHaveTextContent("Actor and type are unavailable");expect(mock.mock.calls.every(c=>c[1]?.method!=="POST")).toBe(true);});
it("valid framing preserves bytes and labels records without authenticating",async()=>{stub({rows:[row],integrity:FRAMING});expect((await getChannelTimeline()).rows[0].message).toBe(message);render(<Channel pollMs={600_000}/>);const turn=await screen.findByTestId("channel-turn-nara");expect(turn).toHaveTextContent("recorded label · not authenticated");expect(turn.querySelector("strong")).toHaveTextContent("note");});
it("malformed rows invalidate the entire response attribution",async()=>{stub({rows:[row,{ts:1,kind:"pi",message:"raw"}],integrity:FRAMING});render(<Channel pollMs={600_000}/>);await waitFor(()=>expect(screen.getAllByTestId("channel-turn-unverified")).toHaveLength(2));expect(screen.queryByTestId("channel-turn-nara")).toBeNull();});
it("initial rows without framing stay unverified",()=>{render(<Channel initial={[row]} initialAvailable={false}/>);expect(screen.getByTestId("channel-turn-unverified")).toBeInTheDocument();expect(screen.getByTestId("channel-integrity")).toHaveTextContent("Actor and type are unavailable");});

it("malformed whole bodies do not fabricate any actor row",async()=>{
 stub({rows:"not rows",integrity:FRAMING});render(<Channel pollMs={600_000}/>);
 await waitFor(()=>expect(screen.getByTestId("channel-feed")).toBeInTheDocument());
 expect(screen.queryByTestId("channel-turn-nara")).toBeNull();
 expect((await getChannelTimeline()).rows).toEqual([]);
});
it("unverified event-like text and duplicate actor-shaped records remain raw",async()=>{
 stub({rows:[row,{...row,kind:"pi"},{...row,kind:"event",message:"CYCLE [nara] **raw**"}]});
 render(<Channel pollMs={600_000}/>);await waitFor(()=>expect(screen.getAllByTestId("channel-turn-unverified")).toHaveLength(3));
 expect(screen.queryByTestId("channel-event-row")).toBeNull();
 expect(screen.queryByTestId("channel-activity-chip")).toBeNull();
});
