import json

import pytest
from starlette.testclient import TestClient

from vault_mcp import webhook
from vault_mcp.config import Config
from vault_mcp.server import build_server

SECRET = "test-secret"
ROOT = "10-Projects/Transcripts"


# --- fixtures --------------------------------------------------------------


@pytest.fixture
def raw_file(tmp_path):
    d = tmp_path / "10-Projects" / "Transcripts" / "2026"
    d.mkdir(parents=True)
    f = d / "meeting_raw.md"
    f.write_text(
        "---\ntype: transcript\nstatus: to-process\ntranscript_id: 42\n---\n\n원본 텍스트\n",
        encoding="utf-8",
    )
    return f


@pytest.fixture
def config(tmp_path, raw_file):
    env = {
        "VAULT_PATH": str(tmp_path),
        "TRANSCRIPT_HOOK_SECRET": SECRET,
        "TRANSCRIPT_ROOT": ROOT,
        "CLAUDE_BIN": "/usr/bin/true",
    }
    return Config.from_env(env)


# --- HMAC verification -----------------------------------------------------


def test_verify_signature_accepts_prefixed():
    body = b'{"path":"x"}'
    sig = "sha256=" + webhook.expected_signature(SECRET, body)
    assert webhook.verify_signature(SECRET, body, sig) is True


def test_verify_signature_accepts_bare_hex():
    body = b'{"path":"x"}'
    assert webhook.verify_signature(SECRET, body, webhook.expected_signature(SECRET, body))


def test_verify_signature_rejects_wrong_and_missing():
    body = b'{"path":"x"}'
    assert webhook.verify_signature(SECRET, body, "sha256=deadbeef") is False
    assert webhook.verify_signature(SECRET, body, None) is False
    assert webhook.verify_signature(SECRET, b"tampered", webhook.expected_signature(SECRET, body)) is False


# --- payload validation ----------------------------------------------------


def test_parse_payload_ok():
    body = json.dumps(
        {"path": f"{ROOT}/2026/m_raw.md", "transcript_id": 42, "meeting_date": "2026-06-16"}
    ).encode()
    p = webhook.parse_payload(body, ROOT)
    assert p.path == f"{ROOT}/2026/m_raw.md"
    assert p.transcript_id == 42
    assert p.meeting_date == "2026-06-16"


def test_parse_payload_rejects_bad_json():
    with pytest.raises(webhook.HookError):
        webhook.parse_payload(b"not json", ROOT)


def test_parse_payload_rejects_missing_path():
    with pytest.raises(webhook.HookError):
        webhook.parse_payload(b'{"transcript_id":1}', ROOT)


def test_parse_payload_rejects_traversal():
    with pytest.raises(webhook.HookError):
        webhook.parse_payload(json.dumps({"path": f"{ROOT}/../../etc/x.md"}).encode(), ROOT)


def test_parse_payload_rejects_outside_root():
    with pytest.raises(webhook.HookError):
        webhook.parse_payload(json.dumps({"path": "01-Inbox/x.md"}).encode(), ROOT)


# --- frontmatter status transitions ---------------------------------------


def test_set_status_updates_and_preserves(raw_file):
    webhook.set_status(raw_file, "processing", {"hook_at": "2026-07-04T00:00:00+00:00"})
    text = raw_file.read_text(encoding="utf-8")
    fm, body = webhook._split_frontmatter(text)
    assert fm["status"] == "processing"
    assert fm["type"] == "transcript"      # preserved
    assert fm["transcript_id"] == 42       # preserved
    assert fm["hook_at"] == "2026-07-04T00:00:00+00:00"
    assert "원본 텍스트" in body            # body preserved


def test_set_status_on_file_without_frontmatter(tmp_path):
    f = tmp_path / "bare.md"
    f.write_text("just body\n", encoding="utf-8")
    webhook.set_status(f, "failed")
    fm, body = webhook._split_frontmatter(f.read_text(encoding="utf-8"))
    assert fm["status"] == "failed"
    assert "just body" in body


# --- prompt / command building ---------------------------------------------


def test_build_prompt_injects_paths():
    prompt = webhook.build_prompt("A/raw.md", "Guide.md", 42, "2026-06-16")
    assert "A/raw.md" in prompt
    assert "Guide.md" in prompt
    assert "42" in prompt


def test_build_command_shape():
    cmd = webhook.build_claude_command(
        claude_bin="claude", prompt="P", allowed_tools="mcp__thomas__vault_read", mcp_config=None
    )
    assert cmd[:3] == ["claude", "-p", "P"]
    assert "--permission-mode" in cmd and "acceptEdits" in cmd
    assert "--output-format" in cmd and "json" in cmd
    assert "--mcp-config" not in cmd


def test_build_command_adds_mcp_config():
    cmd = webhook.build_claude_command(
        claude_bin="claude", prompt="P", allowed_tools="x", mcp_config="/tmp/mcp.json"
    )
    assert "--mcp-config" in cmd and "/tmp/mcp.json" in cmd


# --- run_claude ------------------------------------------------------------


async def test_run_claude_exit_zero(tmp_path):
    run = await webhook.run_claude(["/usr/bin/true"], cwd=tmp_path, timeout=10)
    assert run.exit_code == 0 and run.timed_out is False


async def test_run_claude_timeout(tmp_path):
    run = await webhook.run_claude(["/bin/sleep", "5"], cwd=tmp_path, timeout=1)
    assert run.timed_out is True and run.exit_code != 0


# --- process_transcript (background job) -----------------------------------


async def test_process_transcript_success_marks_processed(raw_file, tmp_path):
    payload = webhook.HookPayload(path="p", transcript_id=42, meeting_date="d")
    await webhook.process_transcript(
        raw_abs=raw_file, raw_rel="p", payload=payload, claude_bin="/usr/bin/true",
        allowed_tools="x", mcp_config=None, prompt_guide="g", timeout=10, cwd=tmp_path,
    )
    fm, _ = webhook._split_frontmatter(raw_file.read_text(encoding="utf-8"))
    assert fm["status"] == "processed"


async def test_process_transcript_failure_marks_failed(raw_file, tmp_path):
    payload = webhook.HookPayload(path="p", transcript_id=42, meeting_date="d")
    await webhook.process_transcript(
        raw_abs=raw_file, raw_rel="p", payload=payload, claude_bin="/usr/bin/false",
        allowed_tools="x", mcp_config=None, prompt_guide="g", timeout=10, cwd=tmp_path,
    )
    fm, _ = webhook._split_frontmatter(raw_file.read_text(encoding="utf-8"))
    assert fm["status"] == "failed"
    assert fm["hook_exit_code"] != 0


# --- HTTP route (end-to-end through the ASGI app) --------------------------


def _call(config, path_rel, sign=True, body_override=None):
    # Starlette's TestClient runs the app lifespan (FastMCP's session manager),
    # which httpx.ASGITransport alone does not — without it the request hangs.
    app = build_server(config).http_app()
    body = body_override if body_override is not None else json.dumps({"path": path_rel}).encode()
    headers = {"content-type": "application/json"}
    if sign:
        headers["X-Transcript-Signature"] = "sha256=" + webhook.expected_signature(SECRET, body)
    with TestClient(app) as client:
        return client.post("/hooks/transcript-done", content=body, headers=headers)


def test_route_rejects_bad_signature(config):
    assert _call(config, f"{ROOT}/2026/meeting_raw.md", sign=False).status_code == 401


def test_route_rejects_bad_payload(config):
    assert _call(config, "ignored", body_override=b"not json").status_code == 400


def test_route_rejects_path_outside_root(config):
    assert _call(config, "01-Inbox/x.md").status_code == 400


def test_route_404_when_file_missing(config):
    assert _call(config, f"{ROOT}/2026/nope_raw.md").status_code == 404


def test_route_accepts_and_flips_to_processing(config, raw_file):
    resp = _call(config, f"{ROOT}/2026/meeting_raw.md")
    assert resp.status_code == 202
    # status flips to processing synchronously before the 202 returns; the
    # background job (claude_bin=/usr/bin/true) may already have advanced it.
    fm, _ = webhook._split_frontmatter(raw_file.read_text(encoding="utf-8"))
    assert fm["status"] in ("processing", "processed")


def test_route_absent_without_secret(tmp_path):
    env = {"VAULT_PATH": str(tmp_path)}
    app = build_server(Config.from_env(env)).http_app()
    routes = [getattr(r, "path", None) for r in app.routes]
    assert "/hooks/transcript-done" not in routes
