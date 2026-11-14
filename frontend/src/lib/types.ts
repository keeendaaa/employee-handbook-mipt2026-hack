export interface Citation {
  source_id: string;
  document_name: string;
  document_id?: string;
  locator: Record<string, unknown>;
  quote: string;
  start: number;
  end: number;
  line_start?: number;
  line_end?: number;
  extraction_method?: string;
  block_text?: string;
  extraction_warnings?: string[];
}
export interface Claim {
  text: string;
  citation_ids: string[];
}
export type ResultType =
  | "answered"
  | "partial"
  | "not_found"
  | "needs_clarification"
  | "conflict";
export interface Answer {
  result_type: ResultType;
  summary: Claim[];
  steps: Claim[];
  citations: Citation[];
  missing_information: string[];
  clarifications: string[];
  conflicts: string[];
  corpus_revision: string;
  limitations?: string[];
}
export interface Task {
  id: string;
  question: string;
  answer: Answer;
  completed: number[];
  status: "active" | "completed";
  createdAt: string;
  updatedAt: string;
}
export interface MaterialRequest {
  id: string;
  question: string;
  message: string;
  step: string;
  source_ids: string[];
  status: "new" | "review" | "closed";
  created_at: string;
}
export interface Topic {
  id: string;
  label: string;
  count: number;
  documents: { id: string; count: number }[];
}
export interface MapQuestion {
  id: string;
  question: string;
  result: Answer;
  stale: boolean;
  related_topics: { id: string; similarity: number }[];
}
export interface KnowledgeMap {
  status: string;
  corpus_revision: string;
  chunk_count: number;
  documents: { id: string; name: string }[];
  topics: Topic[];
  edges: { source: string; target: string; kind: string; similarity: number }[];
  questions: MapQuestion[];
}
export interface Fragment {
  id: string;
  document_name: string;
  preview: string;
  source_id: string;
}
export interface ImportJob {
  id: string;
  status: string;
  filename: string | null;
  message: string;
  warnings: string[];
  duplicate: boolean;
  worker_available: boolean;
}
export interface MailSettings {
  enabled: boolean;
  reply_without_issue: boolean;
  senders: string[];
  api_url: string;
}
export interface MailStatus {
  mailbox: string;
  settings: MailSettings;
  worker: { state: string; updated?: string; detail?: string };
  events: {
    sender: string;
    subject: string;
    status: string;
    detail: string;
    updated: string;
  }[];
}
