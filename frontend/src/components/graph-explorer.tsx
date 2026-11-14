import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUpRight,
  Maximize2,
  Minimize2,
  Scan,
  Search,
  SlidersHorizontal,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { fragmentTitle } from "../lib/document";
import { api } from "../lib/api";
import {
  buildGraph,
  fitCamera,
  zoomCamera,
  projectGraph,
  graphBranch,
  graphLabelLines,
  placeGraphLabels,
} from "../lib/graph";
import type { Camera, GraphNode, NodeKind } from "../lib/graph";
import type { Fragment, KnowledgeMap } from "../lib/types";
import type { DocumentSelection } from "./document-reader";
import {
  Badge,
  Button,
  Empty,
  ErrorNotice,
  Loading,
  Modal,
} from "./primitives";
const names: Record<NodeKind, string> = {
  document: "Документы",
  topic: "Темы",
  question: "Вопросы",
};

export function GraphExplorer({
  data,
  onSource,
  onDocument,
}: {
  data: KnowledgeMap;
  onSource: (id: string) => void;
  onDocument: (doc: DocumentSelection) => void;
}) {
  const graph = useMemo(() => buildGraph(data), [data]);
  const [nodes, setNodes] = useState(graph.nodes),
    [selected, setSelected] = useState<string | null>(null),
    [hover, setHover] = useState<string | null>(null),
    [full, setFull] = useState(false),
    [query, setQuery] = useState(""),
    [filters, setFilters] = useState(false),
    [kinds, setKinds] = useState<NodeKind[]>(["document", "topic", "question"]);
  const [camera, setCamera] = useState<Camera>({ x: 0, y: 0, scale: 1 }),
    [size, setSize] = useState({ width: 800, height: 560 }),
    [fragments, setFragments] = useState<Fragment[] | null>(null),
    [error, setError] = useState("");
  const viewport = useRef<HTMLDivElement | null>(null),
    drag = useRef<{
      id: string | null;
      px: number;
      py: number;
      x: number;
      y: number;
      moved: boolean;
    } | null>(null);
  useEffect(() => {
    setNodes(graph.nodes);
    setSelected(null);
  }, [graph]);
  useEffect(() => {
    if (!viewport.current) return;
    const observer = new ResizeObserver(([entry]) =>
      setSize({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      }),
    );
    observer.observe(viewport.current);
    return () => observer.disconnect();
  }, [full]);

  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const block = (e: WheelEvent) => {
      if ((e.target as Element).closest(".obsidian-graph")) e.preventDefault();
    };
    el.addEventListener("wheel", block, { passive: false });
    return () => el.removeEventListener("wheel", block);
  }, [full]);
  const projected = useMemo(
    () => projectGraph({ nodes, edges: graph.edges }, kinds),
    [nodes, graph, kinds],
  );
  const branch = useMemo(
    () => graphBranch(projected, selected),
    [projected, selected],
  );
  const visible = branch.nodes,
    edges = branch.edges,
    byId = new Map(nodes.map((n) => [n.id, n])),
    active = byId.get(selected || ""),
    focus = hover || selected,
    neighbors = new Set(
      focus
        ? [focus, ...edges
            .filter((e) => e.source === focus || e.target === focus)
            .flatMap((e) => [e.source, e.target])]
        : [],
    ),
    matches = projected.nodes.filter((n) =>
      n.label.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
    ),
    related = branch.nodes.filter((n) => n.id !== selected),
    readableFragments = fragments?.filter((f) => fragmentTitle(f.preview));
  // Refit on navigation/filter changes, never while the user drags a node.
  useEffect(() => {
    // Stack a focused branch on narrow canvases so full titles remain legible.
    if (selected && size.width < 600) {
      const ordered = [...visible].sort(
        (a, b) => Number(b.id === selected) - Number(a.id === selected),
      );
      const arranged = ordered.map((n, i) => ({
        ...n,
        x: i === 0 ? 0 : (i % 2 ? 1 : -1) * Math.min(48, size.width * 0.14),
        y: i * 160,
      }));
      const positions = new Map(arranged.map((n) => [n.id, n]));
      setNodes((old) => old.map((n) => positions.get(n.id) || n));
      const fitted = fitCamera(arranged, size.width, size.height);
      // Large branches remain pannable rather than squeezing titles together.
      setCamera(fitted.scale < 0.65
        ? { x: size.width / 2, y: 48, scale: 0.75 }
        : fitted);
    } else setCamera(fitCamera(visible, size.width, size.height));
  }, [graph, size, selected, kinds]);
  const measureLabel = useMemo(() => {
    const context = document.createElement("canvas").getContext("2d");
    if (context) context.font = '12px "Inter Variable", Arial, sans-serif';
    return (text: string) => context?.measureText(text).width ?? text.length * 7;
  }, []);
  const labels = placeGraphLabels(visible, camera, size.width, size.height,
    [...(focus ? [focus] : []), ...(query ? matches.map((n) => n.id) : [])], measureLabel);
  const shownEdges = focus
    ? edges.filter((e) => e.source === focus || e.target === focus)
    : edges.filter((e) => !kinds.includes("topic") || e.kind === "membership");
  const question =
    active?.kind === "question"
      ? data.questions.find((q) => q.id === active.sourceId)
      : null;
  useEffect(() => {
    if (!active || active.kind === "question") return;
    const controller = new AbortController();
    setFragments(null);
    setError("");
    const topics =
      active.kind === "topic"
        ? [active.sourceId]
        : data.topics
            .filter((t) => t.documents.some((d) => d.id === active.sourceId))
            .map((t) => t.id);
    Promise.all(
      topics.map((id) =>
        api.topic(id, data.corpus_revision, controller.signal),
      ),
    )
      .then((rows) => {
        const seen = new Set<string>();
        setFragments(
          rows
            .flatMap((r) => r.fragments)
            .filter(
              (f) =>
                (active.kind !== "document" ||
                  f.document_name === active.label) &&
                !seen.has(f.source_id) &&
                !!seen.add(f.source_id),
            ),
        );
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [selected, data]);
  function select(n: GraphNode) {
    setSelected(n.id);
    setHover(null);
  }
  function zoom(factor: number) {
    setCamera((c) => zoomCamera(c, factor, size.width / 2, size.height / 2));
  }
  function openSource(id: string) {
    setFull(false);
    onSource(id);
  }
  const canvas = (
    <div className="graph-explorer" data-fullscreen={full}>
      <div className="graph-controls">
        <label className="graph-search">
          <Search size={18} />
          <input
            aria-label="Найти узел на карте"
            placeholder="Найти документ или тему…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query && (
            <button
              className="sm-icon-button"
              aria-label="Очистить поиск карты"
              onClick={() => setQuery("")}
            >
              <X size={16} />
            </button>
          )}
        </label>
        <Button
          aria-label="Фильтры карты"
          aria-expanded={filters}
          onClick={() => setFilters((v) => !v)}
        >
          <SlidersHorizontal size={18} />
        </Button>
        <Button
          aria-label={
            full ? "Свернуть карту" : "Развернуть карту на весь экран"
          }
          onClick={() => setFull((v) => !v)}
        >
          {full ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
        </Button>
      </div>
      {active && <div className="graph-branch-bar">
        <Button variant="subtle" onClick={() => setSelected(null)}>← Вся карта</Button>
        <p>Ветка: <strong>{active.label}</strong><span className="meta"> · Связей: {related.length}</span></p>
      </div>}
      {filters && (
        <div className="graph-filters">
          {(Object.keys(names) as NodeKind[]).map((kind) => (
            <label className="check-label" key={kind}>
              <input
                type="checkbox"
                checked={kinds.includes(kind)}
                onChange={() => {
                  setKinds((old) =>
                    old.includes(kind)
                      ? old.filter((k) => k !== kind)
                      : [...old, kind],
                  );
                  setSelected(null);
                }}
              />
              {names[kind]}
            </label>
          ))}
        </div>
      )}
      {query && (
        <div
          className="graph-search-results"
          aria-label="Результаты поиска карты"
        >
          {matches.length ? (
            matches.map((n) => (
              <button
                key={n.id}
                onClick={() => {
                  select(n);
                  setQuery("");
                }}
              >
                <span className={`graph-dot ${n.kind}`} />
                <span>
                  {n.label}
                  <small>{names[n.kind]}</small>
                </span>
                <ArrowUpRight size={16} />
              </button>
            ))
          ) : (
            <p>Ничего не найдено</p>
          )}
        </div>
      )}
      <div className="graph-workspace" data-inspecting={!!active}>
      <div className="graph-canvas">
      <div className="graph-viewport" ref={viewport}>
        <svg
          className="obsidian-graph"
          role="group"
          aria-label="Карта документов, тем и вопросов"
          tabIndex={0}
          viewBox={`0 0 ${size.width} ${size.height}`}
          onKeyDown={(e) => {
            if (e.target !== e.currentTarget) return;
            if (
              [
                "+",
                "=",
                "-",
                "0",
                "ArrowLeft",
                "ArrowRight",
                "ArrowUp",
                "ArrowDown",
              ].includes(e.key)
            ) {
              e.preventDefault();
              if (e.key === "0")
                setCamera(fitCamera(visible, size.width, size.height));
              else if (["+", "="].includes(e.key)) zoom(1.2);
              else if (e.key === "-") zoom(1 / 1.2);
              else {
                const d = e.shiftKey ? 100 : 30;
                setCamera((c) => ({
                  ...c,
                  x:
                    c.x +
                    (e.key === "ArrowLeft"
                      ? d
                      : e.key === "ArrowRight"
                        ? -d
                        : 0),
                  y:
                    c.y +
                    (e.key === "ArrowUp" ? d : e.key === "ArrowDown" ? -d : 0),
                }));
              }
            }
          }}
          onWheel={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            setCamera((c) =>
              zoomCamera(
                c,
                Math.exp(-e.deltaY * 0.0015),
                e.clientX - rect.left,
                e.clientY - rect.top,
              ),
            );
          }}
          onPointerDown={(e) => {
            if (e.button !== 0) return;
            const target = (e.target as Element).closest("[data-node-id]");
            const id = target?.getAttribute("data-node-id") || null;
            const node = byId.get(id || "");
            drag.current = {
              id,
              px: e.clientX,
              py: e.clientY,
              x: node?.x ?? camera.x,
              y: node?.y ?? camera.y,
              moved: false,
            };
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            const d = drag.current;
            if (!d) return;
            const dx = e.clientX - d.px,
              dy = e.clientY - d.py;
            if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
            if (d.id)
              setNodes((old) =>
                old.map((n) =>
                  n.id === d.id
                    ? {
                        ...n,
                        x: d.x + dx / camera.scale,
                        y: d.y + dy / camera.scale,
                      }
                    : n,
                ),
              );
            else setCamera((c) => ({ ...c, x: d.x + dx, y: d.y + dy }));
          }}
          onPointerUp={(e) => {
            const d = drag.current;
            drag.current = null;
            if (e.currentTarget.hasPointerCapture(e.pointerId))
              e.currentTarget.releasePointerCapture(e.pointerId);
            if (d && !d.moved) {
              if (d.id) {
                const n = byId.get(d.id);
                if (n) select(n);
              } else setSelected(null);
            }
          }}
          onPointerCancel={() => {
            drag.current = null;
          }}
        >
          <g
            transform={`translate(${camera.x},${camera.y}) scale(${camera.scale})`}
            data-camera="true"
          >
            {shownEdges.map((e, i) => {
              const a = byId.get(e.source)!,
                b = byId.get(e.target)!;
              return (
                <line
                  key={i}
                  data-projected={!!e.via}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  className={`obsidian-edge ${focus && (e.source === focus || e.target === focus) ? "connected" : ""}`}
                  style={{
                    opacity: focus && !neighbors.has(e.source) ? 0.12 : 1,
                  }}
                  vectorEffect="non-scaling-stroke"
                >
                  <title>{e.via ? `Смысловая связь через темы: ${e.via.map((id) => byId.get(id)?.label || id).join(" → ")}` : "Связь по теме"}</title>
                </line>
              );
            })}
            {visible.map((n) => (
              <g
                key={n.id}
                data-node-id={n.id}
                className={`obsidian-node ${n.kind} ${selected === n.id ? "selected" : ""}`}
                role="button"
                tabIndex={0}
                aria-label={`${names[n.kind]}: ${n.label}`}
                aria-pressed={selected === n.id}
                transform={`translate(${n.x},${n.y})`}
                style={{
                  opacity:
                    (focus && !neighbors.has(n.id)) ||
                    (query && !matches.some((m) => m.id === n.id))
                      ? 0.2
                      : 1,
                }}
                onMouseEnter={() => setHover(n.id)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(n.id)}
                onBlur={() => setHover(null)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    select(n);
                  }
                }}
              >
                <title>{n.label}</title>
                <circle
                  r={Math.max(n.radius, 20 / camera.scale)}
                  className="graph-hit"
                />
                <circle r={n.radius} className="graph-point" />
                {selected ? (
                  <text y={n.radius + 18 / camera.scale} textAnchor="middle" fontSize={13 / camera.scale}>
                  {graphLabelLines(n.label, size.width < 400 ? 26 : 30).map((line, i) => <tspan key={i} x={0} dy={i ? 17 / camera.scale : 0}>{line}</tspan>)}
                  </text>
                ) : labels.has(n.id) && (
                  <text
                    x={(labels.get(n.id)!.x + 7 - camera.x) / camera.scale - n.x}
                    y={(labels.get(n.id)!.y + 16 - camera.y) / camera.scale - n.y}
                    textAnchor="start"
                    fontSize={12 / camera.scale}
                    data-graph-label={n.id}
                    vectorEffect="non-scaling-stroke"
                  >
                    {labels.get(n.id)!.text}
                  </text>
                )}
              </g>
            ))}
          </g>
        </svg>
        {!visible.length && (
          <div className="graph-empty">
            <Empty title="Нет видимых узлов">
              Выберите тип узлов в фильтрах или добавьте документы.
            </Empty>
          </div>
        )}
      </div>
        <div className="graph-bottom">
          <div className="graph-legend" title="В обзоре показана принадлежность тем документам. Выберите узел для его смысловых связей.">
            {(Object.keys(names) as NodeKind[]).map((k) => (
              <span key={k}>
                <i className={`graph-dot ${k}`} />
                {names[k]}
              </span>
            ))}
          </div>
          <div className="graph-zoom">
            <Button aria-label="Уменьшить карту" onClick={() => zoom(1 / 1.25)}>
              <ZoomOut size={18} />
            </Button>
            <output aria-label="Масштаб карты">
              {Math.round(camera.scale * 100)}%
            </output>
            <Button aria-label="Увеличить карту" onClick={() => zoom(1.25)}>
              <ZoomIn size={18} />
            </Button>
            <Button
              aria-label="Показать всю карту"
              onClick={() =>
                setCamera(fitCamera(visible, size.width, size.height))
              }
            >
              <Scan size={18} />
            </Button>
          </div>
        </div>
      </div>
        {active && (
          <aside className="graph-inspector" aria-label="Выбранный узел">
            <div className="inline spread">
              <Badge>{names[active.kind]}</Badge>
              <button
                className="sm-icon-button"
                aria-label="Снять выбор узла"
                onClick={() => setSelected(null)}
              >
                <X size={18} />
              </button>
            </div>
            <h2>{active.label}</h2>
            {active.kind === "document" && (
              <Button
                onClick={() => {
                  setFull(false);
                  onDocument({
                    id: active.sourceId,
                    revision: data.corpus_revision,
                  });
                }}
              >
                Открыть регламент <ArrowUpRight size={16} />
              </Button>
            )}
            {!!related.length && <nav className="graph-related" aria-label="Связанные узлы">
              <h3>Связанные документы и узлы</h3>
              {related.map((n) => {
                const edge = edges.find((e) => e.source === n.id || e.target === n.id);
                return <button key={n.id} onClick={() => select(n)}>
                  <span className={`graph-dot ${n.kind}`} />
                  <span>{n.label}{edge?.via && <small>Через {edge.via.map((id) => byId.get(id)?.label || id).join(" → ")}</small>}</span>
                  <ArrowUpRight size={16} />
                </button>;
              })}
            </nav>}
            {question ? (
              <>
                <Badge
                  tone={
                    question.result.result_type === "answered"
                      ? "success"
                      : "warning"
                  }
                >
                  {question.stale
                    ? "Нужна перепроверка"
                    : question.result.result_type === "answered"
                      ? "Ответ найден"
                      : "Есть неподтверждённые части"}
                </Badge>
                {question.result.missing_information.map((s, i) => (
                  <p key={i}>{s}</p>
                ))}
                <a
                  className="sm-button button-neutral"
                  href={`#/admin/checks?question=${encodeURIComponent(question.question)}`}
                  onClick={() => setFull(false)}
                >
                  Проверить вопрос <ArrowUpRight size={16} />
                </a>
              </>
            ) : error ? (
              <ErrorNotice error={error} />
            ) : !fragments ? (
              <Loading />
            ) : (
              <>
                <h3>Фрагменты по теме</h3>
                {readableFragments?.length ? (
                  readableFragments.map((f) => (
                    <details key={f.source_id} className="graph-fragment">
                      <summary>{fragmentTitle(f.preview)}</summary>
                      <p className="meta">{f.document_name}</p>
                      <p>{f.preview}</p>
                      <Button
                        variant="subtle"
                        onClick={() => openSource(f.source_id)}
                      >
                        Открыть источник <ArrowUpRight size={16} />
                      </Button>
                    </details>
                  ))
                ) : (
                  <p className="meta">Нет содержательных фрагментов для предпросмотра. Полный текст доступен в регламенте.</p>
                )}
              </>
            )}
          </aside>
        )}
      </div>
    </div>
  );
  return (
    <>
      {!full && canvas}
      <Modal
        open={full}
        onClose={() => setFull(false)}
        title="Карта знаний"
        description="Перетаскивайте узлы и поле карты. Колесо — масштаб, 0 — показать всё."
        fullScreen
      >
        {full && canvas}
      </Modal>
      <p className="meta">
        Выберите узел, чтобы оставить только его ветку. При скрытых темах связи проходят через цепочки тем.
        Это смысловая близость, а не подтверждённые ссылки между регламентами.
        Неподтверждённый вопрос требует проверки и сам по себе не означает
        дефект регламента.
      </p>
    </>
  );
}
