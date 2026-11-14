import type {
  Answer,
  Citation,
  ImportJob,
  KnowledgeMap,
  MailSettings,
  MailStatus,
  MaterialRequest,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
  ) {
    super(message);
  }
}
async function checked(response: Response, allowAccepted = false) {
  if (response.ok && (allowAccepted || response.status !== 202))
    return response;
  let body: { detail?: unknown } = {};
  try {
    body = await response.json();
  } catch {
    /* Non-JSON error pages contain no user-facing detail. */
  }
  const message =
    typeof body.detail === "string"
      ? body.detail
      : response.status === 202
        ? "Карта строится. Повторите через несколько секунд."
        : response.status === 422
          ? "Проверьте заполнение полей и подтверждение доступа к данным."
          : `Сервис вернул ошибку (${response.status}). Повторите запрос.`;
  throw new ApiError(message, response.status);
}
export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  try {
    const response = await checked(await fetch(path, options));
    return (await response.json()) as T;
  } catch (error) {
    if (
      error instanceof ApiError ||
      (error instanceof DOMException && error.name === "AbortError")
    )
      throw error;
    throw new ApiError(
      "Не удалось связаться с сервером. Проверьте соединение и повторите.",
    );
  }
}
async function queueImport(
  path: string,
  options: RequestInit,
): Promise<ImportJob> {
  try {
    return await (await checked(await fetch(path, options), true)).json();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      "Не удалось отправить документ. Проверьте соединение и повторите.",
    );
  }
}
export const jsonBody = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
export const adminHeaders = (token: string) => ({
  Authorization: `Bearer ${token}`,
});

/** SSE is split on event boundaries, never on network chunks or assumed UTF-8 boundaries. */
export async function readEvents(
  stream: ReadableStream<Uint8Array>,
  receive: (value: Record<string, unknown>) => void,
) {
  const reader = stream.getReader(),
    decoder = new TextDecoder();
  let buffer = "";
  function drain(final = false) {
    buffer = buffer.replace(/\r\n/g, "\n");
    let end;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const data = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (data) receive(JSON.parse(data));
    }
    if (final && buffer.trim())
      throw new ApiError("Ответ сервера прервался. Повторите запрос.");
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      drain();
    }
    buffer += decoder.decode();
    drain(true);
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}
export function isAnswer(value: unknown): value is Answer {
  if (!value || typeof value !== "object") return false;
  const a = value as Answer;
  return (
    [
      "answered",
      "partial",
      "not_found",
      "needs_clarification",
      "conflict",
    ].includes(a.result_type) &&
    typeof a.corpus_revision === "string" &&
    [a.summary, a.steps].every(
      (list) =>
        Array.isArray(list) &&
        list.every(
          (c) =>
            c &&
            typeof c.text === "string" &&
            Array.isArray(c.citation_ids) &&
            c.citation_ids.every((id) => typeof id === "string"),
        ),
    ) &&
    Array.isArray(a.citations) &&
    a.citations.every(
      (c) =>
        c &&
        typeof c.source_id === "string" &&
        typeof c.quote === "string" &&
        typeof c.document_name === "string",
    ) &&
    [a.missing_information, a.clarifications, a.conflicts].every(
      (list) => Array.isArray(list) && list.every((t) => typeof t === "string"),
    )
  );
}
export async function ask(
  question: string,
  onProgress: (text: string) => void,
  signal?: AbortSignal,
): Promise<Answer> {
  let response: Response;
  try {
    response = await checked(
      await fetch("/api/query/stream", {
        ...jsonBody({ question, mode: "ask", limit: 10 }),
        signal,
      }),
    );
  } catch (error) {
    if (
      error instanceof ApiError ||
      (error instanceof DOMException && error.name === "AbortError")
    )
      throw error;
    throw new ApiError(
      "Не удалось связаться с сервером. Проверьте соединение и повторите.",
    );
  }
  if (!response.body) throw new ApiError("Сервер не вернул поток ответа.");
  let answer: Answer | undefined,
    finished = false;
  await readEvents(response.body, (event) => {
    if (event.type === "error")
      throw new ApiError(
        String(event.detail || "Не удалось обработать вопрос."),
        Number(event.status_code || 500),
      );
    if (event.type === "started") onProgress("Ищем основания в регламентах…");
    if (event.type === "retrieval")
      onProgress("Сопоставляем найденные источники…");
    if (event.type === "stage" && event.stage === "generation")
      onProgress("Собираем ответ и порядок действий…");
    if (event.type === "answer") {
      if (!isAnswer(event.answer))
        throw new ApiError("Ответ сервера имеет неверный формат.");
      answer = event.answer;
    }
    if (event.type === "done") finished = true;
  });
  if (!answer || !finished)
    throw new ApiError("Ответ прервался. Повторите запрос.");
  return answer;
}
export const api = {
  document: (id: string, revision: string, signal?: AbortSignal) =>
    request<import("./types").DocumentText>(
      `/api/documents/${encodeURIComponent(id)}?corpus_revision=${encodeURIComponent(revision)}`,
      { signal },
    ),
  source: (id: string, signal?: AbortSignal) =>
    request<Citation>(`/api/sources/${encodeURIComponent(id)}`, { signal }),
  map: (signal?: AbortSignal) =>
    request<KnowledgeMap>("/api/map?include_questions=true", { signal }),
  topic: (id: string, revision: string, signal?: AbortSignal) =>
    request<{ fragments: import("./types").Fragment[] }>(
      `/api/map/topics/${encodeURIComponent(id)}?corpus_revision=${encodeURIComponent(revision)}`,
      { signal },
    ),
  check: (question: string) =>
    request<{ answer: Answer }>(
      "/api/map/questions",
      jsonBody({ question, public_data: true }),
    ),
  importUrl: (url: string, replace: boolean) =>
    queueImport(
      "/api/imports/url",
      jsonBody({ url, public_data: true, replace_existing: replace }),
    ),
  importFile: (file: File, replace: boolean) => {
    const body = new FormData();
    body.set("file", file);
    body.set("public_data", "true");
    body.set("replace_existing", String(replace));
    return queueImport("/api/imports/file", { method: "POST", body });
  },
  importStatus: (id: string, signal?: AbortSignal) =>
    request<ImportJob>(`/api/imports/${encodeURIComponent(id)}`, { signal }),
  materials: (token: string) =>
    request<{ requests: MaterialRequest[] }>("/api/material-requests", {
      headers: adminHeaders(token),
    }),
  createMaterial: (
    question: string,
    message: string,
    step = "",
    source_ids: string[] = [],
  ) =>
    request<MaterialRequest>(
      "/api/material-requests",
      jsonBody({
        question: question.slice(0, 2000),
        message,
        step,
        source_ids,
        public_data: true,
      }),
    ),
  updateMaterial: (id: string, status: string, token: string) =>
    request(`/api/material-requests/${encodeURIComponent(id)}`, {
      ...jsonBody({ status }),
      method: "PATCH",
      headers: { ...adminHeaders(token), "Content-Type": "application/json" },
    }),
  mail: (token: string) =>
    request<MailStatus>("/api/admin/mail/status", {
      headers: adminHeaders(token),
    }),
  saveMail: (settings: MailSettings, token: string) =>
    request<MailSettings>("/api/admin/mail/settings", {
      ...jsonBody(settings),
      headers: { ...adminHeaders(token), "Content-Type": "application/json" },
    }),
};

export function locator(c: Citation) {
  return (
    Object.entries(c.locator || {})
      .map(
        ([key, value]) =>
          `${({ page: "Страница", sheet: "Лист", row: "Строка", paragraph: "Абзац", cell: "Ячейка" } as Record<string, string>)[key] || key} ${typeof value === "object" ? JSON.stringify(value) : value}`,
      )
      .join(" · ") +
    (c.line_start ? ` · Строки ${c.line_start}–${c.line_end}` : "")
  );
}
