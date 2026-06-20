# aesc - AI-powered security agent
# Runs inside Kali Linux with all penetration testing tools available
#
# BUILD OPTIMIZATION NOTES:
# - Layers are ordered from least-frequently-changed to most-frequently-changed
# - Kali tools layer (~2GB) is cached and only rebuilt if base image changes
# - Source code is copied LAST so code changes don't invalidate tool cache
# - Use BuildKit cache mounts for apt to speed up rebuilds

FROM kalilinux/kali-rolling:latest

# ============================================================================
# LAYER 1: System packages + Python (rarely changes)
# ============================================================================
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3.13 \
    python3-pip \
    python3.13-venv \
    git \
    curl \
    ca-certificates \
    libcap2-bin

# ============================================================================
# LAYER 2: Install uv (fast Python package manager) - rarely changes
# ============================================================================
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# ============================================================================
# LAYER 3: Kali security tools (LARGEST LAYER - cached aggressively)
# This layer takes 30-60 minutes to build but is cached unless base changes
# ============================================================================
# Choose your tool set by uncommenting ONE option:

# OPTION 1: kali-linux-default (~100 tools, ~11GB) - SLOW, includes bloat
# RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
#     --mount=type=cache,target=/var/lib/apt,sharing=locked \
#     apt-get update && \
#     DEBIAN_FRONTEND=noninteractive apt-get install -y \
#     kali-linux-default

# OPTION 2: Essential security tools (~1.5GB) - FAST BUILDS, no bloat
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    # Network scanning
    nmap masscan netcat-openbsd dnsutils whois iputils-ping net-tools \
    # Web testing
    nikto gobuster dirb ffuf wfuzz whatweb \
    # Vulnerability scanning
    sqlmap wpscan \
    # Password attacks
    hydra john hashcat wordlists \
    # Exploitation (optional - adds 500MB)
    metasploit-framework \
    # Utilities
    smbclient enum4linux crackmapexec \
    tcpdump wireshark-common binwalk \
    # Common dependencies
    openssh-client sshpass jq

# ============================================================================
# LAYER 4: Set tool capabilities (depends on tools layer)
# ============================================================================
# Kali's nmap package installs a wrapper at /usr/bin/nmap that execs
# /usr/lib/nmap/nmap. Capabilities must be set on the ACTUAL binary.
RUN for candidate in /usr/lib/nmap/nmap /usr/bin/nmap; do \
        if [ -f "$candidate" ] && file "$candidate" | grep -q ELF; then \
            setcap cap_net_raw,cap_net_admin,cap_net_bind_service+eip "$candidate" && \
            echo "Set capabilities on $candidate (nmap)"; \
        fi; \
    done && \
    MASSCAN_BIN=$(which masscan 2>/dev/null) && \
    if [ -n "$MASSCAN_BIN" ] && [ -f "$MASSCAN_BIN" ]; then \
        setcap cap_net_raw+eip "$MASSCAN_BIN" && \
        echo "Set capabilities on $MASSCAN_BIN"; \
    fi && \
    for tool in /usr/bin/hping3 /usr/bin/arping /usr/sbin/arp-scan; do \
        [ -f "$tool" ] && setcap cap_net_raw+eip "$tool" 2>/dev/null || true; \
    done

# ============================================================================
# LAYER 5: Create directories (rarely changes)
# ============================================================================
RUN mkdir -p /app /results /root/.config/aesc /home/aesc/.aesc /home/aesc/.cache && \
    chmod -R 777 /home/aesc /results

WORKDIR /app

# ============================================================================
# LAYER 6: Copy ONLY dependency files first (changes less often than code)
# ============================================================================
COPY pyproject.toml uv.lock ./

# ============================================================================
# LAYER 7: Install Python dependencies (cached if pyproject.toml unchanged)
# ============================================================================
ENV UV_HTTP_TIMEOUT=300
ENV UV_LINK_MODE=copy
ENV UV_NO_PROGRESS=1
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# Install Python dependencies (cached if pyproject.toml unchanged)
# LiteLLM and google-auth are now in pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# ============================================================================
# LAYER 8: Download MITRE ATT&CK data (cached, rarely needs update)
# ============================================================================
RUN mkdir -p /app/data/mitre-attack && \
    curl -fsSL --retry 3 --retry-delay 5 \
    "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack.json" \
    -o /app/data/mitre-attack/enterprise-attack.json && \
    echo "MITRE ATT&CK data downloaded ($(du -h /app/data/mitre-attack/enterprise-attack.json | cut -f1))"

# ============================================================================
# LAYER 9: Copy source code LAST (changes most frequently)
# ============================================================================
COPY src/ ./src/
COPY CHANGELOG.md README.md ./

# Ensure the source tree is readable when the container is run with `--user`
# (used by the benchmark harness to avoid root-owned outputs).
RUN chmod -R a+rX /app/src

# Create symlink for CHANGELOG
RUN ln -sf /app/CHANGELOG.md src/aesc/CHANGELOG.md

# ============================================================================
# LAYER 10: Patch and finalize (depends on source code)
# ============================================================================
# Patch kosong library to fix stream_options issue with non-streaming requests
RUN sed -i '89s|stream_options={"include_usage": True},|**({} if not self.stream else {"stream_options": {"include_usage": True}}),|' \
    .venv/lib/python*/site-packages/kosong/contrib/chat_provider/openai_legacy.py 2>/dev/null || true

# Patch LiteLLM to fix Vertex AI global location URL construction
# Bug: LiteLLM uses {location}-aiplatform.googleapis.com but for 'global'
# it should be aiplatform.googleapis.com (without location prefix)
COPY patches/litellm_global_location.py /tmp/
RUN python3 /tmp/litellm_global_location.py || echo "LiteLLM patch skipped"

# Install the project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# Verify key security tools
RUN echo "Verifying security tools..." && \
    (which nmap && nmap --version | head -1 || echo "nmap: not installed") && \
    (which sqlmap && echo "sqlmap: installed" || echo "sqlmap: not installed") && \
    echo "Tool verification completed"

# ============================================================================
# Environment and entrypoint
# ============================================================================
ENV PYTHONUNBUFFERED=1
ENV AESC_IN_DOCKER=1
ENV TERM=xterm-256color

ENTRYPOINT ["uv", "run", "aesc"]
CMD []

# Labels
LABEL org.opencontainers.image.title="aesc"
LABEL org.opencontainers.image.description="AI-powered security agent for penetration testing"
LABEL org.opencontainers.image.source="https://github.com/akaeli-aesc/aesc-cli"
LABEL org.opencontainers.image.licenses="Apache-2.0"