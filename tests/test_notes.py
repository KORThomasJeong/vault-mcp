import pytest

from vault_mcp.guards import GuardError, VaultGuard
from vault_mcp.notes import read_note, write_note


@pytest.fixture
def guard(tmp_path):
    (tmp_path / "30-Resources" / "AI").mkdir(parents=True)
    return VaultGuard(tmp_path)


def test_create_then_read_roundtrip(guard):
    res = write_note(guard, "30-Resources/AI", "hello", "# Hi\nbody")
    assert res["path"] == "30-Resources/AI/hello.md"
    assert res["created"] is True
    back = read_note(guard, "30-Resources/AI/hello.md")
    assert "# Hi" in back["content"]
    assert "source: mcp" in back["content"]
    assert "created:" in back["content"]


def test_create_fails_if_exists(guard):
    write_note(guard, "30-Resources/AI", "dup", "a")
    with pytest.raises(GuardError):
        write_note(guard, "30-Resources/AI", "dup", "b", mode="create")


def test_overwrite_replaces(guard):
    write_note(guard, "30-Resources/AI", "ow", "first")
    write_note(guard, "30-Resources/AI", "ow", "second", mode="overwrite")
    assert "second" in read_note(guard, "30-Resources/AI/ow.md")["content"]
    assert "first" not in read_note(guard, "30-Resources/AI/ow.md")["content"]


def test_append_adds(guard):
    write_note(guard, "30-Resources/AI", "ap", "line1")
    write_note(guard, "30-Resources/AI", "ap", "line2", mode="append")
    content = read_note(guard, "30-Resources/AI/ap.md")["content"]
    assert "line1" in content and "line2" in content


def test_append_missing_file_errors(guard):
    with pytest.raises(GuardError):
        write_note(guard, "30-Resources/AI", "nope", "x", mode="append")


def test_custom_frontmatter_merged(guard):
    write_note(
        guard, "30-Resources/AI", "fm", "body", frontmatter={"tags": ["ai"], "title": "T"}
    )
    content = read_note(guard, "30-Resources/AI/fm.md")["content"]
    assert "title: T" in content
    assert "- ai" in content


def test_filename_gets_md_extension(guard):
    res = write_note(guard, "30-Resources/AI", "noext", "x")
    assert res["path"].endswith("noext.md")


def test_write_outside_bucket_rejected(guard):
    with pytest.raises(GuardError):
        write_note(guard, "Wiki/sources", "x", "y")
