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
