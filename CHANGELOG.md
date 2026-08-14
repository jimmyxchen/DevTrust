# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2024-01-01

### Added
- Initial release of DevTrust
- 8 detection signals:
  - Timing Burst Detector - detects coordinated star-burst campaigns
  - Account Age Detector - flags throwaway accounts
  - User Activity Detector - analyzes genuine GitHub engagement
  - Creation Cluster Detector - DBSCAN clustering of account creation dates
  - Cross-Repository Detector - co-starring pattern analysis
  - Network Detector - social graph analysis
  - Commit Depth Detector - code contribution quality
  - Behavioral Pattern Detector - machine-like behavior detection
- Weighted scoring engine combining all signals
- Rich terminal output with color-coded reports
- CLI interface with Click
- File-based caching with 24h TTL
- Multiple output formats (text, JSON, Markdown)
- Comprehensive test suite with pytest
