# admin/web_app/main.py
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import jwt

app = FastAPI()
templates = Jinja2Templates(directory="admin/templates")

# Аутентификация администратора
async def get_current_admin(request: Request):
    token = request.cookies.get("admin_token")
    if not token:
        raise HTTPException(status_code=401)
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    user = await get_user_by_id(payload["user_id"])
    if user.role not in [UserRole.ADMIN, UserRole.SUPERADMIN]:
        raise HTTPException(status_code=403)
    return user

# ====== ДАШБОРД ======
@app.get("/admin", response_class=HTMLResponse)
async def dashboard(request: Request, admin: User = Depends(get_current_admin)):
    stats = {
        "total_users": await get_users_count(),
        "active_today": await get_active_users_today(),
        "premium_users": await get_premium_users_count(),
        "total_revenue": await get_total_revenue(),
        "messages_today": await get_messages_count_today()
    }
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "admin": admin, 
        "stats": stats
    })

# ====== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ======
@app.get("/admin/users", response_class=HTMLResponse)
async def users_list(
    request: Request, 
    page: int = 1, 
    search: str = "",
    admin: User = Depends(get_current_admin)
):
    users = await get_users_paginated(page=page, search=search)
    return templates.TemplateResponse("users.html", {
        "request": request, 
        "users": users,
        "page": page,
        "search": search
    })

@app.post("/admin/users/create")
async def create_user(
    telegram_id: int,
    email: str,
    subscription_tier: str = "free",
    admin: User = Depends(get_current_admin)
):
    user = await create_new_user(telegram_id, email, subscription_tier)
    await log_admin_action(admin.id, "create_user", user.id, f"Created with tier {subscription_tier}")
    return {"status": "ok", "user_id": user.id}

@app.post("/admin/users/{user_id}/edit")
async def edit_user(
    user_id: int,
    email: str = None,
    is_banned: bool = None,
    subscription_tier: str = None,
    admin: User = Depends(get_current_admin)
):
    user = await get_user_by_id(user_id)
    if email: user.email = email
    if is_banned is not None: user.is_banned = is_banned
    if subscription_tier: user.subscription_tier = subscription_tier
    await save_user(user)
    await log_admin_action(admin.id, "edit_user", user_id, f"Updated fields")
    return {"status": "ok"}

@app.post("/admin/users/{user_id}/delete")
async def delete_user(
    user_id: int,
    admin: User = Depends(get_current_admin)
):
    if admin.role != UserRole.SUPERADMIN:
        raise HTTPException(403, "Only superadmin can delete users")
    await soft_delete_user(user_id)
    await log_admin_action(admin.id, "delete_user", user_id, "User deleted")
    return {"status": "ok"}