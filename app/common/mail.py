"""Sending one email, through the backend EMAIL_BACKEND names.

``smtp`` sends for real; ``console`` writes the message to the log (development);
``memory`` keeps it in ``outbox`` (tests read codes from there).
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr

from app.common.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Mail:
    to: str
    subject: str
    text: str
    html: str = ""


outbox: list[Mail] = []


class MailNotSent(Exception):
    pass


def _message(mail: Mail) -> EmailMessage:
    name, address = parseaddr(settings.default_from_email)
    message = EmailMessage()
    message["From"] = formataddr((name, address))
    message["To"] = mail.to
    message["Subject"] = mail.subject
    message["Message-ID"] = make_msgid(domain=address.split("@")[-1] or None)
    message.set_content(mail.text)
    if mail.html:
        message.add_alternative(mail.html, subtype="html")
    return message


def _smtp(message: EmailMessage) -> None:
    timeout = settings.email_timeout
    if settings.email_use_ssl:
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.email_host,
            settings.email_port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
    else:
        server = smtplib.SMTP(settings.email_host, settings.email_port, timeout=timeout)
    with server:
        if settings.email_use_tls and not settings.email_use_ssl:
            server.starttls(context=ssl.create_default_context())
        if settings.email_host_user:
            server.login(settings.email_host_user, settings.email_host_password)
        server.send_message(message)


def send_mail(mail: Mail) -> None:
    backend = settings.email_backend
    if backend == "memory":
        outbox.append(mail)
        return
    if backend == "console":
        logger.warning("email to %s: %s\n%s", mail.to, mail.subject, mail.text)
        return
    try:
        _smtp(_message(mail))
    except (OSError, smtplib.SMTPException) as exc:
        logger.exception("email to %s not sent", mail.to)
        raise MailNotSent(str(exc)) from exc
