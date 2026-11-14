import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CheckCheck,
  FileText,
  Send,
  Sparkles,
} from "lucide-react";
import {
  Instructions,
  InstructionsTrigger,
  InstructionsContent,
  InstructionsList,
  InstructionsGroup,
  InstructionsItem,
} from "./ui/ai-instructions";
import { HaloSearchInput } from "./ui/halo-search";
import { ask, api } from "../lib/api";
import {
  canComplete,
  completeTask,
  makeTask,
  nextStep,
  toggleStep,
} from "../lib/tasks";
import type { Answer, Claim, Task } from "../lib/types";
import {
  Badge,
  Button,
  Empty,
  ErrorNotice,
  EvidenceCard,
  Loading,
  Modal,
  Notice,
  PageHeading,
  Progress,
  StepItem,
} from "./primitives";

const displayOptions = [
  {
    id: "concise",
    title: "Краткое резюме",
    description: "Показывать подтверждённое резюме перед планом.",
  },
  {
    id: "sources",
    title: "Основания плана",
    description: "Показывать список источников под планом.",
  },
];
export const taskHref = (id: string, step?: number) =>
  `#/task/${id}${step === undefined ? "" : `/step/${step}`}`;
const resultLabel = {
  answered: "По документам",
  partial: "Есть недостающие сведения",
  not_found: "Ответ не подтверждён",
  needs_clarification: "Недостаточно контекста",
  conflict: "Найдено расхождение",
};

export function NewTask({
  onCreate,
  preferences,
  onPreferences,
}: {
  onCreate: (task: Task) => void;
  preferences: string[];
  onPreferences: (values: string[]) => void;
}) {
  const [question, setQuestion] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [stage, setStage] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function submit() {
    if (!question.trim() || busy) return;
    setBusy(true);
    setError("");
    const active = new AbortController();
    controller.current = active;
    try {
      const response = await ask(question.trim(), setStage, active.signal);
      if (!active.signal.aborted && controller.current === active)
        onCreate(makeTask(question.trim(), response));
    } catch (e) {
      if (!active.signal.aborted && controller.current === active)
        setError(e instanceof Error ? e.message : "Не удалось получить ответ.");
    } finally {
      if (controller.current === active) setBusy(false);
    }
  }
  return (
    <div className="new-task">
      <div className="welcome-art">
        <img
          src="/illustrations/mipt-navigator.png"
          alt=""
          width="264"
          height="176"
        />
        <span className="eyebrow">РАБОЧЕЕ ПРОСТРАНСТВО</span>
      </div>
      <PageHeading
        title="С чего начнём?"
        subtitle="Опишите задачу. Смена найдёт основания в регламентах и поможет пройти по каждому шагу."
      />
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label htmlFor="task-question">Ваша рабочая задача</label>
        <textarea
          id="task-question"
          placeholder="Например: нужно оформить трудоустройство сотрудников нового подразделения…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={20000}
          rows={5}
          disabled={busy}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
              e.preventDefault();
              void submit();
            }
          }}
        />
        <div className="composer-footer">
          <Instructions
            instructions={displayOptions}
            value={preferences}
            onValueChange={onPreferences}
          >
            <InstructionsTrigger label="Вид ответа" />
            <InstructionsContent>
              <InstructionsList>
                <InstructionsGroup heading="Отображение">
                  {displayOptions.map((option) => (
                    <InstructionsItem key={option.id} instruction={option} />
                  ))}
                </InstructionsGroup>
              </InstructionsList>
            </InstructionsContent>
          </Instructions>
          <Button
            variant="primary"
            type="submit"
            disabled={busy || !question.trim()}
          >
            {busy ? "Готовим план…" : "Разобрать задачу"}
            <ArrowRight size={16} />
          </Button>
        </div>
      </form>
      {busy && (
        <>
          <Loading>{stage || "Подключаемся к базе…"}</Loading>
          <Button
            onClick={() => {
              controller.current?.abort();
              setBusy(false);
            }}
            variant="subtle"
          >
            Остановить
          </Button>
        </>
      )}
      {error && <ErrorNotice error={error} retry={() => void submit()} />}
      <div className="welcome-notes">
        <div>
          <FileText size={20} />
          <strong>Основание каждого шага</strong>
          <p>Цитаты и конкретное место в документе рядом с действием.</p>
        </div>
        <div>
          <CheckCheck size={20} />
          <strong>В своём темпе</strong>
          <p>Отмечайте выполненное и возвращайтесь к задаче позже.</p>
        </div>
      </div>
      <p className="meta">
        Ответ строится по подключённой базе. Если сведений не хватит, Смена
        покажет, что осталось неизвестным.
      </p>
    </div>
  );
}
function Claims({
  claims,
  onSource,
}: {
  claims: Claim[];
  onSource: (id: string) => void;
}) {
  return (
    <div className="claims">
      {claims.map((c, i) => (
        <p key={i}>
          {c.text}{" "}
          <span className="citation-links">
            {c.citation_ids.map((id, j) => (
              <button
                key={id}
                className="citation-link"
                onClick={() => onSource(id)}
                aria-label={`Открыть источник ${j + 1} для утверждения ${i + 1}`}
              >
                [{j + 1}]
              </button>
            ))}
          </span>
        </p>
      ))}
    </div>
  );
}
function Uncertainty({ answer }: { answer: Answer }) {
  const parts = [
    ...answer.missing_information,
    ...answer.clarifications,
    ...answer.conflicts,
  ];
  return (
    parts.length > 0 && (
      <Notice title={resultLabel[answer.result_type]}>
        {parts.map((text, i) => (
          <p key={i}>{text}</p>
        ))}
      </Notice>
    )
  );
}
export function Feedback({
  task,
  step,
  onClose,
  open,
}: {
  task: Task;
  step?: number;
  onClose: () => void;
  open: boolean;
}) {
  const [message, setMessage] = useState(""),
    [consent, setConsent] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [saved, setSaved] = useState(false);
  useEffect(() => {
    if (open) {
      setMessage("");
      setConsent(false);
      setError("");
      setSaved(false);
    }
  }, [open]);
  async function submit() {
    setBusy(true);
    setError("");
    const claim = step === undefined ? undefined : task.answer.steps[step];
    try {
      await api.createMaterial(
        task.question,
        message,
        claim?.text,
        claim?.citation_ids,
      );
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сохранить запрос.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={saved ? "Запрос сохранён" : "Запросить недостающий материал"}
    >
      {saved ? (
        <>
          <Notice tone="success">
            Администратор увидит ваш запрос в разделе «Запросы материалов».
          </Notice>
          <Button onClick={onClose}>Вернуться к задаче</Button>
        </>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <label className="field">
            Чего не хватает?
            <textarea
              required
              maxLength={3000}
              rows={4}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Укажите, какой документ или подробность нужны для выполнения задачи."
            />
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            Разрешаю передать задачу, шаг и замечание в общую админскую очередь.
            Они не содержат конфиденциальных данных.
          </label>
          {error && <ErrorNotice error={error} />}
          <div className="actions">
            <Button
              type="submit"
              variant="primary"
              disabled={!message.trim() || !consent || busy}
            >
              {busy ? "Сохраняем…" : "Отправить запрос"}
              <Send size={16} />
            </Button>
            <Button onClick={onClose}>Отменить</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
export function TaskJourney({
  task,
  step,
  onUpdate,
  onSource,
  preferences,
}: {
  task: Task;
  step?: number;
  onUpdate: (task: Task) => void;
  onSource: (id: string) => void;
  preferences: string[];
}) {
  const [feedback, setFeedback] = useState(false),
    [detail, setDetail] = useState<Answer | null>(null),
    [busy, setBusy] = useState(false),
    [stage, setStage] = useState(""),
    [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    setDetail(null);
    setError("");
    setBusy(false);
    return () => controller.current?.abort();
  }, [task.id, step]);
  const claim = step === undefined ? undefined : task.answer.steps[step];
  const sources = claim
    ? task.answer.citations.filter((c) =>
        claim.citation_ids.includes(c.source_id),
      )
    : task.answer.citations;
  const missingCitations =
    claim?.citation_ids.filter(
      (id) => !sources.some((c) => c.source_id === id),
    ) || [];
  const goNext = () => {
    if (step === undefined) return;
    const updated = task.completed.includes(step)
      ? task
      : toggleStep(task, step);
    onUpdate(updated);
    const next = nextStep(updated);
    location.hash = taskHref(task.id, next < 0 ? undefined : next).slice(1);
  };
  async function expand() {
    if (!claim) return;
    setBusy(true);
    setError("");
    const active = new AbortController();
    controller.current = active;
    try {
      setDetail(
        await ask(
          `Задача: ${task.question.slice(0, 12000)}\nТекущий этап: ${claim.text}\nРаскрой только этот этап: конкретные действия, условия и ссылки на подтверждающие фрагменты. Если подробностей нет, явно укажи, каких сведений не хватает.`,
          setStage,
          active.signal,
        ),
      );
    } catch (e) {
      if (!active.signal.aborted && controller.current === active)
        setError(e instanceof Error ? e.message : "Ошибка загрузки.");
    } finally {
      if (controller.current === active) setBusy(false);
    }
  }
  if (task.status === "completed" && step === undefined)
    return (
      <>
        <img
          className="completion-art"
          src="/illustrations/mipt-completed.png"
          alt=""
          width="240"
          height="160"
        />
        <PageHeading title="Задача завершена" />
        <Badge tone="success">Завершена</Badge>
        <Progress
          done={task.completed.length}
          total={task.answer.steps.length}
        />
        <h2>Вы отметили все этапы выполненными.</h2>
        <p>
          Отметки отражают ваш прогресс. Результат оформления во внешних
          системах проверьте отдельно.
        </p>
        <div className="actions">
          <a className="sm-button button-primary" href="#/tasks">
            Мои задачи
          </a>
          <Button onClick={() => onUpdate({ ...task, status: "active" })}>
            Снова открыть задачу
          </Button>
        </div>
      </>
    );
  if (step !== undefined && !claim)
    return (
      <Empty
        title="Этап не найден"
        action={
          <a href={taskHref(task.id)} className="sm-button button-neutral">
            Весь план задачи
          </a>
        }
      >
        Откройте актуальный план задачи.
      </Empty>
    );
  return (
    <>
      <PageHeading
        title={claim ? claim.text : task.question}
        subtitle={
          claim
            ? `Шаг ${(step || 0) + 1} из ${task.answer.steps.length}`
            : "План вашей задачи"
        }
      />
      {task.answer.steps.length > 0 && (
        <Progress
          done={task.completed.length}
          total={task.answer.steps.length}
        />
      )}
      <div
        className={`content-columns ${!preferences.includes("sources") && !claim ? "single-column" : ""}`}
      >
        <div className="stack">
          {claim ? (
            <>
              <article className="surface step-detail">
                <Badge tone="analysis">
                  Шаг {(step || 0) + 1} из {task.answer.steps.length}
                </Badge>
                <h2>Что нужно сделать</h2>
                <p>{claim.text}</p>
                {missingCitations.length > 0 && (
                  <Notice title="Не все основания доступны">
                    Для части ссылок фрагменты отсутствуют в ответе. Откройте
                    исходный источник или запросите материал.
                  </Notice>
                )}
                <Button onClick={() => void expand()} disabled={busy}>
                  <Sparkles size={16} />
                  {busy ? "Ищем подробности…" : "Разобрать этот шаг"}
                </Button>
                {busy && <Loading>{stage}</Loading>}
                {error && (
                  <ErrorNotice error={error} retry={() => void expand()} />
                )}
                {detail && (
                  <div className="stack">
                    <h3>Подробности по регламентам</h3>
                    <Claims
                      claims={[...detail.summary, ...detail.steps]}
                      onSource={onSource}
                    />
                    <Uncertainty answer={detail} />
                    {detail.citations.map((c) => (
                      <EvidenceCard
                        key={c.source_id}
                        citation={c}
                        onOpen={onSource}
                      />
                    ))}
                  </div>
                )}
                <Button variant="subtle" onClick={() => setFeedback(true)}>
                  Запросить недостающий материал
                </Button>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={task.completed.includes(step!)}
                    onChange={() => onUpdate(toggleStep(task, step!))}
                  />
                  Этот этап уже выполнен
                </label>
              </article>
              <div className="actions">
                <Button variant="primary" onClick={goNext}>
                  Готово · к следующему этапу
                  <ArrowRight size={16} />
                </Button>
                <a
                  className="sm-button button-neutral"
                  href={taskHref(task.id)}
                >
                  Весь план задачи
                </a>
              </div>
            </>
          ) : (
            <>
              <Uncertainty answer={task.answer} />
              {preferences.includes("concise") &&
                task.answer.summary.length > 0 && (
                  <Claims claims={task.answer.summary} onSource={onSource} />
                )}
              {task.answer.steps.length ? (
                <>
                  <ol className="step-list surface">
                    {task.answer.steps.map((s, i) => (
                      <StepItem
                        key={i}
                        number={i + 1}
                        title={s.text}
                        checked={task.completed.includes(i)}
                        onCheckedChange={() => onUpdate(toggleStep(task, i))}
                        href={taskHref(task.id, i)}
                      />
                    ))}
                  </ol>
                  <div className="actions">
                    <a
                      className="sm-button button-primary"
                      href={taskHref(
                        task.id,
                        nextStep(task) < 0 ? undefined : nextStep(task),
                      )}
                    >
                      {nextStep(task) < 0
                        ? "Проверить план"
                        : "Продолжить по этапам"}
                      <ArrowRight size={16} />
                    </a>
                    <Button
                      disabled={!canComplete(task)}
                      onClick={() => onUpdate(completeTask(task))}
                    >
                      Завершить задачу
                    </Button>
                  </div>
                </>
              ) : (
                <Notice tone="neutral" title="Процедура не выделена">
                  В найденном ответе нет подтверждённого порядка действий. Можно
                  изучить источники или запросить недостающие материалы.
                </Notice>
              )}
              <div className="actions">
                <a href="#/tasks" className="sm-button button-subtle">
                  Вернуться позже
                </a>
                <Button variant="subtle" onClick={() => setFeedback(true)}>
                  Запросить материал
                </Button>
              </div>
              <p className="meta">
                Прогресс сохраняется в этом браузере. Проверено по базе{" "}
                {task.answer.corpus_revision.slice(0, 12)}.
              </p>
            </>
          )}
        </div>
        {(claim || preferences.includes("sources")) && (
          <aside className="source-aside">
            <p className="meta">
              {claim ? "Что говорит документ" : "Основания плана"}
            </p>
            {sources.length ? (
              sources.map((c) => (
                <EvidenceCard
                  key={c.source_id}
                  citation={c}
                  onOpen={onSource}
                />
              ))
            ) : (
              <Notice>Подтверждающие фрагменты не предоставлены.</Notice>
            )}
          </aside>
        )}
      </div>
      {claim && (
        <a className="back-link" href={taskHref(task.id)}>
          <ArrowLeft size={16} />
          Весь план задачи
        </a>
      )}
      <Feedback
        open={feedback}
        onClose={() => setFeedback(false)}
        task={task}
        step={step}
      />
    </>
  );
}
export function TaskList({ tasks }: { tasks: Task[] }) {
  const [search, setSearch] = useState("");
  const visible = tasks.filter((t) =>
    t.question.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  );
  return (
    <>
      <PageHeading
        title="Мои задачи"
        subtitle="Продолжайте с того места, где остановились."
        action={
          <a className="sm-button button-primary" href="#/new">
            Новая задача
          </a>
        }
      />
      <HaloSearchInput
        aria-label="Найти задачу"
        placeholder="Найти задачу"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="halo-search"
      />
      {visible.length ? (
        <div className="task-cards">
          {visible.map((task) => (
            <a
              key={task.id}
              className="task-card surface"
              href={taskHref(task.id)}
            >
              <div className="inline">
                <FileText size={20} />
                <Badge
                  tone={task.status === "completed" ? "success" : "neutral"}
                >
                  {task.status === "completed" ? "Завершена" : "В работе"}
                </Badge>
              </div>
              <h2>{task.question}</h2>
              {task.answer.steps.length > 0 ? (
                <Progress
                  done={task.completed.length}
                  total={task.answer.steps.length}
                />
              ) : (
                <p className="meta">{resultLabel[task.answer.result_type]}</p>
              )}
              <span className="inline">
                {task.status === "completed" ? "Открыть задачу" : "Продолжить"}
                <ArrowRight size={16} />
              </span>
            </a>
          ))}
        </div>
      ) : (
        <Empty title={search ? "Задачи не найдены" : "Пока нет задач"}>
          Опишите рабочую задачу — здесь появятся план и отметки выполнения.
        </Empty>
      )}
      <p className="meta">До 50 последних задач хранятся в этом браузере.</p>
    </>
  );
}
