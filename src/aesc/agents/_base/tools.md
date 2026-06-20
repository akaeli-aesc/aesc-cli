# Tool Usage Guide

## Lookup Before Executing

Don't guess syntax. Use reference tools:

- **KaliDocs**: `KaliDocs("nmap service version detection")`
- **MitreAttack**: `MitreAttack("initial access techniques")`

## Essential Patterns

Save all outputs to the results directory (`${AESC_RESULTS_DIR}`).

### Network Reconnaissance
```bash
# Fast port discovery
nmap -sS -p- --min-rate=5000 TARGET -oN ${AESC_RESULTS_DIR}/ports_TARGET.txt

# Service/version detection (on discovered ports)
nmap -sV -sC -p PORTS TARGET -oN ${AESC_RESULTS_DIR}/services_TARGET.txt
```

### Web Enumeration
```bash
# Directory discovery
gobuster dir -u URL -w /usr/share/wordlists/dirb/common.txt -o ${AESC_RESULTS_DIR}/dirs.txt

# Technology fingerprinting
whatweb URL
```

### Vulnerability Scanning
```bash
# Fast vuln scan
nuclei -u URL -t cves/ -o ${AESC_RESULTS_DIR}/vulns.txt
```

## Tool Timeouts

Long-running tools (nmap full scan, nikto, sqlmap) have 5-minute timeouts. For extensive scans, break into smaller chunks.

## Parallel Execution

When scans are independent, run them in parallel to save time. Example: port scan + DNS enumeration can run simultaneously.
