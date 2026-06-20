"""semantic_search builds the right argv for the fast-search front-end.

The Wiki/ exclusion is the default; --include-wiki opts back in. We monkeypatch
external.run so the test never shells out — it asserts on the argv only.
"""

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
    out = external.semantic_search("/bin/fast", None, "q", "obsidian", 8)
    assert "--include-wiki" not in captured["argv"]
    assert captured["argv"][:4] == ["/bin/fast", "q", "-n", "8"]
    assert out == "ok"


def test_semantic_search_includes_wiki_when_requested(monkeypatch):
    captured = _capture(monkeypatch)
    external.semantic_search("/bin/fast", None, "q", "obsidian", 8, include_wiki=True)
    assert "--include-wiki" in captured["argv"]
