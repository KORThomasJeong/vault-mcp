"""Transcript-done webhook: STT-web fires this the moment a raw transcript is
pushed to the vault, and we turn it into a Meeting MOM by running a headless
`claude -p` against the vault's own cleanup-prompt guide.

Design: docs/Thomas-MCP-transcript-webhook-설계.md (in the vault).

The MCP protocol path and this HTTP path share one FastMCP process but are
separate doors, so this door carries its own auth (HMAC over the raw body) and
its own execution limits (a 30-minute timeout on the headless agent — the
vault_exec 15s cap is far too short for meeting-notes synthesis).

Pure logic (signature check, frontmatter status transitions, prompt/command
building) lives here so it can be unit-tested without a running server; the
Starlette route in server.py is a thin adapter.
"""

from __future__ import annotations

import asyncio
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath

import yaml

# Background tasks are kept in a module-level set so the event loop does not
# garbage-collect them mid-flight (asyncio only holds a weak reference).
_PENDING: set[asyncio.Task] = set()


class HookError(ValueError):
    """Raised for a malformed or unauthorized webhook request."""


# --- HMAC verification ----------------------------------------------------
#
# Contract with STT-web: header `X-Transcript-Signature` carries
#   sha256=<hex hmac-sha256 of the raw request body, keyed by the shared secret>
# (GitHub's webhook convention). A bare hex digest without the `sha256=`
# prefix is also accepted so the sender side can stay minimal.


def expected_signature(secret: str, body: bytes) -> str:
    """The signature we expect for this body, without the `sha256=` prefix."""
    return hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """Constant-time compare of the presented signature against the expected one."""
    if not signature:
        return False
    presented = signature.strip()
    if presented.startswith("sha256="):
        presented = presented[len("sha256=") :]
    return hmac.compare_digest(presented, expected_signature(secret, body))


# --- frontmatter status transitions ---------------------------------------


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body). Missing/invalid frontmatter → ({}, text)."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    rest = text[end + len("\n---") :]
    if rest.startswith("\n"):
        rest = rest[1:]
    try:
        fm = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(fm, dict):
        return {}, text
    return fm, rest


def _join_frontmatter(fm: dict, body: str) -> str:
    dumped = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{dumped}\n---\n{body}"


def set_status(path: Path, status: str, extra: dict | None = None) -> None:
    """Rewrite the raw transcript's frontmatter `status` (idempotency + retry
    tracking). Preserves every other key and the body verbatim. If the file has
    no frontmatter we prepend one so the state is still recorded."""
    text = path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(text)
    fm["status"] = status
    if extra:
        fm.update(extra)
    path.write_text(_join_frontmatter(fm, body), encoding="utf-8")


# --- prompt + command building --------------------------------------------


def build_prompt(
    raw_rel: str,
    prompt_guide_rel: str,
    transcript_id: object,
    meeting_date: object,
) -> str:
    """Reuse the vault's existing cleanup-prompt guide instead of duplicating its
    rules here: tell the headless agent to read the guide, read the raw file, and
    produce the MOM per those rules. Editing the guide in the vault propagates
    automatically."""
    return (
        "전사 완료 웹훅이 발사됐다. STT-web이 raw 전사본을 볼트에 푸시했고, "
        "너는 이것을 회의록으로 가공해야 한다.\n\n"
        "수행 절차:\n"
        f'1. vault_read로 정리 규칙 가이드를 읽어라: "{prompt_guide_rel}"\n'
        f'2. vault_read로 raw 전사본을 읽어라: "{raw_rel}"\n'
        "3. 그 가이드의 규칙에 따라 Meeting MOM 노트를 vault_write로 저장하라.\n"
        f"   - Raw 원본은 이미 \"{raw_rel}\"에 보존돼 있으니 새로 만들지 말고, "
        "MOM 생성에 집중하고 서로 링크만 보강하라.\n"
        "   - 원문에 없는 내용은 단정하지 말고 '미확정/추정/확인 필요'로 표시하라.\n"
        "4. 채팅에는 저장한 MOM 경로만 짧게 남겨라. 본문을 길게 출력하지 마라.\n\n"
        f"메타데이터: transcript_id={transcript_id!r}, meeting_date={meeting_date!r}"
    )


@dataclass(frozen=True)
class ClaudeRun:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


def build_claude_command(
    *,
    claude_bin: str,
    prompt: str,
    allowed_tools: str,
    mcp_config: str | None,
) -> list[str]:
    """The headless invocation from the design doc.

    No shell `timeout` wrapper — the async runner enforces the limit and kills
    the process group, which is more reliable than relying on `timeout(1)`.
    """
    cmd = [
        claude_bin,
        "-p",
        prompt,
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        allowed_tools,
        "--output-format",
        "json",
    ]
    if mcp_config:
        cmd += ["--mcp-config", mcp_config]
    return cmd


async def run_claude(cmd: list[str], cwd: Path, timeout: int) -> ClaudeRun:
    """Run the headless agent, killing it if it blows past the timeout."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return ClaudeRun(-1, "", f"killed after {timeout}s timeout", timed_out=True)
    return ClaudeRun(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout.decode("utf-8", "replace").strip(),
        stderr=stderr.decode("utf-8", "replace").strip(),
        timed_out=False,
    )


# --- payload validation ----------------------------------------------------


@dataclass(frozen=True)
class HookPayload:
    path: str          # vault-relative path to the raw transcript
    transcript_id: object
    meeting_date: object


def parse_payload(body: bytes, transcript_root: str) -> HookPayload:
    """Validate the JSON body. Raises HookError on anything malformed or on a
    path that escapes the transcript root — the webhook must never be able to
    point the agent at an arbitrary file."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HookError(f"Invalid JSON body: {e}") from e
    if not isinstance(data, dict):
        raise HookError("Body must be a JSON object")

    path = data.get("path")
    if not isinstance(path, str) or not path.strip():
        raise HookError("Missing 'path'")
    path = path.strip()

    pure = PurePosixPath(path)
    if pure.is_absolute() or any(p == ".." for p in pure.parts):
        raise HookError(f"Path escapes the vault: {path!r}")
    root = transcript_root.rstrip("/")
    if not (str(pure) == root or str(pure).startswith(root + "/")):
        raise HookError(f"Path is not under the transcript root ({root}): {path!r}")

    return HookPayload(
        path=str(pure),
        transcript_id=data.get("transcript_id"),
        meeting_date=data.get("meeting_date"),
    )


# --- orchestration ---------------------------------------------------------


def _utcstamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def process_transcript(
    *,
    raw_abs: Path,
    raw_rel: str,
    payload: HookPayload,
    claude_bin: str,
    allowed_tools: str,
    mcp_config: str | None,
    prompt_guide: str,
    timeout: int,
    cwd: Path,
) -> None:
    """Background job: run the headless agent, then stamp the outcome into the
    raw file's frontmatter (exit 0 → processed, anything else → failed so it can
    be retried). This never raises into the event loop; failures are recorded."""
    prompt = build_prompt(raw_rel, prompt_guide, payload.transcript_id, payload.meeting_date)
    cmd = build_claude_command(
        claude_bin=claude_bin,
        prompt=prompt,
        allowed_tools=allowed_tools,
        mcp_config=mcp_config,
    )
    try:
        run = await run_claude(cmd, cwd=cwd, timeout=timeout)
    except Exception as e:  # noqa: BLE001 - a spawn failure must still be recorded
        _safe_set_status(raw_abs, "failed", {"hook_error": str(e), "hook_at": _utcstamp()})
        return

    if run.exit_code == 0:
        _safe_set_status(raw_abs, "processed", {"hook_at": _utcstamp()})
    else:
        detail = "timeout" if run.timed_out else (run.stderr or run.stdout)[:500]
        _safe_set_status(
            raw_abs,
            "failed",
            {"hook_error": detail, "hook_exit_code": run.exit_code, "hook_at": _utcstamp()},
        )


def _safe_set_status(path: Path, status: str, extra: dict | None = None) -> None:
    try:
        set_status(path, status, extra)
    except OSError:
        # The file may have moved; there is nothing more we can do from here.
        pass


def spawn(coro) -> asyncio.Task:
    """Fire-and-forget a coroutine on the running loop, keeping a strong ref."""
    task = asyncio.ensure_future(coro)
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
    return task
