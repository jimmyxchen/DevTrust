# Contributing to DevTrust

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/JimmyChen/DevTrust.git
cd DevTrust

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode with all dependencies
pip install -e ".[dev]"

# Install pre-commit hooks (optional)
pre-commit install
```

## Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=dev_trust --cov-report=html

# Run specific test file
pytest tests/test_dev_trust.py -v

# Run with specific marker
pytest tests/ -m "not integration"
```

## Project Structure

```
dev_trust/
├── __init__.py            # Package init
├── __main__.py            # Entry point
├── config.py              # Configuration (pydantic settings)
├── models.py              # Data models (dataclasses)
├── cli.py                 # CLI interface (Click)
├── analyzer.py            # Main analysis engine
├── reporter.py            # Report generation
├── github/
│   └── client.py          # GitHub API client with caching
└── detector/
    ├── __init__.py
    ├── base.py            # Abstract base detector
    ├── scorer.py          # Weighted scoring engine
    ├── timing_detector.py        # Timing burst detection
    ├── account_age_detector.py   # Account age/throwaway detection
    ├── activity_detector.py      # User activity analysis
    ├── cluster_detector.py       # Creation date clustering
    ├── cross_repo_detector.py    # Cross-repo similarity
    ├── network_detector.py       # Network analysis
    ├── commit_depth_detector.py  # Contribution depth
    └── pattern_detector.py       # Behavioral patterns
```

## Adding a New Signal Detector

1. Create a new file in `dev_trust/detector/`:
   ```python
   from dev_trust.detector.base import BaseSignalDetector
   from dev_trust.models import SignalResult, StarEvent

   class MyNewDetector(BaseSignalDetector):
       name = "my_new_signal"
       description = "What it detects"
       weight = 0.10  # Contribution to overall score

       def get_weight(self) -> float:
           return self.weight

       def detect(self, star_events: list[StarEvent], repo_info: dict) -> SignalResult:
           # Your detection logic here
           ...
   ```

2. Register it in `dev_trust/analyzer.py`:
   ```python
   self.registry.register(MyNewDetector())
   ```

3. Add the weight in `dev_trust/detector/scorer.py`:
   ```python
   WEIGHTS = {
       ...
       "my_new_signal": 0.10,
   }
   ```

4. Add tests in `tests/test_dev_trust.py`

## Code Style

- **Python**: 3.10+
- **Formatter**: Black (line length 100)
- **Linter**: Ruff
- **Type hints**: Required for all function signatures
- **Docstrings**: Google style for all public methods

```bash
# Format code
black dev_trust/ tests/

# Lint
ruff check dev_trust/ tests/

# Type check
mypy dev_trust/
```

## Pull Request Process

1. Fork the repo and create a feature branch
2. Make your changes with tests
3. Ensure all tests pass: `pytest tests/`
4. Ensure code is formatted: `black dev_trust/ tests/`
5. Open a PR with a clear description of changes

## Reporting Issues

When reporting issues, please include:
- DevTrust version
- Python version
- Full error traceback
- Repository being analyzed (if applicable)
- Steps to reproduce
