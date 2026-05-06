# admin/web_app/main.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
from datetime import datetime, timedelta
from typing import Optional
import jwt

from core.config import settings
from core.db import init_db, close_db, get_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()

app = FastAPI(title="TeleMail Admin", version="1.0.0", lifespan=lifespan)

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))

def render_template(name: str, **kwargs) -> HTMLResponse:
    template = jinja_env.get_template(name)
    return HTMLResponse(template.render(**kwargs))

# ------------------ Аутентификация ------------------
async def get_current_admin(request: Request):
    token = request.cookies.get("admin_token") or request.headers.get("X-Admin-API-Key")
    if not token:
        raise HTTPException(status_code=401, detail="Auth required")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        async with get_db() as db:
            result = await db.execute(
                "SELECT id, email, role FROM users WHERE id = :uid",
                {"uid": payload["user_id"]}
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=403, detail="User not found")
            return {"id": row[0], "email": row[1], "role": row[2]}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def admin_required(admin = Depends(get_current_admin)):
    if admin["role"] not in ("ADMIN", "SUPERADMIN"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return admin

# ------------------ Страницы ------------------
@app.get("/admin/login", response_class=HTMLResponse)
async def login_page():
    return render_template("login.html")

@app.post("/admin/login")
async def login_action(request: Request, email: str = Form(...), password: str = Form(...)):
    import bcrypt
    async with get_db() as db:
        result = await db.execute(
            "SELECT id, email, role, admin_password_hash FROM users WHERE email = :email",
            {"email": email}
        )
        row = result.fetchone()
        if not row or row[3] is None or not bcrypt.checkpw(password.encode(), row[3].encode()):
            return render_template("login.html", error="Invalid credentials")

        token = jwt.encode(
            {"user_id": row[0], "role": row[2], "exp": datetime.utcnow() + timedelta(hours=12)},
            settings.JWT_SECRET,
            algorithm="HS256"
        )
        response = RedirectResponse("/admin", status_code=302)
        response.set_cookie("admin_token", token, httponly=True, max_age=43200)
        return response

@app.get("/admin", response_class=HTMLResponse)
async def dashboard(request: Request, admin = Depends(admin_required)):
    async with get_db() as db:
        total_users = (await db.execute("SELECT COUNT(*) FROM users WHERE is_deleted = false")).scalar()
        active_today = (await db.execute(
            "SELECT COUNT(*) FROM users WHERE last_active_at >= :today AND is_deleted = false",
            {"today": datetime.utcnow().date()}
        )).scalar()
        premium = (await db.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_tier IN ('pro','business') AND is_deleted = false"
        )).scalar()

    stats = {
        "total_users": total_users or 0,
        "active_users_today": active_today or 0,
        "premium_users": premium or 0,
    }
    return render_template("dashboard.html", admin=admin, stats=stats)

@app.get("/admin/users", response_class=HTMLResponse)
async def users_list(request: Request, admin = Depends(admin_required), page: int = 1, search: str = ""):
    per_page = 50
    offset = (page - 1) * per_page
    async with get_db() as db:
        if search:
            count = (await db.execute(
                "SELECT COUNT(*) FROM users WHERE email ILIKE :s OR phone_number ILIKE :s",
                {"s": f"%{search}%"}
            )).scalar()
            users = (await db.execute(
                "SELECT * FROM users WHERE email ILIKE :s OR phone_number ILIKE :s ORDER BY created_at DESC LIMIT :limit OFFSET :offset",
                {"s": f"%{search}%", "limit": per_page, "offset": offset}
            )).fetchall()
        else:
            count = (await db.execute("SELECT COUNT(*) FROM users")).scalar()
            users = (await db.execute(
                "SELECT * FROM users ORDER BY created_at DESC LIMIT :limit OFFSET :offset",
                {"limit": per_page, "offset": offset}
            )).fetchall()
        total_pages = max(1, (count + per_page - 1) // per_page)
        return render_template("users.html", admin=admin, users=users, page=page, total_pages=total_pages, search=search)

@app.post("/api/admin/users/{user_id}/edit")
async def edit_user(user_id: int, email: Optional[str] = Form(None), tier: Optional[str] = Form(None), is_banned: Optional[bool] = Form(None), ban_reason: Optional[str] = Form(None), admin = Depends(admin_required)):
    async with get_db() as db:
        if email:
            await db.execute("UPDATE users SET email = :email WHERE id = :id", {"email": email, "id": user_id})
        if tier:
            await db.execute("UPDATE users SET subscription_tier = :tier WHERE id = :id", {"tier": tier, "id": user_id})
        if is_banned is not None:
            await db.execute("UPDATE users SET is_banned = :ban, ban_reason = :reason WHERE id = :id",
                             {"ban": is_banned, "reason": ban_reason, "id": user_id})
        await db.commit()
    return JSONResponse({"status": "ok"})
