#!/bin/bash
# aesc One-Line Installer
# Usage: curl -fsSL akaeli.com/install.sh | bash

set -e

echo "🚀 Installing aesc - AI-powered security agent"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Detect OS
OS="$(uname -s)"
case "$OS" in
    Linux*)     OS_TYPE=linux;;
    Darwin*)    OS_TYPE=mac;;
    *)          OS_TYPE=unknown;;
esac

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker is not installed${NC}"
    echo ""
    echo "Please install Docker first:"
    case "$OS_TYPE" in
        linux)
            echo "  Ubuntu/Debian: sudo apt-get install docker.io"
            echo "  Or visit: https://docs.docker.com/engine/install/"
            ;;
        mac)
            echo "  Visit: https://docs.docker.com/desktop/install/mac-install/"
            ;;
        *)
            echo "  Visit: https://docs.docker.com/get-docker/"
            ;;
    esac
    exit 1
fi

echo -e "${GREEN}✅ Docker found${NC}"

# Determine install location
if [ -w /usr/local/bin ]; then
    INSTALL_DIR="/usr/local/bin"
elif [ -w "$HOME/.local/bin" ]; then
    INSTALL_DIR="$HOME/.local/bin"
    mkdir -p "$INSTALL_DIR"
else
    INSTALL_DIR="$HOME/bin"
    mkdir -p "$INSTALL_DIR"
fi

AESC_BIN="$INSTALL_DIR/aesc"

# Download aesc wrapper script
echo ""
echo -e "${BLUE}📥 Downloading aesc CLI...${NC}"
if command -v curl &> /dev/null; then
    curl -fsSL akaeli.com/aesc -o "$AESC_BIN"
elif command -v wget &> /dev/null; then
    wget -q akaeli.com/aesc -O "$AESC_BIN"
else
    echo -e "${RED}Error: Neither curl nor wget found${NC}"
    exit 1
fi

chmod +x "$AESC_BIN"

# Pull Docker image
echo -e "${BLUE}📦 Downloading aesc Docker image (~1GB, first time only)...${NC}"
docker pull ghcr.io/akaeli-aesc/aesc-cli:latest

echo ""
echo -e "${GREEN}✅ aesc installed successfully!${NC}"
echo ""
echo "📍 Installed to: $AESC_BIN"
echo ""

# Check if in PATH
if ! echo "$PATH" | grep -q "$INSTALL_DIR"; then
    echo -e "${YELLOW}⚠️  $INSTALL_DIR is not in your PATH${NC}"
    echo ""
    echo "Add this to your ~/.bashrc or ~/.zshrc:"
    echo "  export PATH=\"\$PATH:$INSTALL_DIR\""
    echo ""
    echo "Then run: source ~/.bashrc"
    echo ""
fi

# Show usage
echo "🚀 Quick Start:"
echo ""
echo "  1. Set your API key:"
echo "     export ANTHROPIC_API_KEY=sk-ant-..."
echo "     export AESC_MODEL_NAME=claude-sonnet-4-5-20250929"
echo ""
echo "  2. Run aesc:"
echo "     aesc                          # Interactive mode"
echo "     aesc -c \"scan 192.168.1.1\"     # Run a command"
echo "     aesc --help                   # Show help"
echo ""
echo "📖 Documentation: https://github.com/akaeli-aesc/aesc-cli"
echo ""

# Offer to add API key
echo -e "${YELLOW}💡 Configure API key now? (y/n)${NC}"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    echo ""
    echo "Enter your Anthropic API key (or press Enter to skip):"
    read -r api_key
    if [ -n "$api_key" ]; then
        SHELL_RC=""
        if [ -f "$HOME/.bashrc" ]; then
            SHELL_RC="$HOME/.bashrc"
        elif [ -f "$HOME/.zshrc" ]; then
            SHELL_RC="$HOME/.zshrc"
        fi

        if [ -n "$SHELL_RC" ]; then
            echo "" >> "$SHELL_RC"
            echo "# aesc Configuration" >> "$SHELL_RC"
            echo "export ANTHROPIC_API_KEY=\"$api_key\"" >> "$SHELL_RC"
            echo "export AESC_MODEL_NAME=\"claude-sonnet-4-5-20250929\"" >> "$SHELL_RC"
            echo ""
            echo -e "${GREEN}✅ Added to $SHELL_RC${NC}"
            echo "Run: source $SHELL_RC"
        fi
    fi
fi

echo ""
echo -e "${GREEN}Ready to hack! Run 'aesc' to get started 🔓${NC}"
