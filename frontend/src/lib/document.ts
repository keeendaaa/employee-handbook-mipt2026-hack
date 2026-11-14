import type { DocumentText } from "./types";

/** A reading surface follows source order; technical extraction blocks are not headings. */
export function documentSections(blocks: DocumentText["blocks"]) {
  const sections: { key: string; paragraphs: string[] }[] = [];
  for (const block of blocks) {
    if (!block.text.trim()) continue;
    const { page, sheet } = block.locator;
    const key = page != null ? `page:${page}` : sheet != null ? `sheet:${sheet}` : "document";
    const previous = sections[sections.length - 1];
    if (previous?.key === key) previous.paragraphs.push(block.text);
    else sections.push({ key, paragraphs: [block.text] });
  }
  return sections;
}

/** Use source wording, never an AI-generated title or signature placeholder. */
export function fragmentTitle(preview: string): string | null {
  const lines = preview.split(/\r?\n/).map((line) => line.trim());
  const meaningful = lines.find((line) => (line.match(/[\p{L}]/gu) || []).length >= 3);
  return meaningful ? meaningful.slice(0, 150) + (meaningful.length > 150 ? "…" : "") : null;
}
