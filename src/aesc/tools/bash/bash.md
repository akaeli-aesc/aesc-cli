Execute shell commands. Returns stdout+stderr combined, truncated if too long.

**Rules:**
- Fresh shell each call (no state preserved)
- Set `timeout` for long-running commands (network tools auto-get 5min)
- Chain commands: `&&` (sequential), `;` (ignore errors), `|` (pipe)
- Quote paths with spaces: `"/path with spaces/"`
- **Output limit:** ~12,000 chars. Commands producing more will be killed. Pipe through `head -n N`, `tail -n N`, or `grep` to select relevant sections.

**Security tools available:** nmap, nikto, gobuster, sqlmap, hydra, metasploit, etc.
