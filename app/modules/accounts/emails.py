"""The signup code letter: one five-digit code, valid for a few minutes."""

from html import escape

from app.common.mail import Mail

WORDS: dict[str, dict[str, str]] = {
    "uz": {
        "subject": "{code} — TargetologAI tasdiqlash kodi",
        "hello": "Assalomu alaykum, {name}!",
        "lead": "TargetologAI'da ro'yxatdan o'tishni yakunlash uchun quyidagi kodni kiriting:",
        "valid": "Kod {minutes} daqiqa amal qiladi.",
        "ignore": "Agar siz ro'yxatdan o'tmagan bo'lsangiz, bu xatni e'tiborsiz qoldiring.",
        "never": "Bu kodni hech kimga bermang — TargetologAI xodimlari uni hech qachon so'ramaydi.",
        "team": "TargetologAI jamoasi",
    },
    "ru": {
        "subject": "{code} — код подтверждения TargetologAI",
        "hello": "Здравствуйте, {name}!",
        "lead": "Чтобы завершить регистрацию в TargetologAI, введите этот код:",
        "valid": "Код действует {minutes} минуты.",
        "ignore": "Если вы не регистрировались, просто проигнорируйте это письмо.",
        "never": "Никому не сообщайте этот код — сотрудники TargetologAI никогда его не спрашивают.",
        "team": "Команда TargetologAI",
    },
    "en": {
        "subject": "{code} — your TargetologAI confirmation code",
        "hello": "Hello, {name}!",
        "lead": "To finish signing up for TargetologAI, enter this code:",
        "valid": "The code is valid for {minutes} minutes.",
        "ignore": "If you did not sign up, you can safely ignore this email.",
        "never": "Never share this code — TargetologAI staff will never ask for it.",
        "team": "The TargetologAI team",
    },
}


def signup_code_mail(
    *, to: str, name: str, code: str, minutes: int, language: str
) -> Mail:
    words = WORDS.get(language, WORDS["uz"])
    hello = words["hello"].format(name=name or to.split("@")[0])
    valid = words["valid"].format(minutes=minutes)
    text = "\n\n".join(
        [
            hello,
            words["lead"],
            code,
            valid,
            words["ignore"],
            words["never"],
            words["team"],
        ]
    )
    digits = "".join(
        f'<td style="width:48px;height:60px;border:1px solid #d6dcf5;border-radius:12px;'
        f"background:#f5f7ff;font-size:30px;font-weight:700;color:#1f2a5c;"
        f'text-align:center;font-family:Consolas,Menlo,monospace;">{escape(digit)}</td>'
        f'<td style="width:8px;"></td>'
        for digit in code
    )
    html = f"""<!doctype html>
<html lang="{escape(language)}">
<body style="margin:0;padding:0;background:#eef1f8;font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef1f8;padding:32px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 18px rgba(31,42,92,0.08);">
<tr><td style="background:linear-gradient(135deg,#3b5bdb,#7048e8);padding:24px 28px;">
<div style="font-size:22px;font-weight:700;color:#ffffff;letter-spacing:0.3px;">Targetolog<span style="color:#ffd43b;">AI</span></div>
</td></tr>
<tr><td style="padding:28px;">
<p style="margin:0 0 12px;font-size:17px;color:#1f2a5c;font-weight:600;">{escape(hello)}</p>
<p style="margin:0 0 22px;font-size:15px;line-height:22px;color:#4a5578;">{escape(words["lead"])}</p>
<table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:0 auto 20px;"><tr>{digits}</tr></table>
<p style="margin:0 0 22px;text-align:center;font-size:14px;color:#3b5bdb;font-weight:600;">&#9201; {escape(valid)}</p>
<p style="margin:0 0 8px;font-size:13px;line-height:19px;color:#7a84a6;">{escape(words["ignore"])}</p>
<p style="margin:0;font-size:13px;line-height:19px;color:#7a84a6;">{escape(words["never"])}</p>
</td></tr>
<tr><td style="padding:16px 28px;background:#f7f8fc;font-size:12px;color:#9aa3c2;">{escape(words["team"])} · targetolog.ai</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
    return Mail(to=to, subject=words["subject"].format(code=code), text=text, html=html)
