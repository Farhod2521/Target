MAX_POLLS = 20
POLL_SECONDS = 3
WATCH_TELEGRAM = "telegram"

# Where an unfinished cabinet is sent, as billing's ``back_url`` says it too.
START_PATH = "/app/start"
# The cabinet sections closed until "Yakunlash" (Django's onboarding
# middleware): its URL namespaces, and the connections screen.
CLOSED_SECTIONS = (
    "metrics",
    "ads",
    "google_ads",
    "leads",
    "chat",
    "agent",
    "destinations",
    "montage",
    "actions",
    "referrals",
    "integrations:connections",
)
CLOSED_MESSAGE = "Boshqa bo'limlar «Yakunlash» bosilgandan keyin ochiladi."
FINISHED_MESSAGE = "Tayyorgarlik yakunlandi."

__all__ = [
    "CLOSED_MESSAGE",
    "CLOSED_SECTIONS",
    "FINISHED_MESSAGE",
    "MAX_POLLS",
    "POLL_SECONDS",
    "START_PATH",
    "WATCH_TELEGRAM",
]
