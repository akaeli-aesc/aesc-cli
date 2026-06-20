from __future__ import annotations

from pathlib import Path

from inline_snapshot import snapshot


def test_pyinstaller_datas():
    from aesc.utils.pyinstaller import datas

    project_root = Path(__file__).parent.parent
    datas = [
        (
            Path(path)
            .relative_to(project_root)
            .as_posix()
            .replace(".venv/Lib/site-packages", ".venv/lib/python3.13/site-packages"),
            Path(dst).as_posix(),
        )
        for path, dst in datas
    ]

    assert sorted(datas) == snapshot(
        [
            (
                ".venv/lib/python3.13/site-packages/dateparser/data/dateparser_tz_cache.pkl",
                "dateparser/data",
            ),
            (
                ".venv/lib/python3.13/site-packages/fastmcp/../fastmcp-2.12.5.dist-info/INSTALLER",
                "fastmcp/../fastmcp-2.12.5.dist-info",
            ),
            (
                ".venv/lib/python3.13/site-packages/fastmcp/../fastmcp-2.12.5.dist-info/METADATA",
                "fastmcp/../fastmcp-2.12.5.dist-info",
            ),
            (
                ".venv/lib/python3.13/site-packages/fastmcp/../fastmcp-2.12.5.dist-info/RECORD",
                "fastmcp/../fastmcp-2.12.5.dist-info",
            ),
            (
                ".venv/lib/python3.13/site-packages/fastmcp/../fastmcp-2.12.5.dist-info/REQUESTED",
                "fastmcp/../fastmcp-2.12.5.dist-info",
            ),
            (
                ".venv/lib/python3.13/site-packages/fastmcp/../fastmcp-2.12.5.dist-info/WHEEL",
                "fastmcp/../fastmcp-2.12.5.dist-info",
            ),
            (
                ".venv/lib/python3.13/site-packages/fastmcp/../fastmcp-2.12.5.dist-info/entry_points.txt",
                "fastmcp/../fastmcp-2.12.5.dist-info",
            ),
            (
                ".venv/lib/python3.13/site-packages/fastmcp/../fastmcp-2.12.5.dist-info/licenses/LICENSE",
                "fastmcp/../fastmcp-2.12.5.dist-info/licenses",
            ),
            ("src/aesc/CHANGELOG.md", "aesc"),
            ("src/aesc/agents/_base/core.md", "aesc/agents/_base"),
            ("src/aesc/agents/_base/protocol.md", "aesc/agents/_base"),
            ("src/aesc/agents/_base/tools.md", "aesc/agents/_base"),
            (
                "src/aesc/agents/attack_chain/actions/agent.yaml",
                "aesc/agents/attack_chain/actions",
            ),
            (
                "src/aesc/agents/attack_chain/actions/system.md",
                "aesc/agents/attack_chain/actions",
            ),
            (
                "src/aesc/agents/attack_chain/c2/agent.yaml",
                "aesc/agents/attack_chain/c2",
            ),
            (
                "src/aesc/agents/attack_chain/c2/system.md",
                "aesc/agents/attack_chain/c2",
            ),
            (
                "src/aesc/agents/attack_chain/delivery/agent.yaml",
                "aesc/agents/attack_chain/delivery",
            ),
            (
                "src/aesc/agents/attack_chain/delivery/system.md",
                "aesc/agents/attack_chain/delivery",
            ),
            (
                "src/aesc/agents/attack_chain/exploitation/agent.yaml",
                "aesc/agents/attack_chain/exploitation",
            ),
            (
                "src/aesc/agents/attack_chain/exploitation/system.md",
                "aesc/agents/attack_chain/exploitation",
            ),
            (
                "src/aesc/agents/attack_chain/installation/agent.yaml",
                "aesc/agents/attack_chain/installation",
            ),
            (
                "src/aesc/agents/attack_chain/installation/system.md",
                "aesc/agents/attack_chain/installation",
            ),
            (
                "src/aesc/agents/attack_chain/orchestrator/agent.yaml",
                "aesc/agents/attack_chain/orchestrator",
            ),
            (
                "src/aesc/agents/attack_chain/orchestrator/system.md",
                "aesc/agents/attack_chain/orchestrator",
            ),
            (
                "src/aesc/agents/attack_chain/reconnaissance/agent.yaml",
                "aesc/agents/attack_chain/reconnaissance",
            ),
            (
                "src/aesc/agents/attack_chain/reconnaissance/system.md",
                "aesc/agents/attack_chain/reconnaissance",
            ),
            (
                "src/aesc/agents/attack_chain/shared/results_tools.md",
                "aesc/agents/attack_chain/shared",
            ),
            (
                "src/aesc/agents/attack_chain/weaponization/agent.yaml",
                "aesc/agents/attack_chain/weaponization",
            ),
            (
                "src/aesc/agents/attack_chain/weaponization/system.md",
                "aesc/agents/attack_chain/weaponization",
            ),
            ("src/aesc/agents/default/agent.yaml", "aesc/agents/default"),
            ("src/aesc/agents/default/sub.yaml", "aesc/agents/default"),
            ("src/aesc/agents/default/system.md", "aesc/agents/default"),
            ("src/aesc/agents/dfir/agent.yaml", "aesc/agents/dfir"),
            ("src/aesc/agents/dfir/system.md", "aesc/agents/dfir"),
            (
                "src/aesc/agents/memory_analysis/agent.yaml",
                "aesc/agents/memory_analysis",
            ),
            (
                "src/aesc/agents/memory_analysis/system.md",
                "aesc/agents/memory_analysis",
            ),
            (
                "src/aesc/agents/reverse_engineering/agent.yaml",
                "aesc/agents/reverse_engineering",
            ),
            (
                "src/aesc/agents/reverse_engineering/system.md",
                "aesc/agents/reverse_engineering",
            ),
            ("src/aesc/agents/wireless/agent.yaml", "aesc/agents/wireless"),
            ("src/aesc/agents/wireless/system.md", "aesc/agents/wireless"),
            ("src/aesc/deps/bin/rg", "aesc/deps/bin"),
            ("src/aesc/prompts/compact.md", "aesc/prompts"),
            ("src/aesc/prompts/init.md", "aesc/prompts"),
            ("src/aesc/tools/bash/bash.md", "aesc/tools/bash"),
            ("src/aesc/tools/bash/cmd.md", "aesc/tools/bash"),
            ("src/aesc/tools/dmail/dmail.md", "aesc/tools/dmail"),
            ("src/aesc/tools/file/glob.md", "aesc/tools/file"),
            ("src/aesc/tools/file/grep.md", "aesc/tools/file"),
            ("src/aesc/tools/file/patch.md", "aesc/tools/file"),
            ("src/aesc/tools/file/read.md", "aesc/tools/file"),
            ("src/aesc/tools/file/replace.md", "aesc/tools/file"),
            ("src/aesc/tools/file/write.md", "aesc/tools/file"),
            ("src/aesc/tools/ssh/connect.md", "aesc/tools/ssh"),
            ("src/aesc/tools/ssh/download.md", "aesc/tools/ssh"),
            ("src/aesc/tools/ssh/exec.md", "aesc/tools/ssh"),
            ("src/aesc/tools/ssh/portforward.md", "aesc/tools/ssh"),
            ("src/aesc/tools/ssh/upload.md", "aesc/tools/ssh"),
            ("src/aesc/tools/task/task.md", "aesc/tools/task"),
            ("src/aesc/tools/think/think.md", "aesc/tools/think"),
            ("src/aesc/tools/todo/set_todo_list.md", "aesc/tools/todo"),
            ("src/aesc/tools/web/fetch.md", "aesc/tools/web"),
            ("src/aesc/tools/web/search.md", "aesc/tools/web"),
        ]
    )


def test_pyinstaller_hiddenimports():
    from aesc.utils.pyinstaller import hiddenimports

    assert sorted(hiddenimports) == snapshot(
        [
            "aesc.tools",
            "aesc.tools.bash",
            "aesc.tools.creds",
            "aesc.tools.dmail",
            "aesc.tools.file",
            "aesc.tools.file.glob",
            "aesc.tools.file.grep",
            "aesc.tools.file.patch",
            "aesc.tools.file.read",
            "aesc.tools.file.replace",
            "aesc.tools.file.write",
            "aesc.tools.intel",
            "aesc.tools.kali_docs",
            "aesc.tools.kali_docs.clone",
            "aesc.tools.kali_docs.search",
            "aesc.tools.mcp",
            "aesc.tools.mitre_attack",
            "aesc.tools.mitre_attack.cache",
            "aesc.tools.mitre_attack.query",
            "aesc.tools.process_registry",
            "aesc.tools.results",
            "aesc.tools.results.schemas",
            "aesc.tools.ssh",
            "aesc.tools.task",
            "aesc.tools.think",
            "aesc.tools.todo",
            "aesc.tools.utils",
            "aesc.tools.web",
            "aesc.tools.web.fetch",
            "aesc.tools.web.search",
        ]
    )
