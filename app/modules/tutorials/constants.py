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
