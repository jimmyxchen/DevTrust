"""Batch analysis script for 100 GitHub repositories."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from dev_trust.analyzer import DevTrustAnalyzer
from dev_trust.github.client import GitHubClient
from dev_trust.reporter import Reporter

REPO_LIST = "/tmp/repo_list.json"
ANALYSES_OUTPUT = "/tmp/devtrust_batch_analyses.json"
REPOS_OUTPUT = "/tmp/devtrust_batch_repos.json"
SAMPLE_SIZE = 5
PROGRESS_FILE = "/tmp/devtrust_batch_progress.json"
MAX_RETRIES = 3


def _make_session() -> requests.Session:
    """Create a requests session with retry logic for transient errors."""
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


_http_session = _make_session()


def load_repos() -> list[dict]:
    with open(REPO_LIST) as f:
        return json.load(f)


def analyze_repo(repo_info: dict) -> dict:
    owner, name = repo_info["full_name"].split("/", 1)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = GitHubClient()
            analyzer = DevTrustAnalyzer(github_client=client, sample_size=SAMPLE_SIZE)
            report = analyzer.analyze_repo(owner, name)

            reporter = Reporter(report)
            json_str = reporter.print_json_report()
            report_data = json.loads(json_str)

            return {
                "repo": repo_info,
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "report": report_data,
            }
        except Exception as e:
            err_str = str(e)
            is_ssl = "SSL" in err_str or "SSLError" in err_str or "EOF" in err_str
            is_timeout = "timeout" in err_str.lower() or "timed out" in err_str.lower()

            if attempt < MAX_RETRIES and (is_ssl or is_timeout):
                wait = attempt * 5
                print(f"  [retry {attempt}/{MAX_RETRIES}] {err_str[:80]} — retrying in {wait}s...", flush=True)
                time.sleep(wait)
            else:
                print(f"  ERROR: {err_str[:120]}", flush=True)
                return {
                    "repo": repo_info,
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    "error": err_str,
                }
    # Should not reach here
    return {
        "repo": repo_info,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "error": "Max retries exceeded",
    }


def save_progress(results: list[dict], current_index: int):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({"current": current_index, "total": 100, "results": results}, f)


def main():
    repos = load_repos()
    print(f"Loaded {len(repos)} repositories, sample_size={SAMPLE_SIZE}, max_retries={MAX_RETRIES}", flush=True)

    start_index = 0
    results = []
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            progress = json.load(f)
            start_index = progress.get("current", 0)
            results = progress.get("results", [])
            print(f"Resuming from repo {start_index + 1}/{len(repos)}", flush=True)

    for i in range(start_index, len(repos)):
        repo = repos[i]
        print(f"[{i + 1}/{len(repos)}] {repo['full_name']} ({repo['stars']:,} stars)...", flush=True)
        t0 = time.time()

        result = analyze_repo(repo)
        results.append(result)

        elapsed = time.time() - t0
        status = "OK" if "error" not in result else "FAIL"
        trust = result.get("report", {}).get("trust_score", "N/A")
        if isinstance(trust, float):
            trust = f"{trust:.1%}"
        print(f"  -> {status} ({elapsed:.1f}s) trust={trust}", flush=True)

        if (i + 1) % 5 == 0:
            save_progress(results, i + 1)

    with open(ANALYSES_OUTPUT, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nAnalyses saved to {ANALYSES_OUTPUT}", flush=True)

    with open(REPOS_OUTPUT, "w") as f:
        json.dump(
            [
                {
                    "full_name": r["repo"]["full_name"],
                    "url": r["repo"]["url"],
                    "stars": r["repo"]["stars"],
                    "language": r["repo"]["language"],
                }
                for r in results
            ],
            f,
            indent=2,
        )
    print(f"Repo list saved to {REPOS_OUTPUT}", flush=True)

    successful = [r for r in results if "error" not in r]
    failed = [r for r in results if "error" in r]
    print(f"\n=== Batch Summary: {len(successful)} OK, {len(failed)} FAIL ===", flush=True)


if __name__ == "__main__":
    main()
