import pytest

from vault_mcp.config import Config


def _base(tmp_path, **extra):
    env = {"VAULT_PATH": str(tmp_path)}
    env.update(extra)
    return env


def test_default_mode_none_without_creds(tmp_path):
    cfg = Config.from_env(_base(tmp_path))
    assert cfg.auth_mode == "none"


def test_infers_token_mode(tmp_path):
    cfg = Config.from_env(_base(tmp_path, MCP_AUTH_TOKEN="secret"))
    assert cfg.auth_mode == "token"
    assert cfg.auth_token == "secret"


def test_infers_github_mode_when_client_id_present(tmp_path):
    cfg = Config.from_env(
        _base(
            tmp_path,
            GITHUB_CLIENT_ID="cid",
            GITHUB_CLIENT_SECRET="sec",
            BASE_URL="https://mcp.example.com",
            GITHUB_ALLOWED_USERS="alice",
        )
    )
    assert cfg.auth_mode == "github"
    assert cfg.github_allowed_users == frozenset({"alice"})


def test_github_mode_requires_allowlist(tmp_path):
    with pytest.raises(RuntimeError, match="GITHUB_ALLOWED_USERS"):
        Config.from_env(
            _base(
                tmp_path,
                AUTH_MODE="github",
                GITHUB_CLIENT_ID="cid",
                GITHUB_CLIENT_SECRET="sec",
                BASE_URL="https://mcp.example.com",
            )
        )


def test_github_mode_requires_base_url_and_secret(tmp_path):
    with pytest.raises(RuntimeError, match="BASE_URL"):
        Config.from_env(
            _base(
                tmp_path,
                AUTH_MODE="github",
                GITHUB_CLIENT_ID="cid",
                GITHUB_ALLOWED_USERS="alice",
            )
        )


def test_allowlist_is_lowercased_and_split(tmp_path):
    cfg = Config.from_env(
        _base(
            tmp_path,
            GITHUB_CLIENT_ID="cid",
            GITHUB_CLIENT_SECRET="sec",
            BASE_URL="https://mcp.example.com",
            GITHUB_ALLOWED_USERS="Alice, Bob , ",
        )
    )
    assert cfg.github_allowed_users == frozenset({"alice", "bob"})


def test_invalid_mode_rejected(tmp_path):
    with pytest.raises(RuntimeError, match="AUTH_MODE"):
        Config.from_env(_base(tmp_path, AUTH_MODE="bogus"))
