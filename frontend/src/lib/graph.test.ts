import { it, expect } from "vitest";
import { buildGraph, fitCamera, zoomCamera, projectGraph, graphBranch, graphLabelLines } from "./graph";
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

const projectionFixture = () => {
  const nodes = ["a", "b", "c", "d", "e", "isolated", "t1", "t2", "t3"].map((id) => ({
    id, sourceId: id, label: id, kind: id.startsWith("t") ? "topic" as const : "document" as const, radius: 9, x: 0, y: 0,
  }));
  const edges = [["a", "t1"], ["b", "t1"], ["t1", "t2"], ["t2", "t3"], ["t3", "t1"], ["c", "t3"], ["d", "t2"], ["d", "e"]].map(([source, target]) => ({ source, target, kind: source.startsWith("t") && target.startsWith("t") ? "similarity" : "membership" }));
  return { nodes, edges };
};
it("connects documents through shared topics, even when other topics are adjacent", () => {
  const g = projectGraph(projectionFixture(), ["document"]);
  expect(g.nodes).toHaveLength(6);
  expect(g.edges).toHaveLength(2);
  expect(g.edges.filter((e) => e.kind === "projected")).toEqual([
    { source: "a", target: "b", kind: "projected", via: ["t1"] },
  ]);
  expect(projectGraph(projectionFixture(), ["document", "topic"]).edges).toHaveLength(8);
});
it("isolates the selected branch and removes even cross-links between its neighbors", () => {
  const g = projectGraph(projectionFixture(), ["document"]), branch = graphBranch(g, "a");
  expect(branch.nodes.map((n) => n.id).sort()).toEqual(["a", "b"]);
  expect(branch.edges).toHaveLength(1);
  expect(branch.edges.every((e) => e.source === "a" || e.target === "a")).toBe(true);
  expect(graphBranch(g, "isolated").nodes).toHaveLength(1);
  expect(graphBranch(g, null)).toBe(g);
});
it("wraps full document titles without replacing their content with ellipses", () => {
  const title = "Регламент поиска и подбора персонала и согласования заявок подразделений.pdf";
  const lines = graphLabelLines(title);
  expect(lines.length).toBeGreaterThan(1);
  expect(lines.join(" ")).toBe(title.replace(/\.pdf$/, ""));
  expect(lines.every((line) => line.length <= 30)).toBe(true);
});
