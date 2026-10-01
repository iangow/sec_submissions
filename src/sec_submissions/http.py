"""SEC HTTP helpers with explicit identification and rate limiting."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values


def _valid_user_agent(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "@" in value


def _project_env_value() -> str | None:
    path = Path.cwd() / ".env"
    if not path.is_file():
        return None
    return dotenv_values(path).get("SEC_USER_AGENT")


def _user_config_value() -> str | None:
    path = Path.home() / ".config" / "sec-submissions" / "config.toml"
    if not path.is_file():
        return None
    with path.open("rb") as stream:
        return tomllib.load(stream).get("user_agent")


def set_user_agent(user_agent: str, scope: str = "session") -> str:
    """Set the SEC user agent for this process and optionally persist it.

    ``scope`` may be ``session``, ``project`` (the current directory's
    ``.env``), or ``user`` (``~/.config/sec-submissions/config.toml``).
    """
    if not _valid_user_agent(user_agent):
        raise ValueError("SEC user agent must be a string containing an email address")
    user_agent = user_agent.strip()
    if scope not in {"session", "project", "user"}:
        raise ValueError("Scope must be 'session', 'project', or 'user'")
    os.environ["SEC_USER_AGENT"] = user_agent
    if scope == "project":
        path = Path.cwd() / ".env"
        existing = path.read_text().splitlines() if path.exists() else []
        updated, replaced = [], False
        for line in existing:
            key, separator, _ = line.partition("=")
            if separator and key.strip() == "SEC_USER_AGENT":
                if not replaced:
                    updated.append(f"SEC_USER_AGENT={user_agent}")
                    replaced = True
            else:
                updated.append(line)
        if not replaced:
            updated.append(f"SEC_USER_AGENT={user_agent}")
        path.write_text("\n".join(updated) + "\n")
        path.chmod(0o600)
    elif scope == "user":
        path = Path.home() / ".config" / "sec-submissions" / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"user_agent = {json.dumps(user_agent)}\n")
        path.chmod(0o600)
    return user_agent


def resolve_user_agent(value: str | None = None, prompt: bool | None = None) -> str:
    """Resolve a SEC identity like ``dera.pq`` and prompt only interactively."""
    if value is not None and (not isinstance(value, str) or value.strip()):
        if not _valid_user_agent(value):
            raise ValueError("SEC user agent must be a string containing an email address")
        return value.strip()

    candidates = (
        ("SEC_USER_AGENT", os.environ.get("SEC_USER_AGENT")),
        ("HTTP_USER_AGENT", os.environ.get("HTTP_USER_AGENT")),
        ("project .env", _project_env_value()),
        ("user config", _user_config_value()),
    )
    invalid_source = None
    for source, candidate in candidates:
        if candidate:
            if _valid_user_agent(candidate):
                os.environ["SEC_USER_AGENT"] = candidate.strip()
                return candidate.strip()
            invalid_source = source
            break

    if prompt is None:
        prompt = sys.stdin.isatty()
    if prompt:
        if invalid_source:
            print(f"{invalid_source} does not contain a contact email address.", file=sys.stderr)
        print("SEC automated-access guidance asks for an identifying user agent with contact information.")
        entered = input("SEC user agent, including your email address: ").strip()
        if not _valid_user_agent(entered):
            raise ValueError("SEC user agent must be a non-empty value containing an email address")
        while True:
            scope = input("Save for this project, all projects, or not at all? [project/user/no] ").strip().lower()
            scope = {
                "": "user", "p": "project", "u": "user",
                "n": "session", "no": "session", "none": "session",
            }.get(scope, scope)
            if scope in {"project", "user", "session"}:
                return set_user_agent(entered, scope)
            print("Enter 'project', 'user', or 'no'.", file=sys.stderr)

    if invalid_source:
        raise ValueError(f"{invalid_source} is set but does not contain an email address")
    raise ValueError("Set SEC_USER_AGENT, pass --user-agent, or run interactively to configure it")


class NetworkRateLimiter:
    """A process-wide minimum delay between requests across worker threads."""

    def __init__(self, requests_per_second: float):
        if requests_per_second <= 0:
            raise ValueError("Request rate must be positive")
        self.delay = 1 / requests_per_second
        self.lock = threading.Lock()
        self.next_request_at = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self.next_request_at - now)
            self.next_request_at = max(now, self.next_request_at) + self.delay
        if wait_seconds:
            time.sleep(wait_seconds)


def fetch_json(url: str, user_agent: str, timeout: float = 30) -> tuple[dict, int]:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        import json

        return json.load(response), response.status


def sgml_url(cik: int, accession: str) -> str:
    compact = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{compact}/{accession}.hdr.sgml"


def fetch_sgml(cik: int, accession: str, user_agent: str) -> dict:
    """Fetch a filing header and return the timestamp plus source provenance."""
    url = sgml_url(cik, accession)
    request = urllib.request.Request(
        url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    )
    started = time.monotonic()
    acceptance = text = digest = status = None
    error = None
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
            encoding = response.headers.get("Content-Encoding", "").lower()
            if encoding == "gzip":
                content = gzip.decompress(content)
            elif encoding == "deflate":
                content = zlib.decompress(content)
            status = response.status
        text = content.decode("latin-1")
        digest = hashlib.sha256(content).hexdigest()
        match = re.search(r"<ACCEPTANCE-DATETIME>\s*(\d{14})", text)
        if not match:
            raise ValueError("ACCEPTANCE-DATETIME tag not found")
        acceptance = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    except Exception as exc:  # retain HTTP/parse failures as audit evidence
        if isinstance(exc, urllib.error.HTTPError):
            status = exc.code
        error = f"{type(exc).__name__}: {exc}"
    return {
        "acceptance": acceptance,
        "url": url,
        "retrieved_at": datetime.now(timezone.utc),
        "elapsed_ms": (time.monotonic() - started) * 1000,
        "status": status,
        "digest": digest,
        "text": text,
        "error": error,
    }


def retryable(error: str | None) -> bool:
    if not error:
        return False
    return not error.startswith("ValueError: ACCEPTANCE-DATETIME tag not found")
