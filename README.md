# aesc

AI-powered security assistant for daily security operations.

Ask questions, run tools, automate workflows — in your terminal.

**by [akæli](https://akaeli.com)** | Open source | Privacy first

[![Version](https://img.shields.io/badge/version-0.1.0-blue)](https://github.com/akaeli-aesc/aesc-cli/releases)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Tests](https://github.com/akaeli-aesc/aesc-cli/actions/workflows/test.yml/badge.svg)](https://github.com/akaeli-aesc/aesc-cli/actions/workflows/test.yml)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ghcr.io-blue)](https://github.com/akaeli-aesc/aesc-cli/pkgs/container/aesc-cli)
[![Security](https://img.shields.io/badge/security-policy-red)](SECURITY.md)

**🔗 [akæli](https://akaeli.com)** — open-source AI security agent CLI

## What can you do with aesc?

### Daily Questions (Red & Blue Team)
```bash
aesc -c "Is this IP suspicious? Check reputation and recent activity"
aesc -c "Explain this log entry and suggest next steps"
aesc -c "What's the MITRE ATT&CK technique for credential dumping?"
```

### Offensive Operations
```bash
aesc -c "Scan this subnet and identify web servers"
aesc -c "Test this endpoint for SQL injection"
aesc -c "Run full recon on target.com"
```

### Defensive Analysis
```bash
aesc -c "Analyze these logs for lateral movement indicators"
aesc -c "What IOCs should I look for after this CVE?"
aesc -c "Create a detection rule for this technique"
```

### Automation
```bash
aesc -c "Generate a pentest report from today's session"
aesc -c "Run our standard external assessment methodology"
```

---

## Overview

aesc is an AI-powered CLI agent for security professionals. Describe what you need in plain English, aesc executes the methodology, you approve every action.

**Current Release:** v0.1.0 - First public release with core functionality

**Why "aesc"?** Short, memorable, and CLI-friendly. A simple, powerful name for a security tool.

## ⚠️ Security Notice

**aesc is designed for authorized security testing only.**

- ✅ **Always get authorization** before scanning/testing any system
- ✅ **Use the approval system** - review commands before execution
- ✅ **Follow responsible disclosure** practices
- ✅ **Comply with laws** and regulations

**Never:**
- ❌ Scan systems without permission
- ❌ Use for illegal activities
- ❌ Auto-approve on untrusted targets (`--yolo` is dangerous!)

**aesc is a powerful tool. Use it responsibly.**

See our [Security Policy](SECURITY.md) for vulnerability reporting.

## Features

- 🔒 **Privacy first** - Runs locally, your data never leaves your machine
- 🤖 **Natural language** - Describe tasks in plain English
- ✅ **Human approval** - Review every action before execution
- 🔧 **Kali toolset** - Access Kali's security tools via the bash tool
- 🌐 **Any LLM** - Ollama (free), OpenAI, Claude, Qwen, Gemini
- 🎯 **Red + Blue** - Offensive and defensive workflows
- 📊 **MITRE ATT&CK** - Framework-mapped operations
- 🐳 **Docker-based** - Isolated, reproducible environment
- 📝 **Session management** - Context-aware conversations

## Privacy First

aesc runs entirely on your machine. Your data never leaves your environment.

- **Local execution**: All tools run locally in Docker
- **Your LLM, your choice**: Use Ollama for 100% offline operation
- **Zero telemetry**: No data collection, no phone home
- **Open source**: Inspect every line of code (Apache 2.0)

## Quick Start

### Option 1: Docker Image (Recommended)

Pull and run the pre-built image from GitHub Container Registry:

```bash
# Pull the latest image
docker pull ghcr.io/akaeli-aesc/aesc-cli:latest

# Run interactively
docker run -it --rm \
  -e ANTHROPIC_API_KEY=your-key-here \
  -e AESC_MODEL_NAME=claude-sonnet-4-5-20250929 \
  ghcr.io/akaeli-aesc/aesc-cli:latest

# Or use specific version
docker pull ghcr.io/akaeli-aesc/aesc-cli:0.1.0
```

### Option 2: Wrapper Script (Easy)

Clone and use the wrapper script (auto-pulls Docker image):

```bash
git clone https://github.com/akaeli-aesc/aesc-cli.git
cd aesc-cli
./aesc                        # Auto-pulls image on first run
```

Then use it like any command:

```bash
./aesc                        # Interactive mode
./aesc -c "scan 192.168.1.1"  # Run a command
./aesc --help                 # Show help
```

### Option 3: Build from Source

Build the Docker image yourself:

```bash
git clone https://github.com/akaeli-aesc/aesc-cli.git
cd aesc-cli
docker build -t aesc:latest .
docker run -it --rm aesc:latest
```

**Prerequisites:** Docker installed ([Get Docker](https://docs.docker.com/get-docker/))

## Installation Options

### Using Docker Compose (Recommended for Development)

```bash
# Clone repository
git clone https://github.com/akaeli-aesc/aesc-cli.git
cd aesc-cli

# One-time setup (auto-detects your user ID)
./setup.sh

# Edit .env to add your API key
# Then run:
docker-compose run --rm aesc
```

**How it works:** `setup.sh` creates `.env` with your user ID. docker-compose automatically loads `.env`, so files are created with correct ownership. No manual exports needed!

### Direct Docker Usage

```bash
# Run with persistent config and results
docker run -it --rm \
  -v $(pwd)/results:/results \
  -v ~/.aesc:/root/.aesc \
  -e ANTHROPIC_API_KEY=your-key-here \
  ghcr.io/akaeli-aesc/aesc-cli:latest
```

📖 **See [Docker Usage Guide](docs/guides/docker-usage.mdx)** for detailed instructions:
- LLM configuration (Ollama, OpenAI, Claude)
- Network configuration options
- Volume mounting for persistence
- Security best practices

📖 **See [Troubleshooting Guide](docs/guides/troubleshooting.mdx)** for common issues:
- API key configuration
- Docker networking
- Performance tuning

## Configuration

### First Time Setup

1. **Set your API key:**

```bash
# Using Anthropic Claude (recommended)
export ANTHROPIC_API_KEY=sk-ant-your-key-here
export AESC_MODEL_NAME=claude-sonnet-4-5-20250929

# Or OpenAI
export OPENAI_API_KEY=sk-your-key-here
export AESC_MODEL_NAME=gpt-4

# Or local Ollama (free!)
export OLLAMA_BASE_URL=http://localhost:11434/v1
export AESC_MODEL_NAME=llama3
```

2. **Run aesc:**

```bash
./aesc                        # Interactive mode
```

### Configuration File

aesc stores configuration in `~/.aesc/config.json` (JSON format)

```json
{
  "providers": {
    "anthropic": {
      "type": "anthropic",
      "api_key": "sk-ant-..."
    },
    "ollama": {
      "type": "openai_legacy",
      "base_url": "http://localhost:11434/v1",
      "api_key": "ollama"
    }
  },
  "models": {
    "default": {
      "provider": "anthropic",
      "model": "claude-sonnet-4-5-20250929",
      "max_context_size": 200000
    }
  },
  "default_model": "default"
}
```

Interactive setup:
```bash
aesc
# Then use: /setup command
```

## Usage Examples

### Interactive Mode

```bash
aesc
> scan 192.168.1.1 for open ports
> analyze this web application for vulnerabilities
> help me enumerate subdomains of example.com
```

### Command Mode

```bash
# Network scanning
aesc -c "scan 192.168.1.0/24 and identify services"

# Web security
aesc -c "check example.com for common vulnerabilities"

# Auto-approve all actions (⚠️ use carefully!)
aesc --yolo -c "quick port scan of 192.168.1.1"

# Continue previous session
aesc --continue

# Save results
aesc -c "scan target.com and save report to /results/scan.txt"

# Query MITRE ATT&CK
aesc -c "lookup MITRE technique T1003"
aesc -c "what tactics does APT29 use?"

# Search Kali documentation
aesc -c "how do I use nmap for service detection?"
aesc -c "show me nikto usage examples"
```

### Advanced Usage

```bash
# Update to latest version
aesc --update

# Show configuration location
aesc --config

# Show results directory
aesc --results

# Run in specific directory
cd /path/to/target && aesc -c "analyze this project"
```

## Available Tools

### Currently Implemented ✅

- **bash** - Execute shell commands (with approval)
- **file operations** - Read, write, search files
- **web tools** - Fetch URLs, search the web
- **task management** - Organize work with todo lists
- **MITRE ATT&CK** - Query threat intelligence, techniques, tactics, and groups
- **Kali Docs** - Search official Kali Linux tool documentation
- **Results Manager** - Automatically collect and organize scan results

### Security Tools (via Kali Linux) 🐧

aesc runs inside Kali Linux with access to its security tools via the bash tool:

- **nmap** - Network discovery and security auditing
- **sqlmap** - Automatic SQL injection detection
- **metasploit** - Penetration testing framework
- **gobuster** - Directory/file/DNS enumeration
- **nikto** - Web server scanner
- **burpsuite** - Web vulnerability scanner
- **hydra** - Brute force tool
- **john** - Password cracker
- **wireshark** - Network protocol analyzer
- And the rest of Kali's toolset...

Currently accessed via the `bash` tool. Native integrations coming in future releases.

## Architecture

aesc is built on a clean, extensible architecture:

```
aesc/
├── soul/              # Agent runtime engine
│   ├── agent.py       # Agent loader
│   ├── runtime.py     # Execution loop
│   └── approval.py    # Security approval system
├── tools/             # Tool implementations
│   ├── bash/          # Command execution
│   ├── file/          # File operations
│   ├── web/           # Web tools
│   └── task/          # Task management
├── agents/            # Agent specifications
│   ├── default/       # Single-agent (general security assistant)
│   └── attack_chain/  # Multi-agent (orchestrator + 7 kill-chain sub-agents)
└── llm.py             # LLM abstraction layer
```

### Single-Agent vs Multi-Agent

aesc ships with two ready-to-run configurations, both selectable with `--agent-file`:

- **Single-agent** (default) — one general-purpose security agent with the full toolset:
  ```bash
  aesc                       # uses src/aesc/agents/default/agent.yaml
  ```
- **Multi-agent** — a kill-chain orchestrator that decomposes the objective and delegates to
  seven specialized sub-agents (reconnaissance → weaponization → delivery → exploitation →
  installation → C2 → actions) through the `Task` tool:
  ```bash
  aesc --agent-file src/aesc/agents/attack_chain/orchestrator/agent.yaml
  ```

Sub-agents are declared under `agent.subagents` in the orchestrator's `agent.yaml` (see the
[Agent Reference](docs/api-reference/agents.mdx)). Run both to compare a single broad agent
against orchestrated delegation on the same task. The specialized `Dockerfile.multi` stages
(`--target aesc-recon|aesc-exploit|aesc-c2|aesc-lateral|aesc-full`) provide matching toolsets.

**Based on:** [Kimi-CLI](https://github.com/MoonshotAI/kimi-cli) - Pure Python agent framework
**Enhancements:** Security focus, Kali Linux integration, penetration testing workflows

See the [Architecture Guide](docs/advanced/architecture.mdx) for detailed architecture documentation.

## Development

There are **two ways** to develop aesc:

### Option 1: Docker Development (Recommended)

**Best for:** Testing security features, working with Kali tools

```bash
# Clone repository
git clone https://github.com/akaeli-aesc/aesc-cli.git
cd aesc-cli

# Build Docker image
docker build -t aesc:dev .

# Run in development mode
docker run -it --rm \
  -v $(pwd):/opt/aesc \
  -v ~/.aesc:/root/.aesc \
  aesc:dev

# Or use docker-compose
docker-compose run --rm aesc
```

**Includes:**
- ✅ Kali Linux environment
- ✅ All security tools (nmap, sqlmap, etc.)
- ✅ Same environment as production

### Option 2: Local Python Development

**Best for:** Quick testing, running unit tests, code development

```bash
# Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/akaeli-aesc/aesc-cli.git
cd aesc-cli
uv sync

# Run locally (on your host machine)
uv run aesc
```

**Note:** ⚠️ This runs aesc on your **host machine** (not in Kali Docker):
- ✅ Good for: Testing agent logic, file operations, LLM interactions
- ❌ No Kali tools: Security tools like nmap, sqlmap won't be available
- ❌ Different environment: May behave differently than Docker version

**For security tool development, use Docker (Option 1).**

### Running Tests

```bash
# Run all tests (works locally)
uv run python -m pytest tests/ -v

# With coverage
uv run python -m pytest tests/ --cov=src/aesc

# Or in Docker
docker run --rm aesc:dev python -m pytest tests/ -v
```

### Adding a New Tool

1. Create tool module: `src/aesc/tools/mytool/__init__.py`
2. Implement the `CallableTool2` interface
3. Register the tool as a fully-qualified `"module.path:ClassName"` string in
   `src/aesc/agents/default/agent.yaml` (e.g. `"aesc.tools.mytool:MyTool"`)
4. Test in Docker: `docker run -it aesc:dev`

Example:
```python
from typing import ClassVar
from pydantic import BaseModel
from aesc.provider import CallableTool2, ToolReturnType
from aesc.tools.utils import ToolResultBuilder

class MyToolParams(BaseModel):
    target: str

class MyTool(CallableTool2[MyToolParams]):
    name: ClassVar[str] = "MyTool"
    description: ClassVar[str] = "Does something useful"
    params: ClassVar[type[MyToolParams]] = MyToolParams

    async def __call__(self, params: MyToolParams) -> ToolReturnType:
        builder = ToolResultBuilder()
        # Implementation here
        builder.write("done")
        return builder.ok("Completed", brief="Success")
```

Then add it to the agent's tool list:
```yaml
# src/aesc/agents/default/agent.yaml
agent:
  tools:
    - "aesc.tools.mytool:MyTool"  # Your new tool
```

**Testing your tool:**
```bash
# Build with your changes
docker build -t aesc:dev .

# Test interactively
docker run -it aesc:dev
> use my_tool on example.com
```

See the [Development Guide](docs/advanced/development.mdx) for a detailed contribution walkthrough.

## Documentation

### For Users
- [Docker Usage Guide](docs/guides/docker-usage.mdx) - Complete Docker instructions
- [Troubleshooting](docs/guides/troubleshooting.mdx) - Common issues and solutions
- [Development Guide](docs/advanced/development.mdx) - Setup and development workflow

### For Contributors
- [Development Guide](docs/advanced/development.mdx) - Workflow and best practices
- [Contributing Guide](docs/advanced/contributing.mdx) - Contribution guidelines
- [Architecture Guide](docs/advanced/architecture.mdx) - Project organization and internals

### Reference
- [Docker Usage Guide](docs/guides/docker-usage.mdx) - Docker reference
- [Architecture Guide](docs/advanced/architecture.mdx) - Technical deep dive

## Contributing

Contributions are welcome! aesc is open source and community-driven.

**Before contributing:**
1. Read the [Contributing Guide](docs/advanced/contributing.mdx) for project guidelines
2. Review the [Development Guide](docs/advanced/development.mdx)
3. Check existing issues and PRs
4. Follow the code style (ruff, pyright)

**To contribute:**
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes with tests
4. Submit a pull request to `main` branch

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

## License

Apache License 2.0 - See [LICENSE](LICENSE) file for details.

## Acknowledgments

aesc is forked from [Kimi-CLI](https://github.com/MoonshotAI/kimi-cli) by Moonshot Partners.

**Inherited from Kimi-CLI:**
- Agent framework architecture
- Tool system and dependency injection
- LLM abstraction layer
- Built-in approval system

**aesc additions by akaeli:**
- Security tool integrations
- Kali Linux optimization
- Security-focused workflows
- Penetration testing agent specifications
- Privacy-first architecture

Special thanks to the Kimi-CLI team for building a solid foundation.

## Support

- 🐛 **Issues:** [GitHub Issues](https://github.com/akaeli-aesc/aesc-cli/issues)
- 💬 **Discussions:** [GitHub Discussions](https://github.com/akaeli-aesc/aesc-cli/discussions)
- 📖 **Documentation:** [docs/](docs/) directory
- 🐳 **Docker Images:** [GitHub Container Registry](https://github.com/akaeli-aesc/aesc-cli/pkgs/container/aesc-cli)

## Links

- **Website:** https://akaeli.com
- **Repository:** https://github.com/akaeli-aesc/aesc-cli
- **Docker Images:** https://github.com/akaeli-aesc/aesc-cli/pkgs/container/aesc-cli
- **Releases:** https://github.com/akaeli-aesc/aesc-cli/releases
- **Security Policy:** [SECURITY.md](SECURITY.md)
- **Upstream:** https://github.com/MoonshotAI/kimi-cli

---

**Built by [akaeli](https://akaeli.com) for the security community**

*aesc - AI-powered security agent for ethical hackers*

Security & privacy first. Always.
