from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from aesc.config import Config, MoonshotSearchConfig, Services
from aesc.soul.approval import Approval
from aesc.tools.utils import ToolRejectedError
from aesc.tools.web.fetch import FetchURL
from aesc.tools.web.fetch import Params as FetchURLParams
from aesc.tools.web.search import Params as SearchWebParams
from aesc.tools.web.search import SearchWeb


@pytest.mark.asyncio
async def test_fetch_url_requires_approval():
    approval = Approval()

    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "FetchURL"
    mock_tool_call.id = "call_123"

    async def reject_request():
        req = await approval.fetch_request()
        req.reject()

    with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
        task = asyncio.create_task(reject_request())
        tool = FetchURL(approval=approval)
        result = await tool(FetchURLParams(url="https://example.com"))
        await task

    assert isinstance(result, ToolRejectedError)


@pytest.mark.asyncio
async def test_search_web_requires_approval():
    approval = Approval()

    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "SearchWeb"
    mock_tool_call.id = "call_123"

    config = Config(
        services=Services(
            moonshot_search=MoonshotSearchConfig(
                base_url="https://search.example/api",
                api_key=SecretStr("dummy"),
            )
        )
    )

    async def reject_request():
        req = await approval.fetch_request()
        req.reject()

    with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
        task = asyncio.create_task(reject_request())
        tool = SearchWeb(config=config, approval=approval)
        result = await tool(SearchWebParams(query="test", limit=1, include_content=False))
        await task

    assert isinstance(result, ToolRejectedError)
