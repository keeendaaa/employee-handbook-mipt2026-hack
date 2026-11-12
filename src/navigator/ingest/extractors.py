"""Local, read-only extraction. Extracted document content is always data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import tempfile
import zipfile


MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ZIP_ENTRIES = 10000
MAX_PDF_PAGES = 1000
MAX_SHEET_CELLS = 500000


@dataclass
class SourceBlock:
    text: str
    locator: dict
    kind: str = "paragraph"
    heading_path: list[str] = field(default_factory=list)
    method: str = "native"
    metadata: dict = field(default_factory=dict)


@dataclass
class Extraction:
    blocks: list[SourceBlock]
    warnings: list[str]


def _validate(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{path.name}: нужен обычный файл, не символическая ссылка")
    size = path.stat().st_size
    if not 0 < size <= MAX_FILE_BYTES:
        raise ValueError(f"{path.name}: пустой файл или превышен лимит 100 MiB")
    suffix = path.suffix.lower()
    if suffix not in {".pdf", ".docx", ".xlsx"}:
        raise ValueError(f"{path.name}: неподдерживаемый формат {suffix}")
    with path.open("rb") as stream:
        signature = stream.read(8)
    if suffix == ".pdf":
        if not signature.startswith(b"%PDF-"):
            raise ValueError(f"{path.name}: неверная сигнатура PDF")
        return suffix
    if not signature.startswith(b"PK"):
        raise ValueError(f"{path.name}: неверная сигнатура Office ZIP")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise ValueError(f"{path.name}: превышен лимит элементов ZIP")
        if sum(item.file_size for item in entries) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError(f"{path.name}: превышен лимит распакованного ZIP")
        for item in entries:
            parts = Path(item.filename).parts
            if item.flag_bits & 1 or ".." in parts or item.filename.startswith("/"):
                raise ValueError(f"{path.name}: недопустимый элемент ZIP")
            if "vbaproject" in item.filename.lower():
                raise ValueError(f"{path.name}: макросы не поддерживаются")
            if item.filename.endswith(".xml"):
                xml = archive.read(item)
                if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                    raise ValueError(f"{path.name}: DTD и сущности XML запрещены")
        required = "word/document.xml" if suffix == ".docx" else "xl/workbook.xml"
        if required not in archive.namelist():
            raise ValueError(f"{path.name}: отсутствует {required}")
    return suffix


def extract_file(path: Path, *, ocr: bool = True) -> Extraction:
    """Extract without modifying originals or contacting external services."""
    path = Path(path)
    try:
        suffix = _validate(path)
        result = {".pdf": _pdf, ".docx": _docx, ".xlsx": _xlsx}[suffix](path, ocr=ocr)
        if not result.blocks:
            raise ValueError("не найден читаемый текст")
        return result
    except (ValueError, RuntimeError) as exc:
        if str(exc).startswith(path.name + ":"):
            raise
        raise ValueError(f"{path.name}: {exc}") from exc
    except Exception as exc:
        # Do not include parser messages: they can contain source data.
        raise ValueError(f"{path.name}: ошибка чтения ({type(exc).__name__})") from exc


@dataclass
class OcrPage:
    text: str
    rotation: int | None = None
    orientation_confidence: float | None = None
    orientation_error: str | None = None


def _orient_image(path: Path) -> tuple[int | None, float | None, str | None]:
    """OSD measures rendered pixels; it never changes the original document."""
    try:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "osd", "--psm", "0"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        output = result.stdout.decode("utf-8")
        angle = re.search(r"Rotate:\s*(0|90|180|270)\b", output)
        confidence = re.search(r"Orientation confidence:\s*([0-9.]+)", output)
        if angle is None:
            return None, None, "OSD не определил ориентацию"
        rotation = int(angle.group(1))
        score = float(confidence.group(1)) if confidence else None
        if rotation and (score is None or score < 5):
            return None, score, "OSD: недостаточная уверенность; поворот не применён"
        if rotation:
            from PIL import Image

            with Image.open(path) as image:
                corrected = image.transpose({90: Image.Transpose.ROTATE_270,
                                             180: Image.Transpose.ROTATE_180,
                                             270: Image.Transpose.ROTATE_90}[rotation])
                corrected.save(path)
        return rotation, score, None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return None, None, "OSD недоступен или ориентация не определена"


def _ocr_page(path: Path, page: int) -> OcrPage:
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        raise RuntimeError("OCR недоступен: установите Poppler и Tesseract с rus+eng")
    with tempfile.TemporaryDirectory(prefix="navigator-ocr-") as directory:
        output = Path(directory) / "page"
        try:
            subprocess.run(
                ["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile", "-scale-to", "3500", "-png", str(path.resolve()), str(output)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=90,
            )
            rotation, confidence, orientation_error = _orient_image(output.with_suffix(".png"))
            result = subprocess.run(
                ["tesseract", str(output.with_suffix(".png")), "stdout", "-l", "rus+eng"],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
            )
            return OcrPage(result.stdout.decode("utf-8").strip(), rotation, confidence, orientation_error)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"страница {page}: превышен таймаут OCR") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"страница {page}: сбой OCR; проверьте Poppler и языки rus+eng") from exc


def _pdf(path: Path, *, ocr: bool) -> Extraction:
    from pypdf import PdfReader

    reader = PdfReader(path, strict=False)
    if reader.is_encrypted:
        raise ValueError("зашифрованный PDF не поддерживается")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError("превышен лимит 1000 страниц PDF")
    blocks = []
    warnings = ["PDF: структура таблиц и порядок чтения требуют проверки по оригиналу"]
    for index, page in enumerate(reader.pages, 1):
        native = (page.extract_text() or "").strip()
        # Images can hold text on a mixed page. OCR the whole page once,
        # retaining native text separately when it differs.
        images = _has_content_image(page.get("/Resources", {}))
        suspicious = len(native) < 40 or images
        method = "native"
        text = native
        metadata = {}
        if suspicious:
            if ocr:
                try:
                    recognized_page = _ocr_page(path, index)
                    recognized = recognized_page.text
                    metadata.update(ocr_rotation=recognized_page.rotation,
                                    orientation_confidence=recognized_page.orientation_confidence)
                    if recognized_page.orientation_error:
                        warnings.append(f"Страница {index}: {recognized_page.orientation_error}")
                except RuntimeError as exc:
                    warnings.append(str(exc))
                    recognized = ""
                if recognized:
                    text = recognized
                    method = "ocr"
                    metadata["native_text"] = native
                    warnings.append(f"Страница {index}: OCR; точность и расположение таблиц не проверены")
                elif native:
                    warnings.append(f"Страница {index}: OCR не дал текста; сохранён только текстовый слой")
                else:
                    warnings.append(f"Страница {index}: текст не извлечён")
            else:
                warnings.append(f"Страница {index}: возможен скан/смешанная страница, OCR отключён")
        if text:
            blocks.append(SourceBlock(text, {"page": index}, kind="page", method=method, metadata=metadata))
    return Extraction(blocks, warnings)


def _has_content_image(resources, seen=None, depth=0) -> bool:
    """Ignore 1px decorative masks; inspect images nested inside Form XObjects."""
    if depth > 8:
        return True  # Conservatively request OCR for unusually deep forms.
    resources = resources.get_object() if hasattr(resources, "get_object") else resources
    seen = set() if seen is None else seen
    if id(resources) in seen:
        return False
    seen.add(id(resources))
    for ref in resources.get("/XObject", {}).values():
        obj = ref.get_object()
        if obj.get("/Subtype") == "/Image":
            if obj.get("/Width", 0) >= 32 and obj.get("/Height", 0) >= 32:
                return True
        elif obj.get("/Subtype") == "/Form" and _has_content_image(obj.get("/Resources", {}), seen, depth + 1):
            return True
    return False


def _docx(path: Path, *, ocr: bool) -> Extraction:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(path)
    blocks = []
    warnings = []
    headings: list[str] = []
    numbering = None
    try:
        numbering = document.part.numbering_part.element
    except (KeyError, NotImplementedError):
        pass  # The optional numbering part is absent.
    counts: dict[tuple[str, int], int] = {}

    def numbering_label(paragraph):
        props = paragraph._p.pPr
        numpr = props.numPr if props is not None else None
        if numpr is None:
            style = paragraph.style
            while style is not None:
                stylepr = style.element.pPr
                if stylepr is not None and stylepr.numPr is not None:
                    numpr = stylepr.numPr
                    break
                style = style.base_style
        if numpr is None or numpr.numId is None:
            return "", {}
        numid = str(numpr.numId.val)
        level = int(numpr.ilvl.val) if numpr.ilvl is not None else 0
        info = {"num_id": numid, "level": level}
        if numbering is None:
            warnings.append("DOCX: отсутствует описание нумерации, сохранены numId/ilvl")
            return "", info
        num = next((n for n in numbering.findall(qn("w:num")) if n.get(qn("w:numId")) == numid), None)
        aid = num.find(qn("w:abstractNumId")) if num is not None else None
        abstract = next((n for n in numbering.findall(qn("w:abstractNum")) if aid is not None and n.get(qn("w:abstractNumId")) == aid.get(qn("w:val"))), None)
        lvl = next((n for n in abstract.findall(qn("w:lvl")) if int(n.get(qn("w:ilvl"))) == level), None) if abstract is not None else None
        if lvl is None:
            warnings.append("DOCX: шаблон нумерации не восстановлен, сохранены numId/ilvl")
            return "", info
        override = next((n for n in num.findall(qn("w:lvlOverride")) if int(n.get(qn("w:ilvl"))) == level), None)
        if override is not None:
            warnings.append("DOCX: найдено переопределение нумерации; видимую метку нужно проверить")
        fmt = lvl.find(qn("w:numFmt"))
        template = lvl.find(qn("w:lvlText"))
        start = lvl.find(qn("w:start"))
        initial = int(start.get(qn("w:val"))) if start is not None else 1
        start_override = override.find(qn("w:startOverride")) if override is not None else None
        if start_override is not None:
            initial = int(start_override.get(qn("w:val")))
        key = (numid, level)
        counts[key] = counts.get(key, initial - 1) + 1
        for other in list(counts):
            if other[0] == numid and other[1] > level:
                del counts[other]
        if fmt is not None and fmt.get(qn("w:val")) == "bullet":
            label = template.get(qn("w:val"), "•") if template is not None else "•"
        elif fmt is not None and fmt.get(qn("w:val")) == "decimal" and template is not None:
            label = template.get(qn("w:val"), "")
            for nested in range(level + 1):
                if f"%{nested + 1}" in label and (numid, nested) not in counts:
                    warnings.append("DOCX: неполный контекст многоуровневой нумерации")
                label = label.replace(f"%{nested + 1}", str(counts.get((numid, nested), 1)))
        else:
            label = ""
            warnings.append("DOCX: формат нумерации не восстановлен, сохранены numId/ilvl")
        info["rendered_label"] = label
        return label, info

    def append_table(table, locator, heading_path):
        for row_index, row in enumerate(table.rows, 1):
            cells = [cell.text for cell in row.cells]
            row_locator = {**locator, "table_row": row_index}
            if any(value.strip() for value in cells):
                blocks.append(SourceBlock(" | ".join(cells), row_locator, kind="table_row", heading_path=list(heading_path), metadata={"cells": cells}))
            seen = set()
            for column, cell in enumerate(row.cells, 1):
                # Merged cells can reference the same underlying XML element.
                if cell._tc in seen:
                    continue
                seen.add(cell._tc)
                for nested_index, nested in enumerate(cell.tables, 1):
                    append_table(nested, {**locator, "container_path": [*locator.get("container_path", []), {"row": row_index, "column": column, "nested_table": nested_index}]}, heading_path)

    for index, element in enumerate(document.element.body, 1):
        if element.tag == qn("w:p"):
            paragraph = Paragraph(element, document)
            text = paragraph.text.strip()
            label, info = numbering_label(paragraph)
            if not text:
                continue
            if label:
                text = f"{label} {text}"
            style_name = paragraph.style.name if paragraph.style is not None else ""
            heading = re.match(r"Heading (\d+)", style_name)
            if heading:
                level = int(heading.group(1))
                headings = headings[:level - 1] + [text]
            blocks.append(SourceBlock(text, {"block": index}, kind="heading" if heading else "paragraph", heading_path=list(headings), metadata={"style": style_name, "numbering": info}))
        elif element.tag == qn("w:tbl"):
            append_table(Table(element, document), {"block": index}, headings)
    if document.element.body.xpath(".//w:ins | .//w:del | .//w:drawing | .//w:object"):
        warnings.append("DOCX: есть исправления, рисунки или вложенные объекты; их содержание полностью не извлечено")
    for section_index, section in enumerate(document.sections, 1):
        for story_name in ("header", "first_page_header", "even_page_header", "footer", "first_page_footer", "even_page_footer"):
            story = getattr(section, story_name)
            if story.is_linked_to_previous:
                continue
            warnings.append("DOCX: колонтитулы извлечены по секциям; позиции страниц и условия отображения не определены")
            for index, element in enumerate(story._element, 1):
                locator = {"section": section_index, "story": story_name, "block": index}
                if element.tag == qn("w:p"):
                    paragraph = Paragraph(element, story)
                    if paragraph.text.strip():
                        blocks.append(SourceBlock(paragraph.text.strip(), locator, kind=story_name))
                elif element.tag == qn("w:tbl"):
                    append_table(Table(element, story), locator, [])
    return Extraction(blocks, list(dict.fromkeys(warnings)))


def _json_value(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def _xlsx(path: Path, *, ocr: bool) -> Extraction:
    from openpyxl import load_workbook

    formulas = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    cached = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    blocks = []
    warnings = []
    merged_by_sheet = _xlsx_merged_ranges(path)
    try:
        for sheet in formulas:
            first_nonempty = None
            values_sheet = cached[sheet.title]
            if sheet.max_row * sheet.max_column > MAX_SHEET_CELLS:
                raise ValueError(f"лист {sheet.title}: превышен лимит 500000 ячеек")
            if sheet.sheet_state != "visible":
                warnings.append(f"Лист {sheet.title}: скрытый лист включён в извлечение")
            for row, value_row in zip(sheet.iter_rows(), values_sheet.iter_rows()):
                cells = []
                text = []
                for cell, value_cell in zip(row, value_row):
                    if cell.value is None:
                        continue
                    record = {"address": cell.coordinate, "row": cell.row, "column": cell.column}
                    if cell.data_type == "f":
                        formula = cell.value if isinstance(cell.value, str) else getattr(cell.value, "text", None)
                        if formula is None:
                            warnings.append(f"Лист {sheet.title}: нестандартная формула в {cell.coordinate} требует проверки")
                        if not isinstance(cell.value, str):
                            record["formula_type"] = type(cell.value).__name__
                            record["formula_range"] = getattr(cell.value, "ref", None)
                        record.update(formula=formula, cached_value=_json_value(value_cell.value), cache_verified=False)
                        if formula and "#REF!" in formula.upper():
                            record["formula_error"] = "broken_reference"
                            warnings.append(f"Лист {sheet.title}, {cell.coordinate}: повреждённая ссылка #REF! в формуле")
                        text.append(f"{cell.coordinate}: формула {formula if formula is not None else '[не извлечена]'}; сохранённое значение {value_cell.value!s} (не проверено)")
                        warnings.append(f"Лист {sheet.title}: формулы не вычислялись; кэш не проверен")
                    else:
                        record["value"] = _json_value(cell.value)
                        if cell.data_type == "e":
                            record["cell_error"] = str(cell.value)
                            warnings.append(f"Лист {sheet.title}, {cell.coordinate}: ошибка ячейки {cell.value}")
                        text.append(f"{cell.coordinate}: {cell.value}")
                    cells.append(record)
                if cells:
                    if first_nonempty is None:
                        first_nonempty = {"row": cells[0]["row"], "cells": cells, "role": "first_nonempty_row_not_verified_header"}
                    metadata = {"cells": cells, "merged_ranges": merged_by_sheet.get(sheet.title, []), "first_nonempty_row": first_nonempty}
                    body = "\n".join(text)
                    if cells[0]["row"] != first_nonempty["row"]:
                        context = "; ".join(f"{item['address']}: {item.get('value', item.get('formula', ''))}" for item in first_nonempty["cells"])
                        body = f"Контекст первой непустой строки (заголовок не подтверждён): {context}\n{body}"
                    blocks.append(SourceBlock(body, {"sheet": sheet.title, "row": cells[0]["row"], "range": f"{cells[0]['address']}:{cells[-1]['address']}"}, kind="sheet_row", heading_path=[sheet.title], metadata=metadata))
    finally:
        formulas.close()
        cached.close()
    return Extraction(blocks, list(dict.fromkeys(warnings)))


def _xlsx_merged_ranges(path: Path) -> dict[str, list[str]]:
    """read_only openpyxl omits merged ranges; retain them from safe XML."""
    from defusedxml.ElementTree import fromstring

    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    result = {}
    with zipfile.ZipFile(path) as archive:
        relationships = fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.get("Id"): item.get("Target") for item in relationships if item.get("TargetMode") != "External"}
        workbook = fromstring(archive.read("xl/workbook.xml"))
        for sheet in workbook.findall("s:sheets/s:sheet", ns):
            target = targets.get(sheet.get("{" + ns["r"] + "}id"))
            if not target:
                continue
            member = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            if member not in archive.namelist():
                raise ValueError("XLSX: отсутствует XML листа")
            root = fromstring(archive.read(member))
            result[sheet.get("name")] = [item.get("ref") for item in root.findall("s:mergeCells/s:mergeCell", ns)]
    return result
