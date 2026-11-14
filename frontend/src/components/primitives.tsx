import {
  useEffect,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from "@ui-sdk/react/dialog";
import {
  AlertCircle,
  ArrowUpRight,
  BookOpen,
  Check,
  LoaderCircle,
  X,
} from "lucide-react";
import { api, locator } from "../lib/api";
import type { Citation } from "../lib/types";

export function Button({
  variant = "neutral",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "neutral" | "subtle";
}) {
  return (
    <button
      type="button"
      className={`sm-button button-${variant} ${className}`}
      {...props}
    />
  );
}
export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: string;
  children: ReactNode;
}) {
  return (
    <span className="sm-badge" data-tone={tone}>
      {children}
    </span>
  );
}
export function Notice({
  title,
  children,
  tone = "warning",
}: {
  title?: string;
  children: ReactNode;
  tone?: string;
}) {
  return (
    <div className="sm-callout" data-tone={tone}>
      {title && <strong>{title}</strong>}
      <div>{children}</div>
    </div>
  );
}
export function ErrorNotice({
  error,
  retry,
}: {
  error: string;
  retry?: () => void;
}) {
  return (
    <div role="alert" className="sm-callout" data-tone="danger">
      <div className="inline">
        <AlertCircle size={18} />
        <strong>Не удалось загрузить</strong>
      </div>
      <p>{error}</p>
      {retry && <Button onClick={retry}>Повторить</Button>}
    </div>
  );
}
export function Loading({ children = "Загружаем…" }: { children?: ReactNode }) {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={20} />
      {children}
    </div>
  );
}
export function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <BookOpen size={28} strokeWidth={1.5} />
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function PageHeading({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {action}
    </header>
  );
}
export function Progress({ done, total }: { done: number; total: number }) {
  return (
    <div className="progress">
      <p>
        {done} из {total}{" "}
        {total % 10 === 1 && total % 100 !== 11 ? "шага" : "шагов"} выполнено
      </p>
      <div
        className="progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        aria-label="Выполнение задачи"
      >
        {Array.from({ length: total }, (_, i) => (
          <ProgressSegment key={i} filled={i < done} />
        ))}
      </div>
    </div>
  );
}
export function ProgressSegment({ filled }: { filled: boolean }) {
  return <span className="sm-progress-segment" data-filled={filled} />;
}
export function StepItem({
  number,
  title,
  checked,
  onCheckedChange,
  href,
}: {
  number: number;
  title: string;
  checked: boolean;
  onCheckedChange: () => void;
  href: string;
}) {
  return (
    <li className="task-step">
      <label className="step-check">
        <input
          aria-label={`Шаг ${number} выполнен`}
          type="checkbox"
          checked={checked}
          onChange={onCheckedChange}
        />
      </label>
      <div className="step-body">
        <a className="step-title" href={href}>
          {number}. {title}
        </a>
        {checked && <Badge tone="success">Выполнено</Badge>}
        <a className="sm-button button-subtle" href={href}>
          Разобрать шаг
          <ArrowUpRight size={14} />
        </a>
      </div>
    </li>
  );
}
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent
        className={`modal ${wide ? "modal-wide" : ""}`}
        initialFocus="content"
      >
        <div className="modal-heading">
          <div>
            <DialogTitle className="modal-title">{title}</DialogTitle>
            {description && (
              <DialogDescription>{description}</DialogDescription>
            )}
          </div>
          <DialogClose className="sm-icon-button" aria-label="Закрыть">
            <X size={20} />
          </DialogClose>
        </div>
        <div className="modal-body">{children}</div>
      </DialogContent>
    </Dialog>
  );
}
export function EvidenceCard({
  citation,
  onOpen,
}: {
  citation: Citation;
  onOpen: (id: string) => void;
}) {
  return (
    <article className="sm-evidence-card">
      <strong>{citation.document_name}</strong>
      <p className="meta">{locator(citation)}</p>
      <blockquote>
        <mark>{citation.quote}</mark>
      </blockquote>
      <Button variant="subtle" onClick={() => onOpen(citation.source_id)}>
        Открыть фрагмент <ArrowUpRight size={16} />
      </Button>
      {citation.extraction_method === "ocr" && (
        <Badge tone="warning">Текст распознан OCR</Badge>
      )}
    </article>
  );
}
export function SourceModal({
  sourceId,
  onClose,
}: {
  sourceId: string | null;
  onClose: () => void;
}) {
  const [source, setSource] = useState<Citation | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    if (!sourceId) return;
    const controller = new AbortController();
    setSource(null);
    setError("");
    api
      .source(sourceId, controller.signal)
      .then(setSource)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [sourceId]);
  const text = source?.block_text || "",
    validRange =
      source &&
      Number.isInteger(source.start) &&
      Number.isInteger(source.end) &&
      text.slice(source.start, source.end) === source.quote;
  return (
    <Modal
      open={!!sourceId}
      onClose={onClose}
      title={source?.document_name || "Источник"}
      description={
        source ? locator(source) : "Точный фрагмент из базы документов"
      }
      wide
    >
      {error ? (
        <ErrorNotice error={error} />
      ) : !source ? (
        <Loading />
      ) : (
        <>
          <div className="inline">
            <Badge>Фрагмент документа</Badge>
            {source.extraction_method === "ocr" && (
              <Badge tone="warning">OCR · возможны ошибки распознавания</Badge>
            )}
          </div>
          <div className="source-text">
            {validRange ? (
              <>
                {text.slice(0, source.start)}
                <mark>{text.slice(source.start, source.end)}</mark>
                {text.slice(source.end)}
              </>
            ) : (
              <mark>{source.quote}</mark>
            )}
          </div>
          {source.extraction_warnings?.map((warning, i) => (
            <Notice key={i}>{warning}</Notice>
          ))}
          <p className="meta">
            Выделен текст, на который ссылается ответ. Ссылка привязана к версии
            документа.
          </p>
          <Button onClick={onClose}>
            <Check size={16} />
            Вернуться к задаче
          </Button>
        </>
      )}
    </Modal>
  );
}
