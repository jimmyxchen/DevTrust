# DevTrust - Uncover the truth behind GitHub stars

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Status](https://img.shields.io/badge/status-beta-yellow)](https://github.com/JimmyChen/DevTrust)

**DevTrust** is a multi-signal analysis tool that detects fake and botted stars on GitHub repositories. It uses 8 distinct detection signals to analyze stargazer profiles and behavior patterns, providing a comprehensive trustworthiness score.

## The Problem

Fake stars are a growing problem on GitHub. Bad actors purchase stars from bot farms to inflate repository popularity, misleading developers and investors. Previous tools like [fake-star-detector](https://github.com/dagster-io/fake-star-detector) and [astronomer](https://github.com/ullaakut/astronomer) have tackled this problem with limited signals.

## How DevTrust Improves

DevTrust combines **8 detection signals** (vs 1-2 in existing tools):

| Signal | Detection Method | Existing Tool |
|--------|-----------------|---------------|
| **Timing Burst** | Statistical analysis of star timing distribution | ✗ |
| **Account Age** | Profile age + throwaway account detection | ✓ |
| **User Activity** | GitHub Events API analysis | ✓ |
| **Creation Cluster** | DBSCAN clustering of account creation dates | ✗ |
| **Cross-Repo Similarity** | Co-starring pattern analysis across repos | ✗ |
| **Network Analysis** | Social graph analysis of stargazer connections | ✗ |
| **Commit Depth** | Code contribution quality assessment | ✗ |
| **Behavioral Patterns** | Machine-like behavior detection | ✗ |

### Key Improvements

- **8 detection signals** with weighted scoring (vs 1-2 in existing tools)
- **Multi-signal fusion** - combines weak signals into strong conclusions
- **Real-time API** analysis with intelligent caching
- **Multiple output formats**: terminal, JSON, Markdown
- **Professional CLI** with progress bars and rich output
- **Modular architecture** - easy to add new signals

## Installation

```bash
# Clone the repository
git clone https://github.com/JimmyChen/DevTrust.git
cd DevTrust

# Install with pip
pip install -e .

# Or install with dev dependencies
pip install -e ".[dev]"
```

## Configuration

DevTrust uses a `.env` file for configuration. Copy the example and add your GitHub token:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# GitHub API token (required for repos with many stargazers)
GITHUB_TOKEN=ghp_your_token_here

# Cache settings
CACHE_DIR=.dev_trust_cache
CACHE_TTL_HOURS=24

# Analysis settings
MIN_CONFIDENCE_THRESHOLD=0.5
SAMPLE_SIZE=
OUTPUT_FORMAT=text
VERBOSE=false
NO_CACHE=false
```

The `.env` file is automatically loaded by DevTrust — no shell configuration needed.

## Usage

### Quick Start: Analyze Any Public Repository

DevTrust is configured to automatically read your GitHub token from the project `.env` file. You only need to set it up once:

```bash
# 1. Copy the example environment file
cp .env.example .env

# 2. Edit .env and add your GitHub personal access token
#    GITHUB_TOKEN=ghp_your_token_here
```

Then run analysis on any public GitHub repository:

```bash
# Analyze by owner/repo
devtrust analyze yusufkaraaslan/Skill_Seekers

# Or use a full URL
devtrust analyze https://github.com/owner/repo
```

### Workflow for Analyzing a Repository

1. **Set up your token** (one-time):
   ```bash
   cp .env.example .env
   # Edit .env and add your GitHub token
   ```

2. **Run the analysis**:
   ```bash
   devtrust analyze owner/repo
   ```

3. **Export the results**:
   ```bash
   # Export as JSON
   devtrust analyze owner/repo --format json --output report.json

   # Export as Markdown
   devtrust analyze owner/repo --format markdown --output report.md

   # View in terminal
   devtrust analyze owner/repo --format text
   ```

### Running Without a Token

You can also run DevTrust without a GitHub token, but you'll be limited to 60 API requests/hour (GitHub's unauthenticated rate limit). For repositories with many stargazers, use `--sample` to limit the analysis:

```bash
# Limited unauthenticated analysis
devtrust analyze owner/repo --sample 30 --no-cache
```

### Advanced Options

```bash
# Sample analysis (faster, analyzes N random stargazers)
devtrust analyze owner/repo --sample 200

# JSON output to stdout
devtrust analyze owner/repo --format json

# Save report to file
devtrust analyze owner/repo --format markdown --output report.md

# Adjust confidence threshold (0.0-1.0)
devtrust analyze owner/repo --min-confidence 0.7

# Verbose mode with cache disabled
devtrust analyze owner/repo --verbose --no-cache

# Clear cache before running
devtrust analyze owner/repo --clear-cache
```

### CLI Commands

```bash
devtrust analyze owner/repo    # Run analysis
devtrust clear-cache           # Clear API cache
devtrust info                  # Show config & rate limits
devtrust --version             # Show version
```

## Sample Output

```
======================================================================
  DevTrust Analysis Report
======================================================================

  Repository:  example/popular-repo
  URL:         https://github.com/example/popular-repo
  Language:    Python
  Total Stars: 50,000
  Analyzed:    200

  TRUST SCORE
  [████████████████░░░░░░░░░░░░░░░░] 42.3% trusted
  Estimated fake stars: 57.7%
  Risk Level: HIGH (confidence: 65%)

  DETECTION SIGNALS
  Signal                   Confidence    Flagged  Status
  ----------------------- ---------- ----------  ---------------
  user_activity                  65%       130  🟡 HIGH
  account_age                    55%       110  🟡 HIGH
  timing_burst                   70%       140  🔴 CRITICAL
  creation_cluster               45%        90  🟢 LOW
  cross_repo                     30%        60  🟢 LOW
  network_analysis               25%        50  🟢 LOW
  commit_depth                   20%        40  🟢 LOW
  behavioral_pattern             35%        70  🟢 LOW

  TOP FLAGGED USERS
  Username                      Score  Reason
  -------------------------- --------  ------------------------------
  bot_account_2847               95%  Account created <1 day before starring
  user_abc123                    92%  Account created <7 days before starring
  star_farmer_99                 88%  Account created <1 day before starring

  RECOMMENDATIONS
  1. Consider reviewing the flagged accounts - estimated 57.7% of stars may be fake.
  2. A timing burst was detected - stars came in an unnaturally short window.
  3. Many stargazers have very new accounts. Consider reviewing these accounts.
  4. Consider using GitHub's built-in star removal features if fake stars are confirmed.
```

## Detection Signals Explained

### 1. Timing Burst Detector
Analyzes the distribution of star timestamps. Fake star campaigns create unnatural bursts where many stars arrive in a short window (often within hours). Uses coefficient of variation and burstiness metrics.

### 2. Account Age Detector
Flags throwaway accounts created shortly before starring. Accounts <1 day old are extremely suspicious, while accounts >1 year old are likely legitimate.

### 3. User Activity Detector
Checks GitHub Events API for genuine engagement. Real users have diverse activity (commits, PRs, issues). Bots typically only star repos with zero other activity.

### 4. Creation Cluster Detector
Uses DBSCAN clustering to find groups of accounts created in the same time windows. Bot campaigns register accounts in batches, creating detectable clusters.

### 5. Cross-Repository Similarity
Analyzes co-starring patterns. Fake star farms target multiple repos with the same bot accounts, creating detectable overlap patterns.

### 6. Network Analysis
Builds a social graph of stargazer relationships. Bot accounts often exist in isolated clusters or have no real social connections.

### 7. Commit Depth
Analyzes genuine code contribution through public repos and engagement metrics. Real developers contribute meaningful code.

### 8. Behavioral Patterns
Detects machine-like patterns: high star rates, random usernames, sequential numbering, default avatars.

## Scoring Methodology

The trust score is a weighted combination of all signals:

```
Trust Score = 1.0 - Σ(weight_i × fake_ratio_i × confidence_i)
```

Weights prioritize the most reliable signals:
- User Activity: 20%
- Account Age: 20%
- Timing Burst: 15%
- Creation Cluster: 15%
- Cross-Repository: 15%
- Network Analysis: 10%
- Commit Depth: 10%
- Behavioral Patterns: 10%

## Detection Accuracy

- **True Positives**: Real bot campaigns are consistently flagged
- **False Positives**: Legitimate viral repos may trigger some signals (low confidence)
- **Confidence Score**: Each signal provides a confidence level based on data quality

## API Rate Limits

- Unauthenticated: 60 requests/hour
- Authenticated: 5,000 requests/hour

Use `GITHUB_TOKEN` for higher limits. Caching reduces API calls significantly.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) file.

## Acknowledgments

- [dagster-io/fake-star-detector](https://github.com/dagster-io/fake-star-detector) - Initial inspiration
- [ullaakut/astronomer](https://github.com/ullaakut/astronomer) - Stargazer trust methodology
- PyGithub - GitHub API library
