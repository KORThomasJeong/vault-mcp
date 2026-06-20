import json

import pytest
from fastmcp import Client

from vault_mcp.config import Config
from vault_mcp.server import build_server


@pytest.fixture
def config(tmp_path):
    (tmp_path / "30-Resources" / "AI").mkdir(parents=True)
    (tmp_path / "01-Inbox").mkdir()
    (tmp_path / "30-Resources" / "AI" / "_whitelist.yaml").write_text(
        "categories:\n  MCP:\n    description: Model Context Protocol.\nfallback: General\n",
        encoding="utf-8",
    )
    env = {"VAULT_PATH": str(tmp_path)}
    return Config.from_env(env)


@pytest.fixture
def server(config):
    return build_server(config)


def _payload(result):
    """Extract the structured/text payload from a CallToolResult."""
    if result.structured_content is not None:
        # FastMCP wraps non-dict returns under "result"
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    return result.content[0].text


async def test_taxonomy_lists_folders_and_whitelist(server):
    async with Client(server) as client:
        res = await client.call_tool("vault_taxonomy", {})
    data = _payload(res)
    assert any(f.startswith("30-Resources") for f in data["folders"])
    assert data["whitelists"]["30-Resources/AI"]["categories"]["MCP"]


async def test_write_then_read(server):
    async with Client(server) as client:
        w = await client.call_tool(
            "vault_write",
            {"folder": "30-Resources/AI", "filename": "via-mcp", "content": "# Note"},
        )
        wp = _payload(w)
        assert wp["path"] == "30-Resources/AI/via-mcp.md"

        r = await client.call_tool("vault_read", {"path": "30-Resources/AI/via-mcp.md"})
        rp = _payload(r)
        assert "# Note" in rp["content"]


async def test_write_root_is_rejected(server):
    async with Client(server) as client:
        w = await client.call_tool(
            "vault_write",
            {"folder": ".", "filename": "bad", "content": "x"},
        )
    assert "error" in _payload(w)


async def test_read_blocked_index(server):
    async with Client(server) as client:
        r = await client.call_tool("vault_read", {"path": "Wiki/_maps/link-map.md"})
    assert "error" in _payload(r)


async def test_search_disabled_message(server):
    async with Client(server) as client:
        r = await client.call_tool("vault_search", {"query": "anything"})
    assert "disabled" in _payload(r).lower()
