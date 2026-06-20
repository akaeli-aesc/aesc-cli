# Setup Instructions

## First Time Setup

1. **Copy the example docker-compose file:**
   ```bash
   cp docker-compose.example.yml docker-compose.yml
   ```

2. **Edit `docker-compose.yml` and add your API key:**
   ```yaml
   environment:
     # For Claude Sonnet 4.5:
     - ANTHROPIC_API_KEY=sk-ant-your-key-here
     - AESC_MODEL_NAME=claude-sonnet-4-5-20250929

     # For OpenAI:
     # - OPENAI_API_KEY=sk-your-key-here
     # - AESC_MODEL_NAME=gpt-4

     # For Ollama (local):
     # - OLLAMA_HOST=http://host.docker.internal:11434
     # - AESC_MODEL_NAME=llama3.1
   ```

3. **Build and run:**
   ```bash
   docker build -t aesc:latest .
   docker-compose run --rm aesc
   ```

## Security Note

⚠️ **Important:** Your `docker-compose.yml` file contains API keys and is gitignored. Never commit it to version control!

## Quick Test

```bash
# Test aesc is working
docker-compose run --rm aesc --version

# Run interactively
docker-compose run --rm aesc

# Run a command
docker-compose run --rm aesc -c "what tools are available?"
```

## See Also

- [README.md](README.md) - Project overview
- [docs/DOCKER_USAGE.md](docs/DOCKER_USAGE.md) - Comprehensive Docker guide
