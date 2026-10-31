from fastapi import APIRouter

from app.modules.accounts.routers import router as accounts
from app.modules.ads.routers import router as campaigns
from app.modules.ads.routers.drafts import router as launch_drafts
from app.modules.ads.routers.google import router as google_ads
from app.modules.ads.routers.launch import router as launch
from app.modules.ads.routers.launch_forms import router as launch_forms
from app.modules.ads.routers.launch_media import router as launch_media
from app.modules.ads.routers.launch_review import router as launch_review
from app.modules.agent.routers import router as agent
from app.modules.backoffice.routers import router as office
from app.modules.billing.routers import router as billing
from app.modules.billing.routers import webhooks as billing_webhooks
from app.modules.businesses.routers import router as businesses
from app.modules.chat.routers import router as chat
from app.modules.crm.routers import router as crm
from app.modules.destinations.routers import router as destinations
from app.modules.integrations.routers import router as integrations
from app.modules.leads.routers import router as leads
from app.modules.leads.routers import webhooks as leads_webhooks
from app.modules.metrics.routers import router as metrics
from app.modules.miniapp.routers import router as miniapp
from app.modules.notifications.routers import router as notifications
from app.modules.notifications.routers.actions import router as actions
from app.modules.notifications.routers.webhooks import webhooks as telegram_webhooks
from app.modules.onboarding.routers import router as onboarding
from app.modules.public.routers import callbacks as public_callbacks
from app.modules.public.routers import router as public
from app.modules.referrals.routers import landing as referral_landing
from app.modules.referrals.routers import router as referrals
from app.modules.sales.routers import router as sales
from app.modules.supportchat.routers import router as support
from app.modules.surveys.routers import router as surveys

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(accounts)
api_router.include_router(businesses)
api_router.include_router(integrations)
api_router.include_router(billing)
api_router.include_router(referrals)
api_router.include_router(leads)
api_router.include_router(crm)
api_router.include_router(destinations)
api_router.include_router(public)
api_router.include_router(office)
api_router.include_router(sales)
api_router.include_router(notifications)
api_router.include_router(actions)
api_router.include_router(miniapp)
api_router.include_router(metrics)
api_router.include_router(campaigns)
# Before the launch's own routes: «drafts» is not a launch id.
api_router.include_router(launch_drafts)
api_router.include_router(launch)
api_router.include_router(launch_review)
api_router.include_router(launch_media)
api_router.include_router(launch_forms)
api_router.include_router(google_ads)
api_router.include_router(chat)
api_router.include_router(agent)
api_router.include_router(onboarding)
api_router.include_router(surveys)
api_router.include_router(support)

public_router = APIRouter()
public_router.include_router(billing_webhooks)
public_router.include_router(referral_landing)
public_router.include_router(leads_webhooks)
public_router.include_router(telegram_webhooks)
public_router.include_router(public_callbacks)
