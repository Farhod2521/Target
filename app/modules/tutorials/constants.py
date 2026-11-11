from app.common.choices import Choices


class TutorialType(Choices):
    META = "meta"
    GOOGLE = "google"
    GPT = "gpt"


TUTORIAL_TYPE_LABELS = {
    TutorialType.META: "Meta",
    TutorialType.GOOGLE: "Google",
    TutorialType.GPT: "GPT",
}


class TutorialPlace(Choices):
    """A cabinet screen that shows its own lessons beside its work. A lesson
    with none is in the Darsliklar section only."""

    DASHBOARD = "dashboard"
    LAUNCH = "launch"
    CAMPAIGNS = "campaigns"
    LEADS = "leads"
    CRM = "crm"
    CHAT = "chat"
    AGENT = "agent"
    GOOGLE = "google"
    CHATGPT = "chatgpt"
    AUDIENCES = "audiences"
    MONTAGE = "montage"
    SURVEYS = "surveys"
    DESTINATIONS = "destinations"
    CONNECTIONS = "connections"
    BILLING = "billing"
    REFERRALS = "referrals"


TUTORIAL_PLACE_LABELS = {
    TutorialPlace.DASHBOARD: "Bosh sahifa",
    TutorialPlace.LAUNCH: "Reklama yaratish",
    TutorialPlace.CAMPAIGNS: "Reklamalar",
    TutorialPlace.LEADS: "Lidlar",
    TutorialPlace.CRM: "CRM",
    TutorialPlace.CHAT: "AI chat",
    TutorialPlace.AGENT: "AI agent",
    TutorialPlace.GOOGLE: "Google reklama",
    TutorialPlace.CHATGPT: "ChatGPT reklama",
    TutorialPlace.AUDIENCES: "Auditoriyalar",
    TutorialPlace.MONTAGE: "Montaj",
    TutorialPlace.SURVEYS: "So'rovnoma",
    TutorialPlace.DESTINATIONS: "Lidlarni yuborish",
    TutorialPlace.CONNECTIONS: "Ulanishlar",
    TutorialPlace.BILLING: "To'lov va tariflar",
    TutorialPlace.REFERRALS: "Referal",
}

TITLE_MAX = 200
DESCRIPTION_MAX = 5000
VIDEO_URL_MAX = 500
PAGE_SIZE = 50

IMAGE_TYPES = ("jpg", "jpeg", "png", "webp")
MAX_IMAGE_MB = 5
# What a browser's <video> plays by itself; a .mov is refused rather than
# stored and shown as a black box in Chrome.
VIDEO_TYPES = {"mp4": "video/mp4", "webm": "video/webm"}
MAX_VIDEO_MB = 1024
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024

IMAGE_DIR = "tutorials/images/%Y/%m/"
VIDEO_DIR = "tutorials/videos/%Y/%m/"
PARTIAL_UPLOAD_DIR = "tutorials/partial"
PARTIAL_UPLOAD_HOURS = 24

# The most one answer to a viewer carries. A request for the whole file
# gets its first piece, so a plain GET is never the video.
STREAM_PIECE_BYTES = 2 * 1024 * 1024
# How long a link from the list plays for. A lesson watched past it asks
# the list again.
PLAY_TOKEN_HOURS = 6
