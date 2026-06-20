"""Authorization: restrict an OAuth-authenticated server to specific users.

Authentication (proving who you are) is handled by the OAuth provider.
Authorization (deciding you're *allowed*) is this module's job. Without it, a
GitHub OAuth server would accept ANY GitHub account — far more open than a
static token. The middleware fails closed: no recognised identity → denied.
"""

from __future__ import annotations

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware, MiddlewareContext

# Claim keys different providers use for the human-readable account name.
_IDENTITY_CLAIMS = ("login", "username", "preferred_username", "email", "sub")


def identities_from_token() -> list[str]:
    """All candidate identity strings (lowercased) for the current request."""
    token = get_access_token()
    if token is None or not getattr(token, "claims", None):
        return []
    out: list[str] = []
    for key in _IDENTITY_CLAIMS:
        val = token.claims.get(key)
        if isinstance(val, str) and val.strip():
            out.append(val.strip().lower())
    return out


class AllowlistMiddleware(Middleware):
    """Reject tool calls from any identity not in the allowlist."""

    def __init__(self, allowed: frozenset[str]):
        self.allowed = allowed

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        token = get_access_token()
        # A static token marked "trusted" is pre-authorized — holding the secret
        # is the authorization. Only OAuth identities are checked against the list.
        if token is not None and getattr(token, "claims", None):
            if token.claims.get("trusted") is True:
                return await call_next(context)
        ids = identities_from_token()
        if not any(i in self.allowed for i in ids):
            shown = ids or ["<no identity>"]
            raise ToolError(f"Access denied for {shown}; not in the allowlist.")
        return await call_next(context)
