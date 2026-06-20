Spawn a specialized subagent for a specific task. Subagent runs with fresh context but receives current findings summary.

**When to use:**
- Delegate attack chain stages (recon, exploit, etc.)
- Run independent tasks in parallel (call Task multiple times in one response)
- Keep main context clean for orchestration

**Parallel execution:** Multiple Task calls in same response run concurrently.

**Available Subagents:**

${SUBAGENTS_MD}
