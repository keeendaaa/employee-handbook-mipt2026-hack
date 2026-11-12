"""Generate clearly synthetic inputs locally; never imitates real regulations."""

from pathlib import Path
import json

from docx import Document
from openpyxl import Workbook
from navigator.ingest.chunking import digest

destination = Path("data/processed/demo-input")
destination.mkdir(parents=True, exist_ok=True)
document = Document()
document.add_heading("СИНТЕТИЧЕСКИЙ ПРИМЕР: тестовая заявка", 0)
document.add_paragraph("1. Для получения учебного набора подайте тестовую заявку учебному координатору.")
document.add_paragraph("2. Получите подтверждение учебного координатора.")
document.save(destination / "synthetic-procedure.docx")
book = Workbook()
sheet = book.active
sheet.title = "СИНТЕТИЧЕСКАЯ СМЕТА"
sheet.append(["Количество", "Цена", "Сумма"])
sheet.append([2, 10, "=A2*B2"])
sheet.merge_cells("A4:C4")
sheet["A4"] = "СИНТЕТИЧЕСКИЙ ПРИМЕР, не реальные данные"
book.save(destination / "synthetic-budget.xlsx")
cases = {"format_version": 1, "corpus_kind": "synthetic", "cases": [
    {"id": "S1", "split": "dev", "question": "Как получить учебный набор?", "expected_type": "answered",
     "supports": [{"document_id": "local-" + digest("synthetic-procedure.docx")[:24],
                   "locator": {"block": 2}, "needle": "подайте тестовую заявку учебному координатору"}],
     "required_facts": ["Тестовая заявка учебному координатору; затем подтверждение."]},
    {"id": "S2", "split": "dev", "question": "Вычислена ли сумма в C2 синтетической сметы?", "expected_type": "partial",
     "supports": [{"document_id": "local-" + digest("synthetic-budget.xlsx")[:24],
                   "locator": {"sheet": "СИНТЕТИЧЕСКАЯ СМЕТА", "row": 2, "range": "A2:C2"}, "needle": "формула =A2*B2"}],
     "required_facts": ["Формула сохранена, кэш отсутствует и не проверен; не выдавать расчёт за факт источника."]},
]}
(destination.parent / "demo-cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2))
print("Созданы два синтетических файла в data/processed/demo-input")
