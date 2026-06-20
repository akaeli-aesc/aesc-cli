# Security Policy

## Our Commitment

At akaeli, security and privacy are core to everything we build. aesc is designed for authorized security testing, and we take the security of our tools seriously.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We appreciate responsible disclosure of security vulnerabilities.

### How to Report

**Email:** open-dev@akæli.com
**PGP Key:** *(coming soon)*

**Please include:**
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if available)

### Response Timeline

- **Initial response:** Within 48 hours
- **Status update:** Within 7 days
- **Fix timeline:** Depends on severity
  - Critical: Within 7 days
  - High: Within 30 days
  - Medium: Within 60 days
  - Low: Within 90 days

### Responsible Disclosure

We follow a 90-day responsible disclosure timeline:

1. You report the vulnerability privately
2. We confirm receipt and assess severity
3. We develop and test a fix
4. We release a patched version
5. After 90 days (or earlier if agreed), public disclosure

### What We Ask

- Give us reasonable time to fix the issue before public disclosure
- Make a good faith effort to avoid privacy violations and data destruction
- Don't exploit the vulnerability beyond what's necessary to demonstrate it

### Recognition

We maintain a security researchers hall of fame for responsible disclosures. With your permission, we'll credit you in:

- Release notes
- Security advisories
- Our website (https://akaeli.com)

## Security Best Practices

When using aesc:

1. **Always get authorization** before testing any system
2. **Use the approval system** - review commands before execution
3. **Keep aesc updated** - security patches are released regularly
4. **Protect your API keys** - never commit them to version control
5. **Use isolated environments** - run aesc in Docker containers
6. **Follow the law** - comply with all applicable regulations

## Security Features

aesc includes security-conscious design:

- **Approval system:** Review commands before execution
- **No auto-execution:** Never runs commands without explicit approval (except in `--yolo` mode)
- **Containerized:** Runs in isolated Docker environment
- **LLM-agnostic:** Use local models (Ollama) for sensitive work
- **Open source:** Auditable code, Apache 2.0 license

## Scope

### In Scope

- aesc CLI tool and core functionality
- Docker images and containers
- GitHub repository and CI/CD
- Documentation and examples

### Out of Scope

- Third-party tools (nmap, sqlmap, etc.) - report to upstream
- LLM providers (OpenAI, Anthropic, etc.) - report to them
- Docker/Kali base images - report to upstream

## Security Advisories

Published security advisories: https://github.com/akaeli-aesc/aesc-cli/security/advisories

## Contact

For non-security issues, use GitHub Issues: https://github.com/akaeli-aesc/aesc-cli/issues

For security concerns only: open-dev@akæli.com

---

**Thank you for helping keep aesc and our users safe!**

*Last updated: November 15, 2024*
