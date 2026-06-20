"""Path safety: keep every operation inside the vault and away from the
machine-generated index files that would blow up token usage if read.

These rules mirror the vault's own operating policy:
  * never read the regenerable index/map/log artifacts or the legacy wiki dump,
  * only ever write into the PARA source buckets (never the vault root),
  * never escape the vault root via `..` or absolute paths.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

# Relative path prefixes (POSIX style) whose contents must never be returned to
# the model — the indexer regenerates them and they are huge.
READ_DENY_PREFIXES: tuple[str, ...] = (
    "Wiki/_maps/",
    "Wiki/_indexes/",
    "Wiki/_logs/",
)

# Relative path prefixes that match anywhere by glob-like startswith after
# normalisation (legacy wiki backups carry a timestamp suffix).
READ_DENY_GLOBS: tuple[str, ...] = (
    "90-Archive/Wiki_legacy_",
    "90-Archive/Wiki_repair_backup_",
)

# Only these top-level buckets accept writes. The vault root itself is off limits
# (root-level .md files are forbidden by policy).
WRITE_ALLOWED_PREFIXES: tuple[str, ...] = (
    "01-Inbox/",
    "10-Projects/",
    "20-Areas/",
    "30-Resources/",
    "docs/",
)


class GuardError(ValueError):
    """Raised when a requested path violates a safety rule."""


def _normalise(rel: str) -> PurePosixPath:
    """Turn user input into a clean POSIX relative path or raise."""
    rel = rel.strip()
    if not rel:
        raise GuardError("Empty path.")
    if rel.startswith("/") or rel.startswith("~"):
        raise GuardError(f"Absolute paths are not allowed: {rel!r}")
    pure = PurePosixPath(rel)
    if pure.is_absolute() or any(part == ".." for part in pure.parts):
        raise GuardError(f"Path escapes the vault: {rel!r}")
    return pure


class VaultGuard:
    def __init__(self, vault_root: Path):
        self.vault_root = vault_root.resolve()

    def resolve(self, rel: str) -> Path:
        """Resolve a vault-relative path to an absolute path inside the vault.

        Raises GuardError on traversal or if the resolved path lands outside the
        vault root (covers symlink trickery too, since we resolve then compare).
        """
        pure = _normalise(rel)
        candidate = (self.vault_root / Path(*pure.parts)).resolve()
        if candidate != self.vault_root and self.vault_root not in candidate.parents:
            raise GuardError(f"Path escapes the vault: {rel!r}")
        return candidate

    def rel_posix(self, rel: str) -> str:
        """Normalised, vault-relative POSIX string (for prefix checks)."""
        return str(_normalise(rel))

    def check_readable(self, rel: str) -> Path:
        path = self.resolve(rel)
        posix = self.rel_posix(rel)
        for prefix in READ_DENY_PREFIXES:
            if posix == prefix.rstrip("/") or posix.startswith(prefix):
                raise GuardError(
                    f"Blocked: {posix} is a machine-generated index/log — "
                    "query the vault instead of reading it."
                )
        for glob in READ_DENY_GLOBS:
            if posix.startswith(glob):
                raise GuardError(f"Blocked: {posix} is an archived legacy dump.")
        return path

    def check_writable(self, rel: str) -> Path:
        path = self.resolve(rel)
        posix = self.rel_posix(rel)
        if "/" not in posix:
            raise GuardError(
                "Refusing to write to the vault root. Write into one of: "
                + ", ".join(WRITE_ALLOWED_PREFIXES)
            )
        if not any(posix.startswith(p) for p in WRITE_ALLOWED_PREFIXES):
            raise GuardError(
                f"Writes are only allowed under {WRITE_ALLOWED_PREFIXES}; got {posix!r}."
            )
        return path
