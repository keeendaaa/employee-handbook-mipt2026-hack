import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { DocumentText } from "../lib/types";
import { documentSections } from "../lib/document";
import { ErrorNotice, Loading, Modal } from "./primitives";

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
      wide
    >
      {error ? (
        <ErrorNotice error={error} />
      ) : !data ? (
        <Loading />
      ) : (
        <>
          <article className="document-reader" aria-label={data.name}>
            {documentSections(data.blocks).map((section, i) => (
              <section className="document-page" key={`${section.key}:${i}`}>
                {section.paragraphs.map((paragraph, index) => (
                  <p className="document-paragraph" key={index}>{paragraph}</p>
                ))}
              </section>
            ))}
          </article>
          <details className="document-information">
            <summary>Информация о документе</summary>
            <div>
              <p className="meta">Версия {data.version_id.slice(0, 8)}. Показан извлечённый текст; оформление оригинала может отличаться.</p>
              {data.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
              {data.blocks.some((b) => b.method === "ocr") && <p>OCR: возможны ошибки распознавания.</p>}
            </div>
          </details>
        </>
      )}
    </Modal>
  );
}
