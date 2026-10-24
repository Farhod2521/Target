from fastapi import APIRouter

from app.modules.accounts.routers import router as accounts
from app.modules.ads.routers import router as campaigns
from app.modules.billing.routers import router as billing
from app.modules.billing.routers import webhooks as billing_webhooks
from app.modules.businesses.routers import router as businesses
from app.modules.crm.routers import router as crm
from app.modules.integrations.routers import router as integrations
from app.modules.leads.routers import router as leads
from app.modules.leads.routers import webhooks as leads_webhooks
from app.modules.metrics.routers import router as metrics
from app.modules.miniapp.routers import router as miniapp
from app.modules.notifications.routers import router as notifications
from app.modules.public.routers import callbacks as public_callbacks
from app.modules.public.routers import router as public
from app.modules.referrals.routers import landing as referral_landing
from app.modules.referrals.routers import router as referrals
from app.modules.sales.routers import router as sales

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(accounts)
api_router.include_router(businesses)
api_router.include_router(integrations)
api_router.include_router(billing)
api_router.include_router(referrals)
api_router.include_router(leads)
api_router.include_router(crm)
api_router.include_router(public)
api_router.include_router(sales)
api_router.include_router(notifications)
api_router.include_router(miniapp)
api_router.include_router(metrics)
api_router.include_router(campaigns)

public_router = APIRouter()
public_router.include_router(billing_webhooks)
public_router.include_router(referral_landing)
public_router.include_router(leads_webhooks)
public_router.include_router(public_callbacks)
