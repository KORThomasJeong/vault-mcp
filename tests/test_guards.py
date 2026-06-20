import pytest

from vault_mcp.guards import GuardError, VaultGuard


@pytest.fixture
def guard(tmp_path):
    (tmp_path / "30-Resources" / "AI").mkdir(parents=True)
    (tmp_path / "Wiki" / "_maps").mkdir(parents=True)
    return VaultGuard(tmp_path)


def test_resolve_inside_vault(guard, tmp_path):
    assert guard.resolve("30-Resources/AI/x.md") == (
        tmp_path / "30-Resources/AI/x.md"
    ).resolve()


@pytest.mark.parametrize("bad", ["../escape.md", "/etc/passwd", "30-Resources/../../x"])
def test_resolve_rejects_traversal(guard, bad):
    with pytest.raises(GuardError):
        guard.resolve(bad)


def test_read_blocks_index_artifacts(guard):
    with pytest.raises(GuardError):
        guard.check_readable("Wiki/_maps/link-map.md")


def test_read_blocks_legacy_dump(guard):
    with pytest.raises(GuardError):
        guard.check_readable("90-Archive/Wiki_legacy_2026-05-15/x.md")


def test_read_allows_normal_note(guard):
    # does not raise even if the file does not exist yet
    guard.check_readable("30-Resources/AI/x.md")


def test_write_rejects_vault_root(guard):
    with pytest.raises(GuardError):
        guard.check_writable("note.md")


def test_write_rejects_disallowed_bucket(guard):
    with pytest.raises(GuardError):
        guard.check_writable("Wiki/sources/x.md")


def test_write_allows_para_bucket(guard):
    guard.check_writable("30-Resources/AI/x.md")
