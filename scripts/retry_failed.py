"""Retry failed repos from the batch analysis."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dev_trust.analyzer import DevTrustAnalyzer
from dev_trust.github.client import GitHubClient
from dev_trust.reporter import Reporter

ANALYSES_FILE = "data/batch_analyses.json"
REPOS_FILE = "data/batch_repos.json"
SAMPLE_SIZE = 5
MAX_RETRIES = 5


def main():
    with open(ANALYSES_FILE) as f:
        results = json.load(f)

    failed_indices = [i for i, r in enumerate(results) if "error" in r]
    print(f"Retrying {len(failed_indices)} failed repos", flush=True)

    for idx in failed_indices:
        repo_info = results[idx]["repo"]
        owner, name = repo_info["full_name"].split("/", 1)
        print(f"[{idx + 1}/100] Retrying {repo_info['full_name']}...", flush=True)
        t0 = time.time()

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                client = GitHubClient()
                analyzer = DevTrustAnalyzer(github_client=client, sample_size=SAMPLE_SIZE)
                report = analyzer.analyze_repo(owner, name)

                reporter = Reporter(report)
                json_str = reporter.print_json_report()
                report_data = json.loads(json_str)

                results[idx] = {
                    "repo": repo_info,
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    "report": report_data,
                    "retried": True,
                    "attempts": attempt,
                }
                elapsed = time.time() - t0
                print(f"  -> OK (attempt {attempt}, {elapsed:.1f}s) trust={report.trust_score:.1%}", flush=True)
                break
            except Exception as e:
                err_str = str(e)
                elapsed = time.time() - t0
                if attempt < MAX_RETRIES:
                    wait = attempt * 3
                    print(f"  [retry {attempt}/{MAX_RETRIES}] {err_str[:60]} — waiting {wait}s ({elapsed:.1f}s elapsed)", flush=True)
                    time.sleep(wait)
                else:
                    print(f"  -> FAIL (attempt {attempt}, {elapsed:.1f}s): {err_str[:80]}", flush=True)
                    results[idx]["retry_error"] = err_str
                    results[idx]["retry_attempts"] = attempt

        # Save after each retry
        with open(ANALYSES_FILE, "w") as f:
            json.dump(results, f, indent=2, default=str)

    # Final summary
    successful = [r for r in results if "error" not in r]
    failed = [r for r in results if "error" in r]
    retried_ok = [r for r in results if r.get("retried") and "error" not in r]

    print(f"\n=== Retry Complete ===", flush=True)
    print(f"Successful: {len(successful)} (including {len(retried_ok)} retried)", flush=True)
    print(f"Still failing: {len(failed)}", flush=True)

    if successful:
        trusts = [r["report"]["trust_score"] for r in successful]
        print(f"Trust scores: mean={sum(trusts)/len(trusts):.1%}, min={min(trusts):.1%}, max={max(trusts):.1%}", flush=True)


if __name__ == "__main__":
    main()
