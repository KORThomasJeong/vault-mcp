import pytest
from fastmcp import Client

from vault_mcp.config import Config
from vault_mcp.server import build_server


@pytest.fixture
def config(tmp_path):
    (tmp_path / "01-Inbox").mkdir()
    (tmp_path / "01-Inbox" / "note.md").write_text("# hi", encoding="utf-8")
    env = {"VAULT_PATH": str(tmp_path)}
    return Config.from_env(env)


@pytest.fixture
def server(config):
    return build_server(config)


def _payload(result):
    if result.structured_content is not None:
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    return result.content[0].text


async def _exec(server, command):
    async with Client(server) as client:
        res = await client.call_tool("vault_exec", {"command": command})
    return _payload(res)


async def test_allowed_echo_runs(server):
    out = await _exec(server, "echo 'vault_exec works'")
    assert out["ok"] is True
    assert out["stdout"] == "vault_exec works"
    assert out["exit_code"] == 0


async def test_allowed_ls_runs_in_vault_cwd(server):
    out = await _exec(server, "ls 01-Inbox")
    assert out["ok"] is True
    assert "note.md" in out["stdout"]


async def test_allowed_pipe_to_head(server):
    out = await _exec(server, "find 01-Inbox -name '*.md' | head -5")
    assert "exit_code" in out  # ran
    assert "note.md" in out["stdout"]


async def test_command_not_in_allowlist_rejected(server):
    out = await _exec(server, "curl http://evil")
    assert out["ok"] is False
    assert "allowlist" in out["error"]
    assert "exit_code" not in out  # never ran


async def test_command_chaining_allowed_for_trusted_user(server):
    # Single-user server: chaining is permitted once the prefix matches.
    out = await _exec(server, "echo a; echo b")
    assert "exit_code" in out  # ran
    assert out["stdout"] == "a\nb"


async def test_command_substitution_allowed(server):
    out = await _exec(server, "echo $(echo nested)")
    assert "exit_code" in out
    assert out["stdout"] == "nested"


async def test_pipe_allowed(server):
    out = await _exec(server, "echo hello | cat")
    assert "exit_code" in out
    assert out["stdout"] == "hello"


async def test_rm_outside_vault_rejected(server):
    out = await _exec(server, "rm /etc/hosts")
    assert out["ok"] is False
    assert "confined to the vault root" in out["error"]
    assert "exit_code" not in out


async def test_rm_inside_vault_allowed_to_run(server, config):
    target = config.vault_path / "01-Inbox" / "note.md"
    out = await _exec(server, f"rm {target}")
    assert "exit_code" in out  # guard let it run
    assert not target.exists()
