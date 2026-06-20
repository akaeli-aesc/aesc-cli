from __future__ import annotations

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = collect_submodules("aesc.tools")
datas = (
    collect_data_files(
        "aesc",
        includes=[
            "agents/**/*.yaml",
            "agents/**/*.md",
            "deps/bin/**",
            "prompts/**/*.md",
            "tools/**/*.md",
            "CHANGELOG.md",
        ],
    )
    + collect_data_files(
        "dateparser",
        includes=["**/*.pkl"],
    )
    + collect_data_files(
        "fastmcp",
        includes=["../fastmcp-*.dist-info/*"],
    )
)
