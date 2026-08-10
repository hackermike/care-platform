"""Sending mail.

Deliberately an interface with no real implementation yet, because choosing a
provider is not an engineering decision here — it needs a **BAA**
(`docs/DEPLOYMENT.md`). Even an invitation email is PHI-adjacent: it reveals that
a named person has a relationship with a named therapy network, which is exactly
the kind of disclosure HIPAA exists to govern.

So this module defines the seam and refuses to guess. In dev the sender writes to
the log; outside dev, an unconfigured sender raises at send time rather than
silently dropping a password-reset link — a swallowed email is indistinguishable
from a broken account, and users would be locked out with no signal.
"""
import logging
from dataclasses import dataclass
from typing import Protocol

from app import config

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """The message could not be sent."""


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    body: str


class Sender(Protocol):
    def send(self, message: Message) -> None: ...


class LoggingSender:
    """Dev only. Writes the message where a developer can read it.

    Logs the full body, links included — which is precisely why it must never be
    the sender outside dev, and why `for_environment()` will not return it there.
    """

    def send(self, message: Message) -> None:
        logger.info(
            "email (not actually sent)\n  to: %s\n  subject: %s\n\n%s",
            message.to,
            message.subject,
            message.body,
        )


class UnconfiguredSender:
    """The production default until a BAA-covered provider is wired up.

    Raises rather than no-ops. A silently dropped reset email looks identical to
    a broken account from the user's side, and they cannot tell you which.
    """

    def send(self, message: Message) -> None:
        raise NotificationError(
            "No email provider is configured. Sending mail from this platform "
            "requires a BAA-covered provider — see docs/DEPLOYMENT.md."
        )


def for_environment() -> Sender:
    return LoggingSender() if config.IS_DEV else UnconfiguredSender()
