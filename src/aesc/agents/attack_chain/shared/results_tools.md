## Results Tools (Agent Communication)

You communicate with the orchestrator through the results folder (`${AESC_RESULTS_DIR}`). This enables coordinated operations where the orchestrator can review your findings and provide guidance.

### Your Tools

- **WriteFinding**: Record discoveries (ports, services, vulnerabilities, credentials)
- **WriteDecision**: Request guidance when facing strategic choices
- **ReadGuidance**: Check for orchestrator's directions before major actions

### When to Use Each Tool

#### WriteFinding
Call this whenever you discover something noteworthy:
- Open ports and services
- Vulnerabilities (with severity)
- Credentials or sensitive data
- Network topology information
- Potential attack vectors

```
WriteFinding(
    type="vulnerability",
    title="SQL Injection in login form",
    description="The login form is vulnerable to SQL injection...",
    severity="critical",
    target="192.168.1.10",
    evidence="sqlmap output showing database dump",
    mitre_technique="T1190",
    exploitable=True,
    next_steps=["Attempt to dump credentials", "Check for admin access"]
)
```

#### WriteDecision
Call this when you face a choice that needs strategic input:
- Multiple attack paths available
- Risk/reward tradeoffs
- Scope questions (should I expand beyond current target?)
- Tool selection for sensitive operations

```
WriteDecision(
    type="priority",
    question="Found 3 vulnerabilities. Which should I exploit first?",
    context="The target has SQLi (web), outdated SSH, and weak SMB creds",
    options=[
        {"id": "A", "title": "SQLi", "description": "Web-based, likely detected", "risk_level": "medium"},
        {"id": "B", "title": "SSH", "description": "Kernel exploit, may crash system", "risk_level": "high"},
        {"id": "C", "title": "SMB", "description": "Stealthy, credential reuse", "risk_level": "low"}
    ],
    recommended="C",
    recommendation_reason="SMB is stealthiest and gives domain access"
)
```

#### ReadGuidance
Call this before starting major actions to check for orchestrator directions:
- At the beginning of your task
- Before pivoting to a new target
- When choosing between multiple approaches

```
ReadGuidance(agent_name="reconnaissance", stage=1)
```

### Communication Best Practices

1. **Write findings early and often** - Don't wait until the end
2. **Be specific in findings** - Include evidence and next steps
3. **Ask for decisions on strategic choices** - Don't guess on high-impact decisions
4. **Check guidance before pivoting** - The orchestrator may have new priorities
5. **Include MITRE technique IDs** - Helps with final reporting
