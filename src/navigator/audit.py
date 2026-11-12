"""Technical extraction review. Counts do not certify normative correctness."""

from collections import Counter
from pathlib import Path


def audit_documents(documents: list[dict]) -> dict:
    formats, totals, rows = Counter(), Counter(), []
    for doc in documents:
        formats[Path(doc["name"]).suffix.lower()] += 1
        counts = Counter(blocks=len(doc["blocks"]))
        issues = set()
        for block in doc["blocks"]:
            if block.get("method") == "ocr":
                counts["ocr_pages"] += 1
                meta = block.get("metadata", {})
                if meta.get("ocr_rotation"):
                    counts["rotated_pages"] += 1
                if meta.get("ocr_rotation") is None:
                    counts["orientation_unresolved"] += 1
                    issues.add("orientation_unresolved")
                issues.add("ocr_accuracy_unverified")
            for cell in block.get("metadata", {}).get("cells", []):
                if not isinstance(cell, dict):
                    continue  # DOCX cells are strings, XLSX cells are records.
                if "formula" in cell:
                    counts["formula_cells"] += 1
                    counts["missing_formula_cache"] += cell.get("cached_value") is None
                    issues.add("formula_cache_unverified")
                    if "#REF!" in (cell["formula"] or "").upper():
                        counts["broken_formula_references"] += 1
                        issues.add("broken_formula_reference")
                if cell.get("cell_error"):
                    counts["error_cells"] += 1
                    issues.add("spreadsheet_error_cell")
        if doc["name"].lower().endswith(".pdf"):
            issues.add("table_layout_and_reading_order_unverified")
        if any("нумерац" in w for w in doc["warnings"]):
            issues.add("numbering_requires_review")
        if doc["warnings"] and not issues:
            issues.add("other_extraction_warnings")
        totals.update(counts)
        rows.append({"document_id": doc["document_id"], "version_id": doc["version_id"],
                     "status": "needs_review" if issues else "technical_checks_only",
                     "issue_types": sorted(issues), "counts": dict(counts),
                     "normative_completeness_verified": False})
    return {"document_count": len(documents), "formats": dict(formats), "totals": dict(totals),
            "documents_requiring_review": sum(r["status"] == "needs_review" for r in rows),
            "normative_completeness_verified": False, "documents": rows}
