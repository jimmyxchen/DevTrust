"""Rich terminal reporter for analysis results."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from dev_trust.models import AnalysisReport


class Reporter:
    """Generate reports in various formats."""

    def __init__(self, report: AnalysisReport):
        self.report = report

    def print_text_report(self) -> None:
        """Print a rich text report to the terminal."""
        r = self.report
        risk_color = r.get_risk_color()
        reset = "\033[0m"
        bold = "\033[1m"

        # Header
        print()
        print(f"{'='*70}")
        print(f"{bold}  DevTrust Analysis Report{reset}")
        print(f"{'='*70}")
        print()

        # Repository info
        print(f"  Repository:  {r.repo.full_name}")
        print(f"  URL:         {r.repo.html_url}")
        print(f"  Language:    {r.repo.language or 'N/A'}")
        print(f"  Total Stars: {r.repo.stars_count:,}")
        print(f"  Analyzed:    {r.analyzed_stars:,}")
        print()

        # Trust score
        print(f"  {bold}TRUST SCORE{reset}")
        trust_pct = r.trust_score * 100
        fake_pct = r.fake_star_percentage * 100
        bar_length = 30
        filled = int(bar_length * r.trust_score)

        bar = (
            f"{'█' * filled}"
            f"{'░' * (bar_length - filled)}"
        )

        print(f"  [{bar}] {trust_pct:.1f}% trusted")
        print(f"  Estimated fake stars: {fake_pct:.1f}%")
        print(
            f"  Risk Level: {risk_color}{bold}{r.risk_level.upper()}{reset} "
            f"(confidence: {r.confidence*100:.0f}%)"
        )
        print()

        # Signal breakdown
        print(f"  {bold}DETECTION SIGNALS{reset}")
        print(f"  {'Signal':<25} {'Confidence':>10} {'Flagged':>10}  {'Status'}")
        print(f"  {'-'*25} {'-'*10} {'-'*10}  {'-'*15}")

        for signal in r.signals:
            pct = signal.confidence_score * 100
            status = (
                "\033[91mCRITICAL\033[0m"
                if signal.confidence_score > 0.7 and signal.suspicious_count > 0
                else (
                    "\033[93mHIGH\033[0m"
                    if signal.confidence_score > 0.5 and signal.suspicious_count > 0
                    else (
                        "\033[92mLOW\033[0m"
                        if signal.confidence_score > 0.3 and signal.suspicious_count > 0
                        else "\033[90mNONE\033[0m"
                    )
                )
            )
            print(
                f"  {signal.name:<25} {pct:>9.0f}% {signal.suspicious_count:>9}  {status}"
            )

        print()

        # Top flagged users
        if r.flagged_users:
            print(f"  {bold}TOP FLAGGED USERS{reset}")
            print(f"  {'Username':<25} {'Score':>8}  {'Reason'}")
            print(f"  {'-'*25} {'-'*8}  {'-'*30}")

            for username, score, reason in r.flagged_users[:15]:
                print(f"  {username:<25} {score*100:>7.0f}%  {reason}")

            if len(r.flagged_users) > 15:
                print(f"  ... and {len(r.flagged_users) - 15} more")

            print()

        # Recommendations
        if r.recommendations:
            print(f"  {bold}RECOMMENDATIONS{reset}")
            for i, rec in enumerate(r.recommendations, 1):
                print(f"  {i}. {rec}")
            print()

        # Footer
        print(f"  Analyzed at: {r.analyzed_at.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"{'='*70}")
        print()

    def print_json_report(self) -> str:
        """Generate JSON report."""
        r = self.report
        data = {
            "repository": {
                "full_name": r.repo.full_name,
                "url": r.repo.html_url,
                "language": r.repo.language,
                "total_stars": r.repo.stars_count,
            },
            "trust_score": round(r.trust_score, 4),
            "fake_star_percentage": round(r.fake_star_percentage, 4),
            "confidence": round(r.confidence, 4),
            "risk_level": r.risk_level,
            "analyzed_stars": r.analyzed_stars,
            "signals": [
                {
                    "name": s.name,
                    "confidence": round(s.confidence_score, 4),
                    "suspicious_count": s.suspicious_count,
                    "total_analyzed": s.total_analyzed,
                    "flagged_users": s.flagged_users,
                }
                for s in r.signals
            ],
            "flagged_users": [
                {"username": u, "score": round(s, 4), "reason": reason}
                for u, s, reason in r.flagged_users
            ],
            "recommendations": r.recommendations,
            "analyzed_at": r.analyzed_at.isoformat(),
        }
        return json.dumps(data, indent=2)

    def generate_markdown_report(self) -> str:
        """Generate a Markdown report."""
        r = self.report
        lines: list[str] = []

        lines.append(f"# DevTrust Analysis: {r.repo.full_name}")
        lines.append("")
        lines.append(f"**Repository:** [{r.repo.full_name}]({r.repo.html_url})")
        lines.append(f"**Language:** {r.repo.language or 'N/A'}")
        lines.append(f"**Total Stars:** {r.repo.stars_count:,}")
        lines.append(f"**Analyzed:** {r.analyzed_stars:,}")
        lines.append("")
        lines.append("## Trust Score")
        lines.append("")
        lines.append(f"**Trust Score:** {r.trust_score*100:.1f}%")
        lines.append(f"**Estimated Fake Stars:** {r.fake_star_percentage*100:.1f}%")
        lines.append(f"**Risk Level:** {r.risk_level.upper()} (confidence: {r.confidence*100:.0f}%)")
        lines.append("")

        lines.append("## Signal Breakdown")
        lines.append("")
        lines.append("| Signal | Confidence | Flagged | Status |")
        lines.append("|--------|-----------|---------|--------|")

        for signal in r.signals:
            status = (
                "🔴 CRITICAL"
                if signal.confidence_score > 0.7
                else (
                    "🟡 HIGH"
                    if signal.confidence_score > 0.5
                    else (
                        "🟢 LOW"
                        if signal.confidence_score > 0.3
                        else "⚪ NONE"
                    )
                )
            )
            pct = f"{signal.confidence_score*100:.0f}%"
            lines.append(
                f"| {signal.name} | {pct} | {signal.suspicious_count}/{signal.total_analyzed} | {status} |"
            )

        lines.append("")

        if r.flagged_users:
            lines.append("## Top Flagged Users")
            lines.append("")
            lines.append("| Username | Score | Reason |")
            lines.append("|----------|-------|--------|")
            for username, score, reason in r.flagged_users[:20]:
                lines.append(f"| {username} | {score*100:.0f}% | {reason} |")
            lines.append("")

        if r.recommendations:
            lines.append("## Recommendations")
            lines.append("")
            for i, rec in enumerate(r.recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")

        lines.append("---")
        lines.append(f"*Generated by DevTrust at {r.analyzed_at.isoformat()}*")
        lines.append("")

        return "\n".join(lines)

    def save_report(self, file_path: Path, format: str = "text") -> None:
        """Save report to a file."""
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if format == "json":
            content = self.print_json_report()
        elif format == "markdown":
            content = self.generate_markdown_report()
        else:
            # Redirect text output
            import io
            import sys

            old_stdout = sys.stdout
            sys.stdout = buffer = io.StringIO()
            try:
                self.print_text_report()
                content = buffer.getvalue()
            finally:
                sys.stdout = old_stdout

        file_path.write_text(content, encoding="utf-8")
