import { it, expect } from "vitest";
import { buildGraph, fitCamera, zoomCamera } from "./graph";
import type { KnowledgeMap } from "./types";
it("uses every actual node and drops dangling edges without inventing dependencies", () => {
  const data = {
    documents: [{ id: "doc", name: "Document" }],
    topics: Array.from({ length: 32 }, (_, i) => ({
      id: `t${i}`,
      label: `Topic ${i}`,
      count: 5,
      documents: [{ id: "doc", count: 1 }],
    })),
    edges: [
      { source: "t0", target: "t1", kind: "similarity", similarity: 0.8 },
      { source: "t0", target: "missing", kind: "similarity", similarity: 0.8 },
    ],
    questions: [],
  } as unknown as KnowledgeMap;
  const g = buildGraph(data);
  expect(g.nodes).toHaveLength(33);
  expect(g.edges).toHaveLength(33);
  const again = buildGraph(data);
  expect(g.nodes.map((n) => [n.x, n.y])).toEqual(
    again.nodes.map((n) => [n.x, n.y]),
  );
  for (const width of [320, 390, 1024, 1440, 1920]) {
    const c = fitCamera(g.nodes, width, 560);
    for (const n of g.nodes) {
      expect((n.x - n.radius) * c.scale + c.x).toBeGreaterThanOrEqual(0);
      expect((n.x + n.radius) * c.scale + c.x).toBeLessThanOrEqual(width);
      expect((n.y - n.radius) * c.scale + c.y).toBeGreaterThanOrEqual(0);
      expect((n.y + n.radius) * c.scale + c.y).toBeLessThanOrEqual(560);
    }
  }
});
it("zooms around the cursor and clamps scale", () => {
  const c = { x: 45, y: 30, scale: 1 },
    z = zoomCamera(c, 2, 200, 150);
  expect((200 - z.x) / z.scale).toBe((200 - c.x) / c.scale);
  expect((150 - z.y) / z.scale).toBe((150 - c.y) / c.scale);
  expect(zoomCamera(c, 100, 0, 0).scale).toBe(4);
  expect(zoomCamera(c, 0.0001, 0, 0).scale).toBe(0.15);
});

it("places dense labels inside the viewport without intersections at different zooms", async () => {
  const { placeGraphLabels } = await import("./graph");
  const nodes = Array.from({ length: 54 }, (_, i) => ({
    id: String(i), sourceId: String(i), kind: "topic" as const,
    label: "Длинная подпись области " + i, radius: 9,
    x: (i % 9) * 60, y: Math.floor(i / 9) * 60,
  }));
  for (const scale of [0.5, 1, 2]) {
    const labels = [...placeGraphLabels(nodes, { x: 50, y: 50, scale }, 900, 600,
      ["0"], (text) => text.length * 6).values()];
    expect(labels.length).toBeGreaterThan(3);
    for (const [i, a] of labels.entries()) {
      expect(a.x).toBeGreaterThanOrEqual(8);
      expect(a.x + a.width).toBeLessThanOrEqual(892);
      expect(a.y + a.height).toBeLessThanOrEqual(536);
      for (const b of labels.slice(i + 1)) {
        expect(a.x < b.x + b.width && a.x + a.width > b.x &&
          a.y < b.y + b.height && a.y + a.height > b.y).toBe(false);
      }
    }
  }
});

it("uses actual document names instead of service-only topic labels", () => {
  const data = { documents: [{ id: "d", name: "Смета.xlsx" }],
    topics: [{ id: "t", label: "none · проверено · сохраненное", count: 1, documents: [{ id: "d", count: 1 }] }],
    edges: [], questions: [] } as unknown as KnowledgeMap;
  expect(buildGraph(data).nodes.find(n => n.kind === "topic")?.label).toBe("Смета");
  expect(data.topics[0].label).toBe("none · проверено · сохраненное");
});
