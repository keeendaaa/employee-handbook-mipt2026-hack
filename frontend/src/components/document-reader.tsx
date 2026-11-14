import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { DocumentText } from "../lib/types";
import { Badge, ErrorNotice, Loading, Modal, Notice } from "./primitives";

export interface DocumentSelection {
  id: string;
  revision: string;
}
export function DocumentReader({
  document,
  onClose,
}: {
  document: DocumentSelection | null;
  onClose: () => void;
}) {
  const [data, setData] = useState<DocumentText | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    if (!document) return;
    const controller = new AbortController();
    setData(null);
    setError("");
    api
      .document(document.id, document.revision, controller.signal)
      .then(setData)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [document?.id, document?.revision]);
  return (
    <Modal
      open={!!document}
      onClose={onClose}
      title={data?.name || "Регламент"}
      description="Извлечённый текст документа"
      wide
    >
      {error ? (
        <ErrorNotice error={error} />
      ) : !data ? (
        <Loading />
      ) : (
        <>
          <div className="inline">
            <Badge>Документ целиком</Badge>
            <span className="meta">Версия {data.version_id.slice(0, 8)}</span>
          </div>
          {data.warnings.map((w, i) => (
            <Notice key={i}>{w}</Notice>
          ))}
          <div className="document-reader">
            {data.blocks.map((block, i) => (
              <section className="document-block" key={i}>
                <h3>
                  {Object.entries(block.locator)
                    .map(
                      ([key, value]) =>
                        `${({ page: "Страница", paragraph: "Абзац", sheet: "Лист" } as Record<string, string>)[key] || key} ${value}`,
                    )
                    .join(" · ") || `Блок ${i + 1}`}
                </h3>
                {block.method === "ocr" && (
                  <Badge tone="warning">
                    OCR · возможны ошибки распознавания
                  </Badge>
                )}
                <div className="source-text">{block.text}</div>
              </section>
            ))}
          </div>
          <p className="meta">
            Показан текст, извлечённый для базы знаний. Оформление оригинального
            файла может отличаться.
          </p>
        </>
      )}
    </Modal>
  );
}
