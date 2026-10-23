"""Runtime configuration, all from environment variables (see .env.example)."""

from __future__ import annotations

import os
import secrets


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


DATABASE_URL: str = _env("DATABASE_URL", "sqlite:///./roundtable.db")
ROUNDTABLE_TOKEN: str = _env("ROUNDTABLE_TOKEN", "")
HOST: str = _env("ROUNDTABLE_HOST", "0.0.0.0")
PORT: int = int(_env("ROUNDTABLE_PORT", "8787"))
PUBLIC_URL: str = _env("ROUNDTABLE_PUBLIC_URL", f"http://localhost:{PORT}").rstrip("/")
# When a reverse proxy (Tailscale Funnel path handler, nginx) mounts the server under a path such as /sr,
# set this so the server strips it. Requests without the prefix still work.
BASE_PATH: str = "/" + _env("ROUNDTABLE_BASE_PATH", "").strip("/") if _env("ROUNDTABLE_BASE_PATH", "").strip("/") else ""
# URL segment that carries the token for clients that cannot send headers: /key/<token>/mcp
TOKEN_PATH_SEGMENT: str = _env("ROUNDTABLE_TOKEN_PATH", "key").strip("/")
DISPLAY_TZ: str = _env("ROUNDTABLE_TZ", "America/Chicago")
SEED_ON_START: bool = _env("ROUNDTABLE_SEED", "true").lower() in ("1", "true", "yes")
ACCOUNT_LABEL: str = _env("ROUNDTABLE_ACCOUNT", "Robinhood MCP account")

# Critic (local model seat)
LLM_BASE_URL: str = _env("LLM_BASE_URL", "http://host.docker.internal:11434/v1")
LLM_MODEL: str = _env("LLM_MODEL", "gemma4:12b")
LLM_API_KEY: str = _env("LLM_API_KEY", "ollama")
CRITIC_INTERVAL: int = int(_env("CRITIC_INTERVAL", "900"))
CRITIC_AUTHOR: str = _env("CRITIC_AUTHOR", "critic")

KNOWN_AUTHORS = ("claude", "gpt", "critic", "shawn", "system")


def require_token() -> str:
    """The shared secret every MCP and API call must carry.

    If none is configured, generate one for this process and print it, so a
    first run is still protected rather than open.
    """
    global ROUNDTABLE_TOKEN
    if not ROUNDTABLE_TOKEN:
        ROUNDTABLE_TOKEN = secrets.token_urlsafe(24)
        print(f"[roundtable] ROUNDTABLE_TOKEN not set; using a one-off token for this run: {ROUNDTABLE_TOKEN}")
        print("[roundtable] Put a fixed value in .env so agents can keep using the same URL.")
    return ROUNDTABLE_TOKEN
