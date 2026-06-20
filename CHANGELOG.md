# Changelog

All notable changes to aesc will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-12-02

First public release of aesc - AI-powered security agent for penetration testing.

### Added

- **Core Features**
  - Natural language interface for security operations
  - Built-in approval system with risk-based assessment
  - LLM-agnostic design (Ollama, OpenAI, Anthropic, and more)
  - Session management with context persistence

- **Security Tools**
  - SSH connection management (key and password auth)
  - SSH port forwarding for pivoting
  - Credential storage for discovered credentials
  - MITRE ATT&CK integration for threat intelligence
  - Kali documentation search

- **Agent System**
  - Attack chain agents (reconnaissance, exploitation, c2, etc.)
  - Modular agent architecture with YAML configuration
  - Subagent support for complex operations

- **User Interface**
  - Professional Textual-based TUI
  - Interactive approval panels
  - Tool call visualization with collapsible output
  - Theme detection for terminal compatibility

- **Infrastructure**
  - Docker support with Kali Linux base image
  - GitHub Actions for CI/CD
  - Comprehensive test suite

### Security

- Risk-based approval system (SAFE, LOW, MEDIUM, HIGH, CRITICAL)
- Audit logging for security operations
- Sensitive file protection in .gitignore

---

## Pre-release History

aesc is based on [Kimi-CLI](https://github.com/MoonshotAI/kimi-cli) by Moonshot AI.
For the complete upstream changelog, see the original project.
