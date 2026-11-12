"""Isolated, time-limited by the parent, file extractor."""

from dataclasses import asdict
import json
from pathlib import Path
import sys

from .extractors import extract_file


def main():
    path, output = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        if sys.platform == "linux":
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        result = asdict(extract_file(path, ocr=sys.argv[3] == "on"))
    except Exception as exc:
        # Parser messages can contain document contents. Keep details local and bounded.
        result = {"error": str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__}
    output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
