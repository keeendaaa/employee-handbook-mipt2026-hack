"""Verify a deployed API and exact source links without logging document text."""

import argparse
import json
import sys

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--question", required=True)
    parser.add_argument("--ask", action="store_true", help="Also call the paid generation API")
    args = parser.parse_args()
    with httpx.Client(base_url=args.url.rstrip("/"), timeout=265) as client:
        ready = client.get("/health/ready")
        ready.raise_for_status()
        search = client.post("/api/search", json={"question": args.question, "limit": 10})
        search.raise_for_status()
        results = search.json()["results"]
        refs = [row["citation"] for row in results]
        report = {"ready": True, "search_results": len(results), "corpus_revision": ready.json()["corpus_revision"]}
        if args.ask:
            answer = client.post("/api/ask", json={"question": args.question})
            answer.raise_for_status()
            data = answer.json()
            assert data["result_type"] in {"answered", "partial", "not_found", "needs_clarification", "conflict"}
            ids = {ref["source_id"] for ref in data["citations"]}
            for claim in data["summary"] + data["steps"]:
                assert claim["citation_ids"] and set(claim["citation_ids"]) <= ids
            refs.extend(data["citations"])
            report.update(result_type=data["result_type"], model=data["model"], usage=data["usage"])
        for ref in {ref["source_id"]: ref for ref in refs}.values():
            response = client.get("/api/sources/" + ref["source_id"])
            response.raise_for_status()
            source = response.json()
            for key in ("quote", "start", "end", "line_start", "line_end", "locator", "version_id"):
                assert source[key] == ref[key], f"Source mismatch: {key}"
            assert source["block_text"][source["start"]:source["end"]] == source["quote"]
        report["source_links_verified"] = True
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (httpx.HTTPError, AssertionError, ValueError, KeyError) as exc:
        print(f"Smoke check failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
