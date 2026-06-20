from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from aesc.config import Config
from aesc.llm import LLM
from aesc.session import Session
from aesc.soul.approval import Approval
from aesc.soul.denwarenji import DenwaRenji
from aesc.utils.logging import logger


class BuiltinSystemPromptArgs(NamedTuple):
    """Builtin system prompt arguments."""

    AESC_NOW: str
    """The current datetime."""
    AESC_WORK_DIR: Path
    """The current working directory."""
    AESC_WORK_DIR_LS: str
    """The directory listing of current working directory."""
    AESC_RESULTS_DIR: Path
    """Session-specific results directory for saving findings."""
    AESC_SESSION_ID: str
    """The current session ID."""


def _list_work_dir(work_dir: Path) -> str:
    if sys.platform == "win32":
        ls = subprocess.run(
            ["cmd", "/c", "dir", work_dir],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    else:
        ls = subprocess.run(
            ["ls", "-la", work_dir],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    return ls.stdout.strip()


@dataclass
class Runtime:
    """Agent runtime."""

    config: Config
    llm: LLM | None
    session: Session
    builtin_args: BuiltinSystemPromptArgs
    denwa_renji: DenwaRenji
    approval: Approval

    def set_llm(self, llm: LLM) -> None:
        """Update the LLM instance (used by /setup for hot-reload)."""
        self.llm = llm
        logger.info("Runtime LLM updated to: {model}", model=llm.model_name)

    @staticmethod
    async def create(
        config: Config,
        llm: LLM | None,
        session: Session,
        yolo: bool,
    ) -> Runtime:
        ls_output = await asyncio.to_thread(_list_work_dir, session.work_dir)

        return Runtime(
            config=config,
            llm=llm,
            session=session,
            builtin_args=BuiltinSystemPromptArgs(
                AESC_NOW=datetime.now().astimezone().isoformat(),
                AESC_WORK_DIR=session.work_dir,
                AESC_WORK_DIR_LS=ls_output,
                AESC_RESULTS_DIR=session.results_dir,
                AESC_SESSION_ID=session.id,
            ),
            denwa_renji=DenwaRenji(),
            approval=Approval(yolo=yolo),
        )
