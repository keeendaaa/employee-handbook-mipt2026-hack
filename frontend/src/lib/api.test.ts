import { describe, it, expect } from "vitest";
import { readEvents, ApiError } from "./api";
function bytes(parts: Uint8Array[]) {
  return new ReadableStream<Uint8Array>({
    start(c) {
      parts.forEach((p) => c.enqueue(p));
      c.close();
    },
  });
}
describe("SSE framing", () => {
  it("preserves Cyrillic split across byte chunks, multiple events and keepalives", async () => {
    const encoded = new TextEncoder().encode(
      ': ping\r\n\r\ndata: {"type":"stage","text":"Привет"}\r\n\r\ndata: {"type":"done"}\r\n\r\n',
    );
    const events: unknown[] = [];
    await readEvents(
      bytes(Array.from(encoded, (b) => new Uint8Array([b]))),
      (e) => events.push(e),
    );
    expect(events).toEqual([
      { type: "stage", text: "Привет" },
      { type: "done" },
    ]);
  });
  it("rejects truncated events and propagates an explicit technical failure", async () => {
    const encoder = new TextEncoder();
    await expect(
      readEvents(bytes([encoder.encode('data: {"type":')]), () => {}),
    ).rejects.toBeInstanceOf(ApiError);
    await expect(
      readEvents(bytes([encoder.encode('data: {"type":"error"}\n\n')]), () => {
        throw new ApiError("server failed", 502);
      }),
    ).rejects.toThrow("server failed");
  });
});
