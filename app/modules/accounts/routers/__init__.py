from fastapi import APIRouter

from app.modules.accounts.routers import account, auth

router = APIRouter()
router.include_router(auth.router)
router.include_router(account.router)
