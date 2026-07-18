"""
REKOMND+ Auth Router
=====================
Handles login, registration, logout, profile management, and admin user panel.
All routes return HTML pages (Jinja2 templates) using a shared base layout.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from auth import (
    User,
    TOOL_SLUGS,
    authenticate,
    clear_session_cookie,
    create_user,
    delete_user,
    get_current_user,
    list_users,
    require_admin,
    require_user,
    reset_user_password,
    set_session_cookie,
    set_user_active,
    set_user_expiry,
    set_user_role,
    set_user_tools,
    touch_last_login,
    update_user,
    get_user_by_id,
    get_user_by_username,
)

BASE_DIR  = Path(__file__).resolve().parent.parent  # rekomnd_plus/
TMPL_DIR  = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TMPL_DIR))

router = APIRouter(tags=["Auth"])


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _tmpl(request: Request, name: str, ctx: dict = None, status_code: int = 200):
    user = get_current_user(request)
    base = {"current_user": user}
    if ctx:
        base.update(ctx)
    return templates.TemplateResponse(request, name, base, status_code=status_code)


# ─────────────────────────────────────────────
# Login
# ─────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request, next: str = "/"):
    user = get_current_user(request)
    if user:
        return RedirectResponse(next or "/", status_code=302)
    return _tmpl(request, "login.html", {"next": next, "tab": "login"})


@router.post("/login", include_in_schema=False)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    user = authenticate(username.strip(), password)
    if not user:
        return _tmpl(
            request, "login.html",
            {"error": "Invalid username or password. Please try again.", "tab": "login", "next": next},
            status_code=401,
        )
    touch_last_login(user.id)
    redirect_url = next if next and next.startswith("/") else "/"
    response = RedirectResponse(redirect_url, status_code=302)
    set_session_cookie(response, user)
    return response


# ─────────────────────────────────────────────
# Register
# ─────────────────────────────────────────────

@router.get("/register", response_class=HTMLResponse, include_in_schema=False)
async def register_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=302)
    return _tmpl(request, "login.html", {"tab": "register"})


@router.post("/register", include_in_schema=False)
async def register_submit(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(""),
    email: str = Form(""),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    username = username.strip()
    display_name = display_name.strip()
    email = email.strip()

    # Validation
    if len(username) < 3:
        return _tmpl(request, "login.html", {
            "error": "Username must be at least 3 characters.", "tab": "register",
        }, status_code=400)
    if len(password) < 6:
        return _tmpl(request, "login.html", {
            "error": "Password must be at least 6 characters.", "tab": "register",
        }, status_code=400)
    if password != confirm_password:
        return _tmpl(request, "login.html", {
            "error": "Passwords do not match.", "tab": "register",
        }, status_code=400)

    try:
        user = create_user(username, display_name or username, email, password, role="user")
    except ValueError as e:
        return _tmpl(request, "login.html", {
            "error": str(e), "tab": "register",
        }, status_code=400)

    touch_last_login(user.id)
    response = RedirectResponse("/", status_code=302)
    set_session_cookie(response, user)
    return response


# ─────────────────────────────────────────────
# Logout
# ─────────────────────────────────────────────

@router.get("/logout", include_in_schema=False)
async def logout(request: Request):
    response = RedirectResponse("/login", status_code=302)
    clear_session_cookie(response)
    return response


# ─────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────

@router.get("/profile", response_class=HTMLResponse, include_in_schema=False)
async def profile_page(request: Request):
    user = require_user(request)
    return _tmpl(request, "profile.html", {"user": user})


@router.post("/profile/update", include_in_schema=False)
async def profile_update(
    request: Request,
    display_name: str = Form(""),
    email: str = Form(""),
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
):
    user = require_user(request)
    errors = []
    new_pw = None

    if new_password:
        if not current_password:
            errors.append("Enter your current password to change it.")
        elif not authenticate(user.username, current_password):
            errors.append("Current password is incorrect.")
        elif len(new_password) < 6:
            errors.append("New password must be at least 6 characters.")
        elif new_password != confirm_password:
            errors.append("New passwords do not match.")
        else:
            new_pw = new_password

    if errors:
        return _tmpl(request, "profile.html", {
            "user": user, "errors": errors,
        }, status_code=400)

    updated = update_user(user.id, display_name.strip() or user.display_name, email.strip(), new_pw)
    return _tmpl(request, "profile.html", {
        "user": updated, "success": "Profile updated successfully!",
    })


# ─────────────────────────────────────────────
# Admin: User management
# ─────────────────────────────────────────────

@router.get("/admin/users", response_class=HTMLResponse, include_in_schema=False)
async def admin_users_page(request: Request):
    admin = require_admin(request)
    users = list_users()
    now_str = datetime.now().strftime("%Y-%m-%d")
    return _tmpl(request, "admin_users.html", {"users": users, "user": admin, "now_str": now_str})


@router.post("/admin/users/create", include_in_schema=False)
async def admin_create_user(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(""),
    email: str = Form(""),
    password: str = Form(...),
    role: str = Form("user"),
):
    require_admin(request)
    try:
        create_user(username.strip(), display_name.strip(), email.strip(), password, role)
    except ValueError as e:
        users = list_users()
        admin = get_current_user(request)
        return _tmpl(request, "admin_users.html", {
            "users": users, "user": admin, "error": str(e),
            "now_str": datetime.now().strftime("%Y-%m-%d"),
        }, status_code=400)
    return RedirectResponse("/admin/users?created=1", status_code=302)


@router.post("/admin/users/{user_id}/toggle", include_in_schema=False)
async def admin_toggle_user(request: Request, user_id: int):
    require_admin(request)
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found")
    set_user_active(user_id, not target.is_active)
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/admin/users/{user_id}/delete", include_in_schema=False)
async def admin_delete_user(request: Request, user_id: int):
    admin = require_admin(request)
    if admin.id == user_id:
        users = list_users()
        return _tmpl(request, "admin_users.html", {
            "users": users, "user": admin,
            "error": "You cannot delete your own account.",
            "now_str": datetime.now().strftime("%Y-%m-%d"),
        }, status_code=400)
    delete_user(user_id)
    return RedirectResponse("/admin/users?deleted=1", status_code=302)


@router.post("/admin/users/{user_id}/permissions", include_in_schema=False)
async def admin_set_permissions(request: Request, user_id: int):
    admin = require_admin(request)
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found")
    form = await request.form()
    grant_all = form.get("grant_all")
    if grant_all == "on":
        set_user_tools(user_id, "all")
    else:
        selected = [slug for slug in TOOL_SLUGS if form.get(f"tool_{slug}")]
        set_user_tools(user_id, selected if selected else [])
    return RedirectResponse("/admin/users?permissions=1", status_code=302)


@router.post("/admin/users/{user_id}/expiry", include_in_schema=False)
async def admin_set_expiry(request: Request, user_id: int):
    admin = require_admin(request)
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found")
    form = await request.form()
    expires_at = form.get("expires_at", "").strip() or None
    set_user_expiry(user_id, expires_at)
    return RedirectResponse("/admin/users?expiry=1", status_code=302)


@router.post("/admin/users/{user_id}/role", include_in_schema=False)
async def admin_set_role(request: Request, user_id: int):
    admin = require_admin(request)
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found")
    form = await request.form()
    role = form.get("role", "user").strip()
    if admin.id == user_id and role != "admin":
        users = list_users()
        return _tmpl(request, "admin_users.html", {
            "users": users, "user": admin,
            "error": "You cannot remove your own admin role.",
            "now_str": datetime.now().strftime("%Y-%m-%d"),
        }, status_code=400)
    set_user_role(user_id, role)
    return RedirectResponse("/admin/users?role=1", status_code=302)


@router.post("/admin/users/{user_id}/reset-password", include_in_schema=False)
async def admin_reset_password(request: Request, user_id: int):
    admin = require_admin(request)
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found")
    form = await request.form()
    new_password = form.get("new_password", "").strip()
    if len(new_password) < 6:
        users = list_users()
        return _tmpl(request, "admin_users.html", {
            "users": users, "user": admin,
            "error": "Password must be at least 6 characters.",
            "now_str": datetime.now().strftime("%Y-%m-%d"),
        }, status_code=400)
    reset_user_password(user_id, new_password)
    return RedirectResponse("/admin/users?password_reset=1", status_code=302)


# ─────────────────────────────────────────────
# API: current user info (JSON)
# ─────────────────────────────────────────────

@router.get("/api/auth/me")
async def api_me(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user.to_dict()
