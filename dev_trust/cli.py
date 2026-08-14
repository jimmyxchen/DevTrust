"""CLI interface for DevTrust."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

from dev_trust.analyzer import DevTrustAnalyzer
from dev_trust.config import settings
from dev_trust.github.client import CacheManager
from dev_trust.reporter import Reporter

console = Console()


def parse_repo_input(repo_input: str) -> tuple[str, str]:
    """Parse repository input as URL or owner/repo string."""
    # Handle GitHub URLs
    if repo_input.startswith("https://github.com/"):
        parts = repo_input.replace("https://github.com/", "").strip("/").split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]

    # Handle owner/repo format
    if "/" in repo_input:
        parts = repo_input.strip("/").split("/")
        if len(parts) == 2:
            return parts[0], parts[1]

    raise click.BadParameter(
        f"Invalid repository format: {repo_input}. "
        "Use 'owner/repo' or a full GitHub URL."
    )


@click.group()
@click.version_option(version="1.0.0", prog_name="devtrust")
def cli() -> None:
    """DevTrust - Uncover the truth behind GitHub stars.

    Analyzes GitHub repositories to detect fake/botted stars using
    multiple signal detection methods.
    """
    pass


@cli.command()
@click.argument("repo")
@click.option(
    "--token",
    envvar="GITHUB_TOKEN",
    help="GitHub personal access token (or set GITHUB_TOKEN env var).",
)
@click.option(
    "--sample",
    type=int,
    default=None,
    help="Analyze only N random stargazers (faster, less accurate).",
)
@click.option(
    "--min-confidence",
    type=float,
    default=0.5,
    help="Minimum confidence threshold for flagging (0.0-1.0).",
)
@click.option(
    "--format",
    type=click.Choice(["text", "json", "markdown"]),
    default="text",
    help="Output format.",
)
@click.option(
    "--output",
    type=click.Path(),
    default=None,
    help="Write report to a file.",
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Enable verbose output.",
)
@click.option(
    "--no-cache",
    is_flag=True,
    help="Disable caching and force fresh API calls.",
)
@click.option(
    "--clear-cache",
    is_flag=True,
    help="Clear the cache before running.",
)
def analyze(
    repo: str,
    token: str | None,
    sample: int | None,
    min_confidence: float,
    format: str,
    output: str | None,
    verbose: bool,
    no_cache: bool,
    clear_cache: bool,
) -> None:
    """Analyze a GitHub repository for fake stars.

    Example usage:

        devtrust analyze owner/repo

        devtrust analyze https://github.com/owner/repo

        devtrust analyze owner/repo --sample 100 --format json
    """
    # Parse repo input
    try:
        owner, name = parse_repo_input(repo)
    except click.BadParameter as e:
        console.print(f"[red]Error: {e.message}[/red]")
        sys.exit(1)

    # Handle cache
    if clear_cache:
        CacheManager(settings.cache_dir).clear()
        console.print("[yellow]Cache cleared.[/yellow]")

    # Override settings from CLI flags
    settings.github_token = token or settings.github_token
    settings.sample_size = sample
    settings.min_confidence_threshold = min_confidence
    settings.output_format = format
    settings.output_file = Path(output) if output else None
    settings.verbose = verbose
    settings.no_cache = no_cache

    # Initialize analyzer
    try:
        github_client = DevTrustAnalyzer(
            github_client=None,
            sample_size=sample,
        ).github_client
        analyzer = DevTrustAnalyzer(
            github_client=github_client,
            sample_size=sample,
        )
    except Exception as e:
        console.print(f"[red]Failed to initialize: {e}[/red]")
        sys.exit(1)

    # Run analysis
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Analyzing repository...", total=100)

            # Phase 1: Fetch data
            progress.update(task, completed=20, description="Fetching stargazers...")
            report = analyzer.analyze_repo(owner, name)

            progress.update(task, completed=100, description="Analysis complete!")

    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "Requires authentication" in error_msg:
            console.print(
                "[red]GitHub API requires authentication for this operation.[/red]\n"
                "[yellow]Set up a token:[/yellow]\n"
                "  1. Create a token at https://github.com/settings/tokens\n"
                "  2. Run: [bold]export GITHUB_TOKEN=ghp_your_token[/bold]\n"
                "  3. Or use: [bold]devtrust analyze owner/repo --token YOUR_TOKEN[/bold]"
            )
        else:
            console.print(f"[red]Analysis failed: {e}[/red]")
        if verbose:
            import traceback
            console.print(traceback.format_exc())
        sys.exit(1)

    # Generate report
    reporter = Reporter(report)

    if output:
        reporter.save_report(Path(output), format)
        console.print(f"[green]Report saved to {output}[/green]")
    else:
        if format == "json":
            console.print_json(reporter.print_json_report())
        elif format == "markdown":
            console.print(reporter.generate_markdown_report())
        else:
            reporter.print_text_report()


@cli.command()
def clear_cache() -> None:
    """Clear the DevTrust cache."""
    CacheManager(settings.cache_dir).clear()
    console.print("[green]Cache cleared successfully.[/green]")


@cli.command()
def info() -> None:
    """Show configuration and rate limit information."""
    from dev_trust.analyzer import DevTrustAnalyzer

    analyzer = DevTrustAnalyzer()
    rate_info = analyzer.github_client.get_rate_limit_info()

    console.print("\n[bold]DevTrust Configuration[/bold]\n")
    console.print(f"  Authenticated: {analyzer.github_client.is_authenticated}")
    console.print(f"  Cache directory: {settings.cache_dir}")
    console.print(f"  Cache enabled: {settings.cache_enabled}")
    console.print(f"  Sample size: {settings.sample_size or 'all'}")
    console.print(f"  Min confidence: {settings.min_confidence_threshold}")
    console.print()

    console.print("[bold]GitHub API Rate Limits[/bold]\n")
    if "error" not in rate_info:
        console.print(f"  Core remaining: {rate_info['core_remaining']}/{rate_info['core_limit']}")
        console.print(f"  Search remaining: {rate_info['search_remaining']}/{rate_info['search_limit']}")
    else:
        console.print(f"  {rate_info['error']}")
    console.print()


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
