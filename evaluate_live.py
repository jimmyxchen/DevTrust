"""Evaluate DevTrust live analysis results against practical-tutorials/project-based-learning.

Run: python evaluate_live.py <report.json>
Or: python evaluate_live.py  (to generate fresh report first)
"""
from __future__ import annotations

import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone


def generate_report() -> str:
    """Run the live analysis and return the path to the report."""
    import subprocess
    token = os.environ.get("GITHUB_TOKEN", "")
    report_path = "/tmp/devtrust_live_eval.json"
    cmd = [
        sys.executable, "-m", "dev_trust.cli",
        "analyze", "practical-tutorials/project-based-learning",
        "--token", token,
        "--sample", "200",
        "--format", "json",
        "--output", report_path,
    ]
    print(f"Running: {' '.join(cmd[:3])} ... <token hidden>")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        print(f"Analysis failed with exit code {result.returncode}")
        sys.exit(1)
    return report_path


def evaluate(report_path: str) -> bool:
    """Evaluate the analysis report and verify it's reasonable."""
    with open(report_path) as f:
        report = json.load(f)

    passed = True

    # 1. Basic structure checks
    print("\n=== Structure Validation ===")
    required_keys = ["repository", "trust_score", "fake_star_percentage",
                     "confidence", "risk_level", "analyzed_stars", "signals"]
    for key in required_keys:
        present = key in report
        status = "PASS" if present else "FAIL"
        if not present:
            passed = False
        print(f"  {status}: '{key}' present = {present}")

    # 2. Score range checks
    print("\n=== Score Range Validation ===")
    trust = report.get("trust_score", -1)
    fake = report.get("fake_star_percentage", -1)
    conf = report.get("confidence", -1)

    checks = [
        (0.0 <= trust <= 1.0, f"trust_score={trust} in [0,1]"),
        (0.0 <= fake <= 1.0, f"fake_star_percentage={fake} in [0,1]"),
        (0.0 <= conf <= 1.0, f"confidence={conf} in [0,1]"),
        (report.get("analyzed_stars", 0) > 0, f"analyzed_stars={report.get('analyzed_stars', 0)} > 0"),
    ]
    for check, desc in checks:
        status = "PASS" if check else "FAIL"
        if not check:
            passed = False
        print(f"  {status}: {desc}")

    # 3. Risk level consistency
    print("\n=== Risk Level Consistency ===")
    risk = report.get("risk_level", "")
    valid_levels = {"low", "medium", "high", "critical"}
    check = risk in valid_levels
    status = "PASS" if check else "FAIL"
    if not check:
        passed = False
    print(f"  {status}: risk_level='{risk}' is valid")

    # 4. Trust score vs fake percentage consistency
    if trust >= 0 and fake >= 0:
        expected_trust = 1.0 - fake
        diff = abs(trust - expected_trust)
        # Some tolerance due to clamping and rounding
        check = diff < 0.05
        status = "PASS" if check else "FAIL"
        if not check:
            passed = False
        print(f"  {status}: trust_score ({trust:.3f}) ≈ 1 - fake_pct ({fake:.3f}), diff={diff:.4f}")

    # 5. Signal validation
    print("\n=== Signal Validation ===")
    signals = report.get("signals", [])
    print(f"  Signals detected: {len(signals)}")
    expected_signals = {
        "timing_burst", "account_age", "user_activity",
        "creation_cluster", "cross_repo", "network_analysis",
        "commit_depth", "behavioral_pattern"
    }
    found_signals = {s["name"] for s in signals}
    missing = expected_signals - found_signals
    if missing:
        passed = False
        print(f"  FAIL: Missing signals: {missing}")
    else:
        print(f"  PASS: All 8 signals present")

    # 6. Each signal has valid structure
    for signal in signals:
        name = signal.get("name", "unknown")
        conf_s = signal.get("confidence", -1)
        susp = signal.get("suspicious_count", -1)
        total = signal.get("total_analyzed", -1)
        check = (0.0 <= conf_s <= 1.0 and susp >= 0 and total >= 0
                 and susp <= total if total > 0 else True)
        status = "PASS" if check else "FAIL"
        if not check:
            passed = False
        print(f"  {status}: signal '{name}' conf={conf_s}, flagged={susp}/{total}")

    # 7. Repository info
    print("\n=== Repository Validation ===")
    repo = report.get("repository", {})
    print(f"  Repository: {repo.get('full_name', 'N/A')}")
    print(f"  Language: {repo.get('language', 'N/A')}")
    print(f"  Total stars (GitHub): {repo.get('total_stars', 'N/A'):,}")
    print(f"  Analyzed: {report.get('analyzed_stars', 0)}")

    # 8. Practical-tutorials/project-based-learning specific checks
    print("\n=== Repo-Specific Sanity Checks ===")
    repo_name = repo.get("full_name", "")
    check = repo_name == "practical-tutorials/project-based-learning"
    status = "PASS" if check else "FAIL"
    if not check:
        passed = False
    print(f"  {status}: Repo is 'practical-tutorials/project-based-learning' (got '{repo_name}')")

    # This is a well-known curated list with genuine stars, so trust should be reasonable
    # We don't assert a specific score, but we log it for human review
    print(f"\n  Trust score: {trust:.1%}")
    print(f"  Fake star estimate: {fake:.1%}")
    print(f"  Confidence: {conf:.1%}")
    print(f"  Risk level: {risk}")

    # 9. Recommendations
    print("\n=== Recommendations ===")
    recs = report.get("recommendations", [])
    print(f"  {len(recs)} recommendations generated")
    for i, rec in enumerate(recs[:5], 1):
        print(f"    {i}. {rec[:100]}")

    # Final verdict
    print("\n" + "=" * 60)
    if passed:
        print("  EVALUATION: PASS — All checks passed")
    else:
        print("  EVALUATION: FAIL — Some checks failed")
    print("=" * 60)

    return passed


if __name__ == "__main__":
    if len(sys.argv) > 1:
        report_path = sys.argv[1]
    else:
        # Check if report already exists from a previous run
        default_path = "/tmp/devtrust_report.json"
        if os.path.exists(default_path) and os.path.getsize(default_path) > 10:
            print(f"Using existing report: {default_path}")
            report_path = default_path
        else:
            print("No existing report found, generating fresh analysis...")
            report_path = generate_report()

    passed = evaluate(report_path)
    sys.exit(0 if passed else 1)
