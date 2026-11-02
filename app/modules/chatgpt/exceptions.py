"""ChatGPT Ads refusals. Codes are spelled by hand: ``ChatGPT`` would snake into ``chat_gpt``."""

from app.common.exceptions import DomainError, NotFound, ProviderRefused


class ChatGPTAdsUnavailable(NotFound):
    code = "chatgpt_ads_unavailable"

    def __init__(self) -> None:
        super().__init__("Sahifa topilmadi.")


class ChatGPTNotConnected(DomainError):
    code = "chatgpt_not_connected"

    def __init__(self) -> None:
        super().__init__("Avval ChatGPT Ads akkauntini ulang.")


class ChatGPTKeyRequired(DomainError):
    code = "chatgpt_key_required"

    def __init__(self) -> None:
        super().__init__(
            "API kalitni kiriting. Uni ads.openai.com → Settings bo'limida yaratasiz."
        )


class ChatGPTKeyRejected(DomainError):
    code = "chatgpt_key_rejected"

    def __init__(self) -> None:
        super().__init__(
            "OpenAI bu kalitni qabul qilmadi. Kalitni ads.openai.com → Settings'dan qayta nusxalang yoki yangisini yarating."
        )


class ChatGPTUnreachable(DomainError):
    code = "chatgpt_unreachable"
    status_code = 503

    def __init__(self) -> None:
        super().__init__(
            "ChatGPT Ads hozir javob bermadi. Birozdan keyin qayta urinib ko'ring."
        )


class ChatGPTAccountTaken(DomainError):
    code = "chatgpt_account_taken"
    status_code = 409

    def __init__(self) -> None:
        super().__init__(
            "Bu ChatGPT Ads akkaunti boshqa kabinetga ulangan. Bitta akkaunt bitta kabinetda ishlaydi."
        )


class ChatGPTBudgetRequired(DomainError):
    code = "chatgpt_budget_required"

    def __init__(self) -> None:
        super().__init__("Kunlik byudjetni kiriting: kamida 1 (akkaunt valyutasida).")


class ChatGPTImageRefused(DomainError):
    code = "chatgpt_image_refused"

    def __init__(self) -> None:
        super().__init__("Rasm JPEG, PNG yoki WebP bo'lsin va 8 MB dan oshmasin.")


class ChatGPTDraftFailed(DomainError):
    code = "chatgpt_draft_failed"
    status_code = 503

    def __init__(self) -> None:
        super().__init__(
            "AI hozir matn yoza olmadi. Birozdan keyin qayta urinib ko'ring yoki o'zingiz yozing."
        )


class ChatGPTRefused(ProviderRefused):
    """OpenAI said no to a press; ``refusal`` is the cabinet's refusal dialog."""
