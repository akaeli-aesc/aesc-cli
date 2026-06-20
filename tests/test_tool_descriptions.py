from __future__ import annotations

# ruff: noqa

import platform
import pytest
from inline_snapshot import snapshot

from aesc.tools.bash import Bash
from aesc.tools.dmail import SendDMail
from aesc.tools.file.glob import Glob
from aesc.tools.file.grep import Grep
from aesc.tools.file.patch import PatchFile
from aesc.tools.file.read import ReadFile
from aesc.tools.file.replace import StrReplaceFile
from aesc.tools.file.write import WriteFile
from aesc.tools.task import Task
from aesc.tools.think import Think
from aesc.tools.todo import SetTodoList
from aesc.tools.web.fetch import FetchURL
from aesc.tools.web.search import SearchWeb


def test_task_description(task_tool: Task):
    """Test the description of Task tool."""
    assert task_tool.base.description == snapshot(
        """\
Spawn a specialized subagent for a specific task. Subagent runs with fresh context but receives current findings summary.

**When to use:**
- Delegate attack chain stages (recon, exploit, etc.)
- Run independent tasks in parallel (call Task multiple times in one response)
- Keep main context clean for orchestration

**Parallel execution:** Multiple Task calls in same response run concurrently.

**Available Subagents:**

- `coder`: Good at general software engineering tasks.
- `reconnaissance`: Red Team reconnaissance specialist. Delegate when you need:
- Port scanning and service enumeration (nmap, masscan)
- Web application fingerprinting (whatweb, nikto)
- Subdomain and DNS enumeration
- Vulnerability scanning (nuclei)
- OSINT gathering
Returns findings via WriteFinding. Check with ReadFindings after.

- `weaponization`: Red Team weaponization specialist. Delegate when you need:
- Exploit selection (searchsploit, metasploit search)
- Payload generation (msfvenom)
- Custom exploit modification
- Evasion technique implementation
Requires reconnaissance findings as input.

- `delivery`: Red Team delivery specialist. Delegate when you need:
- Exploit delivery (web, network)
- Listener setup (metasploit, netcat)
- Initial access establishment
- Callback verification
Requires weaponization output as input.

- `exploitation`: Red Team exploitation specialist. Delegate when you need:
- Post-exploitation enumeration
- Privilege escalation (Linux/Windows)
- Credential harvesting (mimikatz, hashdump)
- Internal reconnaissance
Requires active session from delivery.

- `installation`: Red Team persistence specialist. Delegate when you need:
- Backdoor installation (SSH keys, services, cron)
- Persistence mechanisms
- Defense evasion
Requires elevated access from exploitation.

- `c2`: Red Team C2 specialist. Delegate when you need:
- C2 channel setup (metasploit, chisel, ligolo)
- Pivoting and tunneling
- SOCKS proxy configuration
- Session management
Use after establishing persistence.

- `actions`: Red Team actions specialist. Delegate when you need:
- Lateral movement (pass-the-hash, SSH keys)
- Data discovery and collection
- Data exfiltration
- Impact demonstration
- Final reporting
Use after C2 is established.

"""
    )


def test_send_dmail_description(send_dmail_tool: SendDMail):
    """Test the description of SendDMail tool."""
    assert send_dmail_tool.base.description == snapshot(
        """\
Send a message to the past, just like sending a D-Mail in Steins;Gate.

You can see some `user` messages with `CHECKPOINT {checkpoint_id}` wrapped in `<system>` tags in the context. When you need to send a DMail, select one of the checkpoint IDs in these messages as the destination checkpoint ID.

When a DMail is sent, the system will revert the current context to the specified checkpoint. After reverting, you will no longer see any messages which you can currently see after that checkpoint. The message in the DMail will be appended to the end of the context. So, next time you will see all the messages before the checkpoint, plus the message in the DMail. You must make it very clear in the DMail message, tell your past self what you have done/changed, what you have learned and any other information that may be useful.

When sending a DMail, DO NOT do much explanation to the user. The user do not care about this. Just explain to your past self.

Here are some typical scenarios you may want to send a DMail:

- You read a file, found it very large and most of the content is not relevant to the current task. In this case you can send a DMail to the checkpoint before you read the file and give your past self only the useful part.
- You searched the web, found the result very large.
  - If you got what you need, you may send a DMail to the checkpoint before you searched the web and give your past self the useful part.
  - If you did not get what you need, you may send a DMail to tell your past self to try another query.
- You wrote some code and it did not work as expected. You spent many struggling steps to fix it but the process is not relevant to the ultimate goal. In this case you can send a DMail to the checkpoint before you wrote the code and give your past self the fixed version of the code and tell yourself no need to write it again because you already wrote to the filesystem.
"""
    )


def test_think_description(think_tool: Think):
    """Test the description of Think tool."""
    assert think_tool.base.description == snapshot(
        "Use the tool to think about something. It will not obtain new information or change the database, but just append the thought to the log. Use it when complex reasoning or some cache memory is needed.\n"
    )


def test_set_todo_list_description(set_todo_list_tool: SetTodoList):
    """Test the description of SetTodoList tool."""
    assert set_todo_list_tool.base.description == snapshot(
        """\
Update todo list for tracking multi-step tasks.

Use when task has multiple subtasks/milestones. Update status as you complete items.

**Don't use for:** Simple questions, single-step tasks, trivial operations.
"""
    )


@pytest.mark.skipif(platform.system() == "Windows", reason="Skipping test on Windows")
def test_bash_description(bash_tool: Bash):
    """Test the description of Bash tool."""
    assert bash_tool.base.description == snapshot(
        """\
Execute shell commands. Returns stdout+stderr combined, truncated if too long.

**Rules:**
- Fresh shell each call (no state preserved)
- Set `timeout` for long-running commands (network tools auto-get 5min)
- Chain commands: `&&` (sequential), `;` (ignore errors), `|` (pipe)
- Quote paths with spaces: `"/path with spaces/"`
- **Output limit:** ~12,000 chars. Commands producing more will be killed. Pipe through `head -n N`, `tail -n N`, or `grep` to select relevant sections.

**Security tools available:** nmap, nikto, gobuster, sqlmap, hydra, metasploit, etc.
"""
    )


def test_read_file_description(read_file_tool: ReadFile):
    """Test the description of ReadFile tool."""
    assert read_file_tool.base.description == snapshot(
        """\
Read file content. Returns with line numbers (cat -n format).

**Tips:**
- Use `line_offset` and `n_lines` for partial reads
- Max 1000 lines, truncates lines > 2000 chars
- Read multiple files in parallel when possible
- For searching content, prefer Grep tool
"""
    )


def test_glob_description(glob_tool: Glob):
    """Test the description of Glob tool."""
    assert glob_tool.base.description == snapshot(
        """\
Find files using glob patterns. Supports `*`, `?`, `**` (recursive).

**Examples:**
- `*.py` - Python files in current dir
- `src/**/*.js` - JS files recursively in src/
- `test_*.py` - Test files

**Avoid:** `**/*.py` (too broad), `node_modules/**` (too large)
"""
    )


def test_grep_description(grep_tool: Grep):
    """Test the description of Grep tool."""
    assert grep_tool.base.description == snapshot(
        "Search files using ripgrep. Use this instead of bash grep/rg. Escape braces: `\\\\{`\n"
    )


def test_write_file_description(write_file_tool: WriteFile):
    """Test the description of WriteFile tool."""
    assert write_file_tool.base.description == snapshot(
        "Write content to file. Default mode: overwrite. Use append mode for large content.\n"
    )


def test_str_replace_file_description(str_replace_file_tool: StrReplaceFile):
    """Test the description of StrReplaceFile tool."""
    assert str_replace_file_tool.base.description == snapshot(
        """\
Replace specific strings within a specified file.

**Tips:**
- Only use this tool on text files.
- Multi-line strings are supported.
- Can specify a single edit or a list of edits in one call.
- You should prefer this tool over WriteFile tool and Bash `sed` command.
"""
    )


def test_patch_file_description(patch_file_tool: PatchFile):
    """Test the description of PatchFile tool."""
    assert patch_file_tool.base.description == snapshot(
        """\
Apply a unified diff patch to a file.

**Tips:**
- The patch must be in unified diff format, the format used by `diff -u` and `git diff`.
- Only use this tool on text files.
- The tool will fail with error returned if the patch doesn't apply cleanly.
- The file must exist before applying the patch.
- You should prefer this tool over WriteFile tool and Bash `sed` command when editing an existing file.
"""
    )


def test_search_web_description(search_web_tool: SearchWeb):
    """Test the description of MoonshotSearch tool."""
    assert search_web_tool.base.description == snapshot(
        "WebSearch tool allows you to search on the internet to get latest information, including news, documents, release notes, blog posts, papers, etc.\n"
    )


def test_fetch_url_description(fetch_url_tool: FetchURL):
    """Test the description of FetchURL tool."""
    assert fetch_url_tool.base.description == snapshot(
        "Fetch a web page from a URL and extract main text content from it.\n"
    )
