# Attack Chain Protocol

Agents communicate through the results folder (`${AESC_RESULTS_DIR}`) using structured tools.

## As a Subagent

### WriteFinding
Call **immediately** when you discover something noteworthy:
- Open ports, running services
- Software versions, technologies
- Vulnerabilities (include CVE if known)
- Credentials, API keys, secrets
- Misconfigurations, exposures

```
WriteFinding(
  type="vulnerability",
  title="SQL Injection in login form",
  description="Parameter 'id' vulnerable to SQLi",
  severity="high",
  target="192.168.1.100",
  exploitable=true
)
```

### WriteDecision
Call when you need strategic guidance:
- Multiple viable attack paths exist
- Risk/reward tradeoff decision needed
- Unexpected situation encountered
- Unsure whether to proceed

The tool blocks until orchestrator/human responds (or timeout).

### ReadGuidance
Check **before major actions** for orchestrator directions. Adapt your approach based on guidance priority.

## Output Format

**Don't** generate lengthy JSON reports in your response.

**Do**:
1. Call `WriteFinding` for each discovery as you find it
2. Summarize key points in plain text
3. State what you did and recommend next steps
