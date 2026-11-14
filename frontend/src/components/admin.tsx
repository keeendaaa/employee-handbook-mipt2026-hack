import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  FileText,
  KeyRound,
  Mail,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Upload,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { api, ApiError } from "../lib/api";
import { graphLayout } from "../lib/graph";
import type {
  Answer,
  Fragment,
  ImportJob,
  KnowledgeMap,
  MailSettings,
  MailStatus,
  MaterialRequest,
} from "../lib/types";
import { HaloSearchInput } from "./ui/halo-search";
import {
  Badge,
  Button,
  Empty,
  ErrorNotice,
  EvidenceCard,
  Loading,
  Notice,
  PageHeading,
} from "./primitives";

function useMap() {
  const [data, setData] = useState<KnowledgeMap | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api
      .map(controller.signal)
      .then(setData)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [retry]);
  return { data, error, loading, reload: () => setRetry((r) => r + 1) };
}
export function AdminAccess({
  token,
  onToken,
}: {
  token: string;
  onToken: (value: string) => void;
}) {
  const [draft, setDraft] = useState(token);
  return (
    <form
      className="access-form"
      onSubmit={(e) => {
        e.preventDefault();
        onToken(draft.trim());
      }}
    >
      <KeyRound size={18} />
      <label htmlFor="admin-key">Доступ администратора</label>
      <input
        id="admin-key"
        type="password"
        autoComplete="off"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="Ключ доступа"
      />
      <Button type="submit">Подключить</Button>
    </form>
  );
}
export function Documents({ admin = false }: { admin?: boolean }) {
  const { data, error, loading, reload } = useMap(),
    [search, setSearch] = useState("");
  const docs =
    data?.documents.filter((d) =>
      d.name.toLowerCase().includes(search.toLowerCase()),
    ) || [];
  return (
    <>
      <PageHeading
        title="Регламенты"
        subtitle="Документы подключённой базы знаний."
        action={
          admin && (
            <a className="sm-button button-primary" href="#/admin/import">
              <Plus size={16} />
              Добавить документ
            </a>
          )
        }
      />
      <HaloSearchInput
        className="halo-search"
        aria-label="Найти регламент"
        placeholder="Поиск по названию"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorNotice error={error} retry={reload} />
      ) : docs.length ? (
        <div className="document-list">
          {docs.map((doc) => (
            <article key={doc.id} className="document-row">
              <div className="document-icon">
                <FileText size={20} />
              </div>
              <div>
                <h2>{doc.name}</h2>
                <p className="meta">В подключённой базе</p>
              </div>
              <Badge>Документ</Badge>
            </article>
          ))}
        </div>
      ) : (
        <Empty title="Документы не найдены">
          {search
            ? "Измените поисковый запрос."
            : "Добавьте первый регламент в базу."}
        </Empty>
      )}
    </>
  );
}
const importNames: Record<string, string> = {
  queued: "В очереди",
  downloading: "Скачиваем",
  extracting: "Извлекаем текст",
  embedding: "Индексируем",
  indexing: "Индексируем",
  publishing: "Публикуем",
  ready: "Готово",
  partial: "С предупреждениями",
  failed: "Ошибка",
};
export function ImportDocument() {
  const [mode, setMode] = useState<"file" | "url">("file"),
    [file, setFile] = useState<File | null>(null),
    [url, setUrl] = useState(""),
    [consent, setConsent] = useState(false),
    [replace, setReplace] = useState(false),
    [job, setJob] = useState<ImportJob | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const terminal = job && ["ready", "partial", "failed"].includes(job.status);
  useEffect(() => {
    if (!job || terminal) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      api
        .importStatus(job.id, controller.signal)
        .then((j) => {
          setJob(j);
          setError("");
        })
        .catch((e) => {
          if (!controller.signal.aborted) setError(e.message);
        });
    }, 3000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [job?.id, terminal]);
  function choose(selected?: File) {
    setError("");
    if (!selected) return;
    if (!/\.(pdf|docx|xlsx)$/i.test(selected.name)) {
      setError("Поддерживаются PDF, DOCX и XLSX.");
      return;
    }
    if (!selected.size || selected.size > 25 * 1024 * 1024) {
      setError("Выберите непустой файл размером до 25 МБ.");
      return;
    }
    setFile(selected);
  }
  async function submit() {
    if (!consent) return;
    setBusy(true);
    setError("");
    try {
      const queued =
        mode === "file" && file
          ? await api.importFile(file, replace)
          : await api.importUrl(url, replace);
      setJob(queued);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Не удалось загрузить документ.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        title="Добавить регламент"
        subtitle="Загрузите файл или укажите прямую публичную ссылку."
      />
      {job ? (
        <div className="stack narrow">
          <article className="surface">
            <Badge
              tone={
                job.status === "failed"
                  ? "danger"
                  : job.status === "ready"
                    ? "success"
                    : "warning"
              }
            >
              {job.duplicate
                ? "Уже есть в базе"
                : importNames[job.status] || job.status}
            </Badge>
            <h2>{job.filename || "Импорт по ссылке"}</h2>
            <p>{job.message}</p>
            {!terminal && <Loading>Обрабатываем документ…</Loading>}
            {!job.worker_available && (
              <Notice>
                Обработчик временно недоступен. Задача сохранена в очереди.
              </Notice>
            )}
            {job.warnings.map((w, i) => (
              <Notice key={i}>{w}</Notice>
            ))}
          </article>
          {error && <ErrorNotice error={error} />}
          <div className="actions">
            <a href="#/admin/documents" className="sm-button button-primary">
              К регламентам
              <ArrowRight size={16} />
            </a>
            {terminal && (
              <Button
                onClick={() => {
                  setJob(null);
                  setError("");
                }}
              >
                Добавить ещё
              </Button>
            )}
          </div>
        </div>
      ) : (
        <form
          className="stack narrow"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <div className="tabs" role="tablist" aria-label="Способ добавления">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "file"}
              onClick={() => setMode("file")}
            >
              Файл
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "url"}
              onClick={() => setMode("url")}
            >
              По ссылке
            </button>
          </div>
          {mode === "file" ? (
            <label
              className="dropzone"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                choose(e.dataTransfer.files[0]);
              }}
            >
              <Upload size={28} />
              <strong>
                {file ? file.name : "Выберите или перетащите файл"}
              </strong>
              <span>PDF, DOCX, XLSX · до 25 МБ</span>
              <input
                type="file"
                accept=".pdf,.docx,.xlsx"
                aria-label="Файл регламента"
                onChange={(e) => choose(e.target.files?.[0])}
              />
            </label>
          ) : (
            <label className="field">
              Прямая ссылка на документ
              <input
                type="url"
                required
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://mipt.ru/…/document.pdf"
                maxLength={4096}
              />
              <span className="meta">
                Публичный PDF, DOCX, XLSX или ссылка на файл Яндекс Диска.
              </span>
            </label>
          )}
          <label className="check-label">
            <input
              type="checkbox"
              checked={replace}
              onChange={(e) => setReplace(e.target.checked)}
            />
            Разрешить замену ранее добавленного документа
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            Документ неконфиденциальный и разрешён для общей базы и внешнего API
            модели.
          </label>
          {error && <ErrorNotice error={error} />}
          <div className="actions">
            <Button
              type="submit"
              variant="primary"
              disabled={
                !consent || busy || (mode === "file" ? !file : !url.trim())
              }
            >
              {busy ? "Добавляем…" : "Добавить в базу"}
            </Button>
            <a className="sm-button button-neutral" href="#/admin/documents">
              Отмена
            </a>
          </div>
        </form>
      )}
    </>
  );
}
export function KnowledgeGraph({
  onSource,
}: {
  onSource: (id: string) => void;
}) {
  const { data, error, loading, reload } = useMap(),
    [selected, setSelected] = useState<string | null>(null),
    [fragments, setFragments] = useState<Fragment[] | null>(null),
    [fragmentError, setFragmentError] = useState(""),
    [zoom, setZoom] = useState(1),
    [filter, setFilter] = useState("all");
  const viewport = useRef<HTMLDivElement | null>(null),
    [canvasWidth, setCanvasWidth] = useState(744);
  useEffect(() => {
    if (!viewport.current) return;
    const observer = new ResizeObserver(([entry]) =>
      setCanvasWidth(Math.max(640, entry.contentRect.width)),
    );
    observer.observe(viewport.current);
    return () => observer.disconnect();
  }, [data]);
  useEffect(() => {
    if (!selected || !data) return;
    const controller = new AbortController();
    setFragments(null);
    setFragmentError("");
    api
      .topic(selected, data.corpus_revision, controller.signal)
      .then((r) => setFragments(r.fragments))
      .catch((e) => {
        if (!controller.signal.aborted) setFragmentError(e.message);
      });
    return () => controller.abort();
  }, [selected, data?.corpus_revision]);
  if (loading)
    return (
      <>
        <PageHeading title="Карта знаний" />
        <Loading />
      </>
    );
  if (error || !data)
    return (
      <>
        <PageHeading title="Карта знаний" />
        <ErrorNotice error={error} retry={reload} />
      </>
    );
  const topic = data.topics.find((t) => t.id === selected),
    questions = data.questions.filter(
      (q) =>
        filter === "all" ||
        (filter === "missing" &&
          ["partial", "not_found"].includes(q.result.result_type)) ||
        (filter === "stale" && q.stale),
    );
  const layout = graphLayout(data.topics.map(t=>t.id),Math.min(questions.length,10),canvasWidth);
  const centres = layout.centres;
  return (
    <>
      <PageHeading
        title="Карта знаний"
        subtitle={`Документы: ${data.documents.length} · Темы: ${data.topics.length} · Фрагменты: ${data.chunk_count}`}
        action={
          <Button onClick={reload}>
            <RefreshCw size={16} />
            Обновить
          </Button>
        }
      />
      <div className="graph-toolbar">
        <div className="tabs" aria-label="Фильтр проверенных вопросов">
          {[
            ["all", "Все связи"],
            ["missing", "Неподтверждённые вопросы"],
            ["stale", "Нужна перепроверка"],
          ].map(([value, label]) => (
            <button
              key={value}
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="inline">
          <Button
            aria-label="Уменьшить карту"
            onClick={() => setZoom((z) => Math.max(0.7, z - 0.15))}
          >
            <ZoomOut size={16} />
          </Button>
          <Button
            aria-label="Увеличить карту"
            onClick={() => setZoom((z) => Math.min(2, z + 0.15))}
          >
            <ZoomIn size={16} />
          </Button>
        </div>
      </div>
      <div className="graph-layout">
        <div className="graph-viewport" ref={viewport}>
          <svg
            width={layout.width * zoom}
            height={layout.height * zoom}
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            className="graph-svg"
            aria-label="Смысловые связи тем и проверенных вопросов"
          >
            {data.edges.map((e, i) => {
              const a = centres.get(e.source),
                b = centres.get(e.target);
              return a && b ? (
                <line
                  key={i}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  className="graph-edge"
                />
              ) : null;
            })}
            {questions.slice(0, 10).map((q, i) => {
              const x = layout.width - 148,
                y = 40 + i * 48;
              return (
                <g key={q.id}>
                  {q.related_topics.map((t) => {
                    const p = centres.get(t.id);
                    return p ? (
                      <line
                        key={t.id}
                        x1={p.x}
                        y1={p.y}
                        x2={x}
                        y2={y + 18}
                        className="graph-edge graph-edge-question"
                      />
                    ) : null;
                  })}
                  <foreignObject x={x - 120} y={y} width={252} height={44}>
                    <a
                      href="#/admin/checks"
                      className={`graph-question ${q.stale ? "stale" : ""}`}
                      title={q.question}
                    >
                      {q.stale ? "↻ " : "? "}
                      {q.question}
                    </a>
                  </foreignObject>
                </g>
              );
            })}
            {data.topics.map((t) => {
              const p = centres.get(t.id)!;
              return (
                <foreignObject
                  key={t.id}
                  x={p.x - 106}
                  y={p.y - 32}
                  width={212}
                  height={78}
                >
                  <button
                    className="graph-node"
                    aria-pressed={selected === t.id}
                    onClick={() => setSelected(t.id)}
                  >
                    <span>{t.label}</span>
                    <small>
                      Фрагменты: {t.count} · Документы: {t.documents.length}
                    </small>
                  </button>
                </foreignObject>
              );
            })}
          </svg>
        </div>
        <aside className="graph-details surface">
          {topic ? (
            <>
              <Badge>Тема</Badge>
              <h2>{topic.label}</h2>
              {fragmentError ? (
                <ErrorNotice
                  error={fragmentError}
                  retry={() => {
                    reload();
                  }}
                />
              ) : !fragments ? (
                <Loading />
              ) : (
                fragments.map((f) => (
                  <article key={f.id} className="fragment">
                    <strong>{f.document_name}</strong>
                    <p>{f.preview}</p>
                    <Button
                      variant="subtle"
                      onClick={() => onSource(f.source_id)}
                    >
                      Открыть источник
                      <ArrowRight size={16} />
                    </Button>
                  </article>
                ))
              )}
            </>
          ) : (
            <>
              <h2>Связи в базе знаний</h2>
              <p>
                Выберите тему, чтобы увидеть документы и конкретные фрагменты.
              </p>
              <Notice tone="neutral">
                Линии показывают смысловую близость. Они не доказывают
                нормативную зависимость документов. Неподтверждённый вопрос
                требует проверки владельцем регламента.
              </Notice>
            </>
          )}
        </aside>
      </div>
      <details className="surface accessible-map">
        <summary>Список тем и связанных документов</summary>
        {data.topics.map((t) => (
          <div key={t.id}>
            <Button variant="subtle" onClick={() => setSelected(t.id)}>
              {t.label}
            </Button>
            <p className="meta">
              {t.documents
                .map(
                  (d) =>
                    data.documents.find((doc) => doc.id === d.id)?.name || d.id,
                )
                .join(" · ")}
            </p>
          </div>
        ))}
      </details>
    </>
  );
}
export function Checks({ onSource }: { onSource: (id: string) => void }) {
  const { data, error, loading, reload } = useMap(),
    [question, setQuestion] = useState(""),
    [consent, setConsent] = useState(false),
    [busy, setBusy] = useState(false),
    [checkError, setCheckError] = useState(""),
    [answer, setAnswer] = useState<Answer | null>(null);
  async function submit() {
    setBusy(true);
    setCheckError("");
    try {
      setAnswer((await api.check(question)).answer);
      reload();
    } catch (e) {
      setCheckError(e instanceof Error ? e.message : "Проверка не выполнена.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        title="Проверка регламентов"
        subtitle="Проверьте рабочую ситуацию и найдите неподтверждённые части ответа."
      />
      <form
        className="surface stack"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label className="field">
          Рабочая ситуация
          <textarea
            rows={3}
            value={question}
            maxLength={500}
            onChange={(e) => setQuestion(e.target.value)}
            required
            placeholder="Как сотруднику действовать в этой ситуации?"
          />
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
          Вопрос неконфиденциальный. Разрешаю сохранить вопрос и результат на
          общей карте.
        </label>
        <Button
          type="submit"
          variant="primary"
          disabled={busy || !consent || !question.trim()}
        >
          {busy ? "Проверяем…" : "Проверить по базе"}
        </Button>
      </form>
      {checkError && <ErrorNotice error={checkError} />}
      <Notice tone="neutral">
        Отсутствие ответа в найденных фрагментах ещё не доказывает дефект
        регламента. Сначала проверьте полноту базы, извлечение текста и
        применимость документов.
      </Notice>
      {answer && (
        <article className="surface stack">
          <Badge
            tone={answer.result_type === "answered" ? "success" : "warning"}
          >
            {answer.result_type === "answered"
              ? "Ответ подтверждён"
              : "Нужна проверка"}
          </Badge>
          {answer.summary.map((s, i) => (
            <p key={i}>{s.text}</p>
          ))}
          {[
            ...answer.missing_information,
            ...answer.clarifications,
            ...answer.conflicts,
          ].map((s, i) => (
            <Notice key={i}>{s}</Notice>
          ))}
          {answer.citations.map((c) => (
            <EvidenceCard key={c.source_id} citation={c} onOpen={onSource} />
          ))}
        </article>
      )}
      <h2>Проверенные ситуации</h2>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorNotice error={error} retry={reload} />
      ) : !data?.questions.length ? (
        <Empty title="Проверок пока нет">
          Добавьте первую рабочую ситуацию выше.
        </Empty>
      ) : (
        <div className="stack">
          {data.questions.map((q) => (
            <article className="surface" key={q.id}>
              <div className="inline">
                <Badge
                  tone={
                    q.stale
                      ? "warning"
                      : q.result.result_type === "answered"
                        ? "success"
                        : "analysis"
                  }
                >
                  {q.stale
                    ? "Нужна перепроверка"
                    : q.result.result_type === "answered"
                      ? "Подтверждено"
                      : "Не всё подтверждено"}
                </Badge>
              </div>
              <h3>{q.question}</h3>
              <p className="meta">
                {q.result.missing_information?.join(" ") ||
                  (q.result.result_type === "answered"
                    ? "Ответ найден в базе."
                    : "Откройте результат проверки.")}
              </p>
              <Button
                onClick={() => {
                  setQuestion(q.question);
                  setAnswer(q.result);
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
              >
                Открыть проверку
              </Button>
            </article>
          ))}
        </div>
      )}
    </>
  );
}
export function Requests({
  token,
  onSource,
}: {
  token: string;
  onSource: (id: string) => void;
}) {
  const [requests, setRequests] = useState<MaterialRequest[]>([]),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState<string | null>(null);
  const reload = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .materials(token)
      .then((r) => setRequests(r.requests))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [token]);
  useEffect(reload, [reload]);
  async function update(r: MaterialRequest, status: string) {
    setBusy(r.id);
    try {
      await api.updateMaterial(r.id, status, token);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сохранить статус.");
    } finally {
      setBusy(null);
    }
  }
  return (
    <>
      <PageHeading
        title="Запросы материалов"
        subtitle="Сотрудники сообщают, чего не хватает для выполнения задач."
        action={
          <Button onClick={reload}>
            <RefreshCw size={16} />
            Обновить
          </Button>
        }
      />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorNotice error={error} retry={reload} />
      ) : !requests.length ? (
        <Empty title="Запросов пока нет">
          Новые замечания сотрудников появятся здесь.
        </Empty>
      ) : (
        requests.map((r) => (
          <article key={r.id} className="surface request-card">
            <div className="inline">
              <Badge
                tone={
                  r.status === "closed"
                    ? "success"
                    : r.status === "review"
                      ? "analysis"
                      : "warning"
                }
              >
                {
                  { new: "Новый", review: "На проверке", closed: "Закрыт" }[
                    r.status
                  ]
                }
              </Badge>
              <span className="meta">
                {new Date(r.created_at).toLocaleDateString("ru-RU")}
              </span>
            </div>
            <h2>{r.message}</h2>
            <p>{r.question}</p>
            {r.step && <p className="meta">Этап: {r.step}</p>}
            <div className="actions">
              {r.source_ids.map((id, i) => (
                <Button key={id} variant="subtle" onClick={() => onSource(id)}>
                  Источник {i + 1}
                </Button>
              ))}
              <Button
                disabled={busy === r.id}
                onClick={() =>
                  void update(
                    r,
                    r.status === "new"
                      ? "review"
                      : r.status === "review"
                        ? "closed"
                        : "new",
                  )
                }
              >
                {r.status === "new"
                  ? "Взять на проверку"
                  : r.status === "review"
                    ? "Закрыть запрос"
                    : "Открыть снова"}
              </Button>
            </div>
          </article>
        ))
      )}
    </>
  );
}
const eventNames: Record<string, string> = {
  pending: "В очереди",
  sending: "Отправляется",
  sent: "Ответ отправлен",
  skipped: "Пропущено",
  retry: "Повтор запланирован",
  failed: "Ошибка",
  uncertain: "Доставка неизвестна",
};
const workerNames: Record<string, string> = {
  starting: "Запускается",
  online: "Работает",
  paused: "На паузе",
  error: "Ошибка",
};
export function MailPanel({ token }: { token: string }) {
  const [data, setData] = useState<MailStatus | null>(null),
    [draft, setDraft] = useState<MailSettings | null>(null),
    [senders, setSenders] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [success, setSuccess] = useState(false),
    [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false),
    savingRef = useRef(false),
    mounted = useRef(true);
  const load = useCallback(async () => {
    try {
      const r = await api.mail(token);
      if (!mounted.current) return;
      setData(r);
      setError("");
      if (!dirtyRef.current && !savingRef.current) {
        setDraft(r.settings);
        setSenders(r.settings.senders.join("\n"));
      }
    } catch (e) {
      if (mounted.current)
        setError(e instanceof Error ? e.message : "Почта недоступна.");
    }
  }, [token]);
  useEffect(() => {
    mounted.current = true;
    dirtyRef.current = false;
    setDirty(false);
    setData(null);
    setDraft(null);
    void load();
    const timer = setInterval(() => void load(), 10000);
    return () => {
      mounted.current = false;
      clearInterval(timer);
    };
  }, [load]);
  function edit(settings: MailSettings) {
    dirtyRef.current = true;
    setDirty(true);
    setSuccess(false);
    setDraft(settings);
  }
  async function save(settings?: MailSettings) {
    if (!draft) return;
    setBusy(true);
    savingRef.current = true;
    setSuccess(false);
    setError("");
    const values = settings || {
      ...draft,
      senders: senders
        .split(/[\n,;]/)
        .map((s) => s.trim())
        .filter(Boolean),
    };
    if (
      values.senders.length > 100 ||
      values.senders.some((s) => s.length > 254 || !/^\S+@\S+\.\S+$/.test(s))
    ) {
      setError("Укажите до 100 корректных адресов, по одному в строке.");
      setBusy(false);
      savingRef.current = false;
      return;
    }
    try {
      const saved = await api.saveMail(values, token);
      setDraft(saved);
      setSenders(saved.senders.join("\n"));
      dirtyRef.current = false;
      setDirty(false);
      setSuccess(true);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Настройки не сохранены.");
    } finally {
      setBusy(false);
      savingRef.current = false;
    }
  }
  return (
    <>
      <PageHeading
        title="Почтовый бот"
        subtitle="Ответы на письма по подключённым регламентам."
        action={
          <Button onClick={() => void load()} disabled={busy}>
            <RefreshCw size={16} />
            Обновить
          </Button>
        }
      />
      {error && <ErrorNotice error={error} retry={() => void load()} />}{" "}
      {!data || !draft ? (
        !error && <Loading />
      ) : (
        <>
          <div className="surface mail-status">
            <div className="inline">
              <div className="document-icon">
                <Mail size={24} />
              </div>
              <div>
                <h2>{data.mailbox}</h2>
                <p className="meta">
                  {data.worker.detail || "Обработка входящих писем"}
                </p>
              </div>
            </div>
            <Badge
              tone={
                data.worker.state === "online"
                  ? "success"
                  : data.worker.state === "error"
                    ? "danger"
                    : "warning"
              }
            >
              {workerNames[data.worker.state] || data.worker.state}
            </Badge>
            {!dirty && (
              <Button
                disabled={busy}
                onClick={() =>
                  void save({
                    ...data.settings,
                    enabled: !data.settings.enabled,
                  })
                }
              >
                {data.settings.enabled ? (
                  <Pause size={16} />
                ) : (
                  <Play size={16} />
                )}{" "}
                {data.settings.enabled ? "Поставить на паузу" : "Запустить"}
              </Button>
            )}
          </div>
          {!data.settings.api_url && (
            <Notice>
              Включён тестовый режим: ответы не обращаются к рабочему API
              регламентов.
            </Notice>
          )}
          <details className="surface mail-settings" open>
            <summary>Настройки бота{dirty && " · есть изменения"}</summary>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void save();
              }}
            >
              <fieldset disabled={busy}>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={draft.enabled}
                    onChange={(e) =>
                      edit({ ...draft, enabled: e.target.checked })
                    }
                  />
                  Обрабатывать входящие письма
                </label>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={draft.reply_without_issue}
                    onChange={(e) =>
                      edit({ ...draft, reply_without_issue: e.target.checked })
                    }
                  />
                  Отвечать на письма, в которых не найден запрос
                </label>
                <label className="field">
                  Разрешённые отправители
                  <textarea
                    rows={3}
                    value={senders}
                    onChange={(e) => {
                      setSenders(e.target.value);
                      edit(draft);
                    }}
                    placeholder="name@example.org"
                  />
                  <span className="meta">
                    По одному адресу в строке. Пустой список разрешает все
                    адреса.
                  </span>
                </label>
                <label className="field">
                  URL обработчика регламентов
                  <input
                    type="url"
                    maxLength={2048}
                    value={draft.api_url}
                    onChange={(e) =>
                      edit({ ...draft, api_url: e.target.value })
                    }
                    placeholder="https://your-domain.ru/api/mail/analyze"
                  />
                  <span className="meta">
                    HTTPS, путь /api/mail/analyze. Пустое поле включает тестовый
                    режим.
                  </span>
                </label>
                <Button
                  type="submit"
                  variant="primary"
                  disabled={!dirty || busy}
                >
                  {busy ? "Сохраняем…" : "Сохранить настройки"}
                </Button>
              </fieldset>
            </form>
            {success && (
              <p role="status" className="inline">
                <Check size={16} />
                Настройки сохранены
              </p>
            )}
          </details>
          <h2>Последние письма</h2>
          {data.events.length ? (
            <div className="mail-events">
              {data.events.map((event, i) => (
                <article key={`${event.updated}-${i}`} className="mail-event">
                  <div>
                    <h3>{event.subject || "Без темы"}</h3>
                    <p className="meta">{event.sender}</p>
                  </div>
                  <Badge
                    tone={
                      event.status === "sent"
                        ? "success"
                        : event.status === "failed"
                          ? "danger"
                          : event.status === "uncertain"
                            ? "warning"
                            : "neutral"
                    }
                  >
                    {eventNames[event.status] || event.status}
                  </Badge>
                  <p>{event.detail}</p>
                  <time className="meta">
                    {new Date(event.updated).toLocaleString("ru-RU")}
                  </time>
                </article>
              ))}
            </div>
          ) : (
            <Empty title="Писем пока нет">
              Здесь появятся последние 50 событий обработки.
            </Empty>
          )}
        </>
      )}
    </>
  );
}
