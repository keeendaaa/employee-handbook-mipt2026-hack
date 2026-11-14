import { expect, it } from "vitest";
import { documentSections, fragmentTitle } from "./document";

it("keeps DOCX paragraphs in source order without exposing extraction block headings", () => {
  const texts = ["Министерство науки", "Московский физико-технический институт", "ПРИКАЗ", "1. Сохранить исходный текст.\nПодпись ______"];
  const sections = documentSections(texts.map((text, i) => ({ text, locator: { block: i * 2 + 1 }, method: "native" })));
  expect(sections).toEqual([{ key: "document", paragraphs: texts }]);
});
it("retains page/sheet boundaries and never changes source text", () => {
  expect(documentSections([
    { text: "Первая страница", locator: { page: 1 }, method: "native" },
    { text: "", locator: { page: 1 }, method: "native" },
    { text: "Скан\n  с отступом", locator: { page: 2 }, method: "ocr" },
    { text: "Смета | 12", locator: { sheet: "Смета", row: 1 }, method: "native" },
    { text: "Итого | 12", locator: { sheet: "Смета", row: 2 }, method: "native" },
  ])).toEqual([
    { key: "page:1", paragraphs: ["Первая страница"] },
    { key: "page:2", paragraphs: ["Скан\n  с отступом"] },
    { key: "sheet:Смета", paragraphs: ["Смета | 12", "Итого | 12"] },
  ]);
});
it("uses actual substantive source wording instead of signature placeholders in graph previews", () => {
  expect(fragmentTitle("____________ /_________/\n2025")).toBeNull();
  expect(fragmentTitle("Срок: 5 дней")).toBe("Срок: 5 дней");
  expect(fragmentTitle("__________\n3. Заполните тестовую форму.")).toBe("3. Заполните тестовую форму.");
});
