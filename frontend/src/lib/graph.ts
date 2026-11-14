import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
} from "d3-force";
import type { SimulationLinkDatum, SimulationNodeDatum } from "d3-force";
import type { KnowledgeMap } from "./types";
export type NodeKind = "document" | "topic" | "question";
export interface GraphNode extends SimulationNodeDatum {
  id: string;
  sourceId: string;
  label: string;
  kind: NodeKind;
  radius: number;
  x: number;
  y: number;
}
export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
  /** Hidden topic IDs that justify a projected semantic edge. */
  via?: string[];
}
export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
/** Contract only hidden topics, never a visible document or question. */
export function projectGraph(graph: Graph, kinds: NodeKind[], topicDepth = Infinity): Graph {
  const nodes = graph.nodes.filter((n) => kinds.includes(n.kind)),
    visible = new Set(nodes.map((n) => n.id)),
    topics = new Set(graph.nodes.filter((n) => n.kind === "topic").map((n) => n.id)),
    adjacency = new Map<string, string[]>(),
    edges = new Map<string, GraphEdge>();
  const key = (a: string, b: string) => JSON.stringify([a, b].sort());
  for (const edge of graph.edges) {
    adjacency.set(edge.source, [...(adjacency.get(edge.source) || []), edge.target]);
    adjacency.set(edge.target, [...(adjacency.get(edge.target) || []), edge.source]);
    if (visible.has(edge.source) && visible.has(edge.target))
      edges.set(key(edge.source, edge.target), edge);
  }
  if (!kinds.includes("topic")) {
    for (const origin of nodes) {
      const queue = (adjacency.get(origin.id) || [])
        .filter((id) => topics.has(id))
        .map((id) => [id]);
      const visited = new Set<string>();
      for (let i = 0; i < queue.length; i++) {
        const via = queue[i], current = via[via.length - 1];
        if (visited.has(current) || via.length > topicDepth) continue;
        visited.add(current);
        for (const next of adjacency.get(current) || []) {
          if (visible.has(next) && next !== origin.id) {
            const id = key(origin.id, next), old = edges.get(id);
            if (!old || (old.via && old.via.length > via.length))
              edges.set(id, { source: origin.id, target: next, kind: "projected", via });
          } else if (topics.has(next) && !visited.has(next) && via.length < topicDepth)
            queue.push([...via, next]);
        }
      }
    }
  }
  return { nodes, edges: [...edges.values()] };
}
/** A branch contains the chosen node and its incident edges only. */
export function graphBranch(graph: Graph, id: string | null): Graph {
  if (!id || !graph.nodes.some((n) => n.id === id)) return graph;
  const edges = graph.edges.filter((e) => e.source === id || e.target === id),
    ids = new Set([id, ...edges.flatMap((e) => [e.source, e.target])]);
  return { nodes: graph.nodes.filter((n) => ids.has(n.id)), edges };
}
export function graphLabelLines(label: string, length = 30): string[] {
  const words = label.replace(/\.(pdf|docx|xlsx)$/i, "").replace(/_/g, " ").split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  for (const word of words) {
    for (let start = 0; start < word.length; start += length) {
      const part = word.slice(start, start + length), last = lines.length - 1;
      if (last >= 0 && lines[last].length + part.length + 1 <= length)
        lines[last] += " " + part;
      else lines.push(part);
    }
  }
  return lines.length ? lines : [label];
}
export interface Camera {
  x: number;
  y: number;
  scale: number;
}
export function buildGraph(data: KnowledgeMap) {
  const nodes: GraphNode[] = [
    ...data.documents.map((d) => ({
      id: `document:${d.id}`,
      sourceId: d.id,
      label: d.name,
      kind: "document" as const,
      radius: 9,
      x: 0,
      y: 0,
    })),
    ...data.topics.map((t) => ({
      id: `topic:${t.id}`,
      sourceId: t.id,
      label: t.label,
      kind: "topic" as const,
      radius: 5 + Math.min(5, Math.sqrt(t.count)),
      x: 0,
      y: 0,
    })),
    ...data.questions.map((q) => ({
      id: `question:${q.id}`,
      sourceId: q.id,
      label: q.question,
      kind: "question" as const,
      radius: 7,
      x: 0,
      y: 0,
    })),
  ];
  const ids = new Set(nodes.map((n) => n.id));
  const edges: GraphEdge[] = [
    ...data.topics.flatMap((t) =>
      t.documents.map((d) => ({
        source: `topic:${t.id}`,
        target: `document:${d.id}`,
        kind: "membership",
      })),
    ),
    ...data.edges.map((e) => ({
      source: `topic:${e.source}`,
      target: `topic:${e.target}`,
      kind: e.kind,
    })),
    ...data.questions.flatMap((q) =>
      q.related_topics.map((t) => ({
        source: `question:${q.id}`,
        target: `topic:${t.id}`,
        kind: "question",
      })),
    ),
  ].filter(
    (e) => ids.has(e.source) && ids.has(e.target) && e.source !== e.target,
  );
  // Stop before ticking: no background simulation, stable positions for keyboard navigation.
  for (let i = 0; i < nodes.length; i++) {
    nodes[i].x = Math.cos(i * 2.399963) * Math.sqrt(i + 1) * 65;
    nodes[i].y = Math.sin(i * 2.399963) * Math.sqrt(i + 1) * 65;
  }
  const simulation = forceSimulation(nodes)
    .stop()
    .force(
      "link",
      forceLink<GraphNode, SimulationLinkDatum<GraphNode>>(
        edges.map((e) => ({ ...e })),
      )
        .id((n) => n.id)
        .distance(220)
        .strength(0.4),
    )
    .force("charge", forceManyBody().strength(-420))
    .force("center", forceCenter())
    .force(
      "collision",
      forceCollide<GraphNode>().radius((n) => n.kind === "topic" ? 55 : 120),
    );
  simulation.tick(240);
  simulation.stop();
  return { nodes, edges };
}
export function fitCamera(
  nodes: GraphNode[],
  width: number,
  height: number,
): Camera {
  if (!nodes.length) return { x: width / 2, y: height / 2, scale: 1 };
  const minX = Math.min(
      ...nodes.map(
        (n) => n.x - Math.max(n.radius, Math.min(108, n.label.length * 3.6)),
      ),
    ),
    maxX = Math.max(
      ...nodes.map(
        (n) => n.x + Math.max(n.radius, Math.min(108, n.label.length * 3.6)),
      ),
    );
  const minY = Math.min(...nodes.map((n) => n.y - n.radius)),
    maxY = Math.max(...nodes.map((n) => n.y + n.radius + graphLabelLines(n.label).length * 18 + 12));
  const scale = Math.max(
    0.15,
    Math.min(
      1,
      (width - 96) / Math.max(1, maxX - minX),
      (height - 120) / Math.max(1, maxY - minY),
    ),
  );
  return {
    x: width / 2 - ((minX + maxX) / 2) * scale,
    y: height / 2 - ((minY + maxY) / 2) * scale,
    scale,
  };
}
export function zoomCamera(
  camera: Camera,
  factor: number,
  x: number,
  y: number,
): Camera {
  const scale = Math.max(0.15, Math.min(4, camera.scale * factor)),
    ratio = scale / camera.scale;
  return {
    scale,
    x: x - (x - camera.x) * ratio,
    y: y - (y - camera.y) * ratio,
  };
}
