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
}
export interface Camera {
  x: number;
  y: number;
  scale: number;
}
const genericTopicWords = new Set("none null поле поля проверено сохраненное сохранённое заголовок контекст непустой непустое актуальность годы года структура прочие этап".split(" "));
function topicLabel(topic: KnowledgeMap["topics"][number], documents: KnowledgeMap["documents"]) {
  const words = topic.label.split(" · ").filter(word => !genericTopicWords.has(word.toLocaleLowerCase()));
  if (words.length) return words.join(" · ");
  const document = documents.find(d => d.id === topic.documents[0]?.id);
  return document ? document.name.replace(/\.(pdf|docx|xlsx)$/i, "").replaceAll("_", " ") : topic.label;
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
      label: topicLabel(t, data.documents),
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
        .distance(135)
        .strength(0.4),
    )
    .force("charge", forceManyBody().strength(-240))
    .force("center", forceCenter())
    .force(
      "collision",
      forceCollide<GraphNode>().radius((n) => n.radius + 30),
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
    maxY = Math.max(...nodes.map((n) => n.y + n.radius + 24));
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

export interface GraphLabel {
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
}
/** Labels use screen coordinates so zoom never shrinks text into unreadable dots. */
export function placeGraphLabels(
  nodes: GraphNode[],
  camera: Camera,
  width: number,
  height: number,
  priorityIds: string[],
  measure: (text: string) => number,
): Map<string, GraphLabel> {
  const labels = new Map<string, GraphLabel>();
  const points = nodes.map((node) => ({
    node,
    x: camera.x + node.x * camera.scale,
    y: camera.y + node.y * camera.scale,
    radius: node.radius * camera.scale + 5,
  }));
  const priority = new Map(priorityIds.map((id, i) => [id, i]));
  const ordered = points.slice().sort((a, b) =>
    (priority.get(a.node.id) ?? Infinity) - (priority.get(b.node.id) ?? Infinity) ||
    Number(b.node.kind === "document") - Number(a.node.kind === "document"),
  );
  const overlaps = (a: GraphLabel, b: GraphLabel) =>
    a.x < b.x + b.width && a.x + a.width > b.x &&
    a.y < b.y + b.height && a.y + a.height > b.y;
  for (const point of ordered) {
    let text = point.node.label;
    const maxWidth = width < 600 ? Math.min(120, (width - 32) * 0.4) : 180;
    if (measure(text) > maxWidth) {
      while (text.length && measure(text + "…") > maxWidth) text = text.slice(0, -1);
      text += "…";
    }
    // Reserve a margin for font loading, glyph bearings and the white text outline.
    const w = measure(text) + 14, h = 23;
    const candidates = [
      { x: point.x - w / 2, y: point.y + point.radius },
      { x: point.x - w / 2, y: point.y - point.radius - h },
      { x: point.x + point.radius, y: point.y - h / 2 },
      { x: point.x - point.radius - w, y: point.y - h / 2 },
    ];
    for (const position of candidates) {
      const box = { ...position, width: w, height: h, text };
      if (box.x < 8 || box.y < 8 || box.x + w > width - 8 || box.y + h > height - 64) continue;
      if ([...labels.values()].some((other) => overlaps(box, other))) continue;
      if (points.some((p) => overlaps(box, {
        text: "", x: p.x - p.radius, y: p.y - p.radius,
        width: p.radius * 2, height: p.radius * 2,
      }))) continue;
      labels.set(point.node.id, box); break;
    }
  }
  return labels;
}
