"""semantic_search builds the right argv for the fast-search front-end.

The Wiki/ exclusion is the default; --include-wiki opts back in. We monkeypatch
external.run so the test never shells out — it asserts on the argv only.
"""

from pathlib import Path

import vault_mcp.external as external


def _capture(monkeypatch):
    captured = {}

    def fake_run(argv, timeout=external.DEFAULT_TIMEOUT):
        captured["argv"] = argv
        return 0, "ok", ""

    monkeypatch.setattr(external, "run", fake_run)
    return captured


def test_semantic_search_excludes_wiki_by_default(monkeypatch):
    captured = _capture(monkeypatch)
    out = external.semantic_search(
        None, Path("/vault"), "/bin/fast", None, "q", "obsidian", 8
    )
    assert "--include-wiki" not in captured["argv"]
    assert captured["argv"][:4] == ["/bin/fast", "q", "-n", "8"]
    assert out == "ok"


def test_semantic_search_includes_wiki_when_requested(monkeypatch):
    captured = _capture(monkeypatch)
    external.semantic_search(
        None,
        Path("/vault"),
        "/bin/fast",
        None,
        "q",
        "obsidian",
        8,
        include_wiki=True,
    )
    assert "--include-wiki" in captured["argv"]


def test_semantic_search_prefers_jikji_when_configured(monkeypatch):
    captured = _capture(monkeypatch)
    payload = {
        "index_status": "ready",
        "handoff_action": "direct_use",
        "answer_paths": ["30-Resources/AI/note.md"],
        "candidates": [
            {"path": "30-Resources/AI/note.md", "score": 0.98, "next_read": "original"}
        ],
    }

    def fake_run(argv, timeout=external.DEFAULT_TIMEOUT):
        captured["argv"] = argv
        return 0, __import__("json").dumps(payload), ""

    monkeypatch.setattr(external, "run", fake_run)

    out = external.semantic_search(
        "/usr/local/bin/jikji",
        Path("/vault"),
        "/bin/fast",
        None,
        "meeting note",
        "obsidian",
        5,
    )

    assert captured["argv"] == [
        "/usr/local/bin/jikji",
        "find",
        "/vault",
        "meeting note",
        "--json",
        "--top-k",
        "5",
    ]
    assert "Search backend: Jikji find" in out
    assert "30-Resources/AI/note.md" in out


def test_semantic_search_falls_back_from_missing_jikji_index(monkeypatch):
    calls = []

    def fake_run(argv, timeout=external.DEFAULT_TIMEOUT):
        calls.append(argv)
        if argv[0] == "/usr/local/bin/jikji":
            return 1, "", "No Jikji search index found under /vault. Run: jikji prepare /vault"
        return 0, "legacy result", ""

    monkeypatch.setattr(external, "run", fake_run)

    out = external.semantic_search(
        "/usr/local/bin/jikji",
        Path("/vault"),
        "/bin/fast",
        None,
        "meeting note",
        "obsidian",
        5,
    )

    assert calls[0][0] == "/usr/local/bin/jikji"
    assert calls[1][:4] == ["/bin/fast", "meeting note", "-n", "5"]
    assert out == "legacy result"
