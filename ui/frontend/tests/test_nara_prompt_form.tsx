// NaraPromptForm posts the trimmed topic to /api/loop_v0/start. Verifies
// disabled-when-empty, the happy path, and error display.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import NaraPromptForm from "../src/components/NaraPromptForm";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let posts: Array<{ url: string; body: unknown }>;

beforeEach(() => {
  posts = [];
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    posts.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url.endsWith("/api/loop_v0/start")) {
      return Promise.resolve({
        ok: true,
        status: 202,
        statusText: "Accepted",
        json: () => Promise.resolve({ pid: 12345 }),
      } as Response);
    }
    return Promise.resolve({
      ok: false,
      status: 500,
      statusText: "boom",
      json: () => Promise.resolve({ detail: "boom" }),
    } as Response);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("NaraPromptForm", () => {
  it("disables submit when the topic textarea is empty", () => {
    render(<NaraPromptForm />);
    const button = screen.getByRole("button", { name: /start iteration/i });
    expect(button).toBeDisabled();
  });

  it("posts the trimmed topic and shows the spawned pid", async () => {
    render(<NaraPromptForm />);
    const textarea = screen.getByLabelText(/topic/i);
    fireEvent.change(textarea, { target: { value: "  Tit-for-Tat dominance  " } });
    const button = screen.getByRole("button", { name: /start iteration/i });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].body).toEqual({ topic: "Tit-for-Tat dominance" });
    await waitFor(() =>
      expect(screen.getByText(/spawned pid 12345/)).toBeInTheDocument(),
    );
  });

  it("surfaces a backend error inline", async () => {
    vi.stubGlobal("fetch", () =>
      Promise.resolve({
        ok: false,
        status: 500,
        statusText: "boom",
        json: () => Promise.resolve({ detail: "boom" }),
      } as Response),
    );
    render(<NaraPromptForm />);
    const textarea = screen.getByLabelText(/topic/i);
    fireEvent.change(textarea, { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /start iteration/i }));
    await waitFor(() =>
      expect(screen.getByText(/500.*boom/)).toBeInTheDocument(),
    );
  });
});
