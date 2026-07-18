"""
REKOMND+ — Authentication & Access Control
==========================================
SQLite-backed multi-user auth with session cookies.
Provides User model, login/register, role-based admin, per-user tool
permissions, account expiry, and suspend/resume support.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import Response

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).resolve().parent / "data" / "auth.db"
_COOKIE_NAME = "rkom_session"
_SESSION_MAX_AGE_DAYS = 30

# Tool slugs recognised by the platform
TOOL_SLUGS = ("gmaps", "poster", "commenter", "buyers", "whatsapp")

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${hashed.hex()}", salt


def _verify_password(password: str, stored: str) -> bool:
    salt, _ = stored.split("$", 1)
    candidate, _ = _hash_password(password, salt)
    return secrets.compare_digest(candidate, stored)


# ---------------------------------------------------------------------------
# User dataclass
# ---------------------------------------------------------------------------

@dataclass
class User:
    id: int
    username: str
    display_name: str
    email: str
    password_hash: str
    role: str
    is_active: bool
    allowed_tools: str          # "all" or JSON list like '["gmaps","poster"]'
    expires_at: Optional[str]   # ISO datetime or None
    created_at: str
    last_login: Optional[str]
    avatar_color: str = ""
    initials: str = ""

    def __post_init__(self):
        if not self.initials:
            parts = (self.display_name or self.username).split()
            self.initials = "".join(p[0].upper() for p in parts[:2]) or "U"
        if not self.avatar_color:
            colors = [
                "linear-gradient(135deg,#f59e0b,#ef4444)",
                "linear-gradient(135deg,#6366f1,#8b5cf6)",
                "linear-gradient(135deg,#10b981,#059669)",
                "linear-gradient(135deg,#f59e0b,#d97706)",
                "linear-gradient(135deg,#ec4899,#f43f5e)",
                "linear-gradient(135deg,#06b6d4,#3b82f6)",
            ]
            h = sum(ord(c) for c in self.username)
            self.avatar_color = colors[h % len(colors)]

    # Computed shortcuts
    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def last_login_short(self) -> str:
        if not self.last_login:
            return "Never"
        return self.last_login[:10]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "is_admin": self.is_admin,
            "allowed_tools": self.allowed_tools,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "last_login": self.last_login,
        }

    @property
    def tools_list(self) -> list[str]:
        return _parse_tools(self.allowed_tools)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"] or row["username"],
        email=row["email"] or "",
        password_hash=row["password_hash"],
        role=row["role"] or "user",
        is_active=bool(row["is_active"]),
        allowed_tools=row["allowed_tools"] or "all",
        expires_at=row["expires_at"],
        created_at=row["created_at"] or "",
        last_login=row["last_login"],
    )


# ---------------------------------------------------------------------------
# DB init
# ---------------------------------------------------------------------------

def init_db() -> None:
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                username        TEXT    UNIQUE NOT NULL,
                display_name    TEXT    DEFAULT '',
                email           TEXT    DEFAULT '',
                password_hash   TEXT    NOT NULL,
                role            TEXT    DEFAULT 'user',
                is_active       INTEGER DEFAULT 1,
                allowed_tools   TEXT    DEFAULT 'all',
                expires_at      TEXT    DEFAULT NULL,
                created_at      TEXT    NOT NULL,
                last_login      TEXT    DEFAULT NULL
            )
        """)
        # Ensure default admin exists
        existing = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
        if not existing:
            pw_hash, _ = _hash_password("admin123")
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO users (username, display_name, password_hash, role, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("admin", "Administrator", pw_hash, "admin", now),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def create_user(
    username: str,
    display_name: str,
    email: str,
    password: str,
    role: str = "user",
) -> User:
    pw_hash, _ = _hash_password(password)
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (username, display_name, email, password_hash, role, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (username, display_name, email, pw_hash, role, now),
            )
            conn.commit()
            return get_user_by_id(cur.lastrowid)
        except sqlite3.IntegrityError:
            raise ValueError(f"Username '{username}' already exists.")


def get_user_by_id(user_id: int) -> Optional[User]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None


def get_user_by_username(username: str) -> Optional[User]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return _row_to_user(row) if row else None


def list_users() -> list[User]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
        return [_row_to_user(r) for r in rows]


def update_user(
    user_id: int,
    display_name: str | None = None,
    email: str | None = None,
    password: str | None = None,
) -> User:
    with _get_conn() as conn:
        user = get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found.")
        dn = display_name if display_name is not None else user.display_name
        em = email if email is not None else user.email
        if password:
            pw_hash, _ = _hash_password(password)
            conn.execute(
                "UPDATE users SET display_name=?, email=?, password_hash=? WHERE id=?",
                (dn, em, pw_hash, user_id),
            )
        else:
            conn.execute(
                "UPDATE users SET display_name=?, email=? WHERE id=?",
                (dn, em, user_id),
            )
        conn.commit()
    return get_user_by_id(user_id)


def delete_user(user_id: int) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()


def set_user_active(user_id: int, active: bool) -> None:
    with _get_conn() as conn:
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(active), user_id))
        conn.commit()


def touch_last_login(user_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, user_id))
        conn.commit()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def authenticate(username: str, password: str) -> Optional[User]:
    user = get_user_by_username(username)
    if not user or not user.is_active:
        return None
    if not _verify_password(password, user.password_hash):
        return None
    return user


def set_session_cookie(response: Response, user: User) -> None:
    from itsdangerous import URLSafeTimedSerializer
    secret = _get_secret_key()
    serializer = URLSafeTimedSerializer(secret)
    token = serializer.dumps({"uid": user.id})
    response.set_cookie(
        _COOKIE_NAME,
        value=token,
        max_age=_SESSION_MAX_AGE_DAYS * 86400,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(_COOKIE_NAME, path="/")


def get_current_user(request: Request) -> Optional[User]:
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        return None
    secret = _get_secret_key()
    serializer = URLSafeTimedSerializer(secret)
    try:
        data = serializer.loads(token, max_age=_SESSION_MAX_AGE_DAYS * 86400)
    except (SignatureExpired, BadSignature, Exception):
        return None
    user = get_user_by_id(data.get("uid", 0))
    if user and not user.is_active:
        return None
    return user


def require_user(request: Request) -> User:
    user = get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=307,
            detail="Login required",
            headers={"Location": "/login?next=" + str(request.url.path)},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled.")
    return user


def require_admin(request: Request) -> User:
    user = require_user(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


def _get_secret_key() -> str:
    key_path = _DB_PATH.parent / ".session_secret"
    if key_path.exists():
        return key_path.read_text().strip()
    key = secrets.token_hex(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(key)
    return key


# ---------------------------------------------------------------------------
# Access control — tool permissions & expiry
# ---------------------------------------------------------------------------

def _parse_tools(raw: str) -> list[str]:
    if not raw or raw.strip().lower() == "all":
        return list(TOOL_SLUGS)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [t for t in parsed if t in TOOL_SLUGS]
    except (json.JSONDecodeError, TypeError):
        pass
    return [t.strip() for t in raw.split(",") if t.strip() in TOOL_SLUGS]


def _serialize_tools(tools: list[str]) -> str:
    if set(tools) >= set(TOOL_SLUGS):
        return "all"
    return json.dumps(sorted(tools))


def is_tool_allowed(user: User, tool_slug: str) -> bool:
    if user.is_admin:
        return True
    if not user.is_active:
        return False
    if user.expires_at:
        try:
            exp = datetime.fromisoformat(user.expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                return False
        except (ValueError, TypeError):
            pass
    allowed = _parse_tools(user.allowed_tools)
    return tool_slug in allowed


def set_user_tools(user_id: int, tools: list[str] | str) -> None:
    if isinstance(tools, str):
        if tools.strip().lower() == "all":
            serialized = "all"
        else:
            serialized = _serialize_tools([t.strip() for t in tools.split(",") if t.strip()])
    else:
        serialized = _serialize_tools(tools)
    with _get_conn() as conn:
        conn.execute("UPDATE users SET allowed_tools = ? WHERE id = ?", (serialized, user_id))
        conn.commit()


def set_user_expiry(user_id: int, expires_at: str | None) -> None:
    with _get_conn() as conn:
        conn.execute("UPDATE users SET expires_at = ? WHERE id = ?", (expires_at, user_id))
        conn.commit()


def set_user_role(user_id: int, role: str) -> None:
    if role not in ("admin", "user"):
        raise ValueError("Invalid role.")
    with _get_conn() as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        conn.commit()


def reset_user_password(user_id: int, new_password: str) -> None:
    pw_hash, _ = _hash_password(new_password)
    with _get_conn() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, user_id))
        conn.commit()
