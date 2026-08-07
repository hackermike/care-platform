"""Client-state vs. therapist-licensure checking.

`docs/DECISIONS.md`: the launch is state-agnostic *because* therapists are
listed rather than employed, which makes licensure the network's compliance
obligation. What the platform owes in return is this check — a therapist may
only see a client located in a state they are licensed in.

Deliberately a pure function over records, not a route guard: booking, intake,
and the admin roster all need the same answer, and duplicating the rule is how
the three drift apart.
"""
from dataclasses import dataclass

from app.models.provider import TherapistProfile
from app.timeutil import as_utc, utcnow


@dataclass(frozen=True)
class LicensureCheck:
    allowed: bool
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.allowed


UNKNOWN_CLIENT_STATE = "The client's state is unknown, so licensure cannot be checked."
NOT_LICENSED = "This therapist is not licensed in the client's state."
LICENSE_EXPIRED = "This therapist's licence in the client's state has expired."


def check(therapist: TherapistProfile, client_state: str | None) -> LicensureCheck:
    """May this therapist see a client located in `client_state`?

    An unknown client state fails closed. Guessing would mean asserting
    compliance the platform cannot actually vouch for, and the fix — ask the
    client where they are — is cheap.
    """
    if not client_state:
        return LicensureCheck(False, UNKNOWN_CLIENT_STATE)

    wanted = client_state.strip().upper()
    matching = [
        licence
        for licence in therapist.licenses
        if (licence.state or "").strip().upper() == wanted
    ]
    if not matching:
        return LicensureCheck(False, NOT_LICENSED)

    now = utcnow()
    # A licence with no expiry is treated as current: networks do not always
    # record one, and refusing every such record would block real practice.
    if all(
        (expiry := as_utc(licence.expires_on)) is not None and expiry <= now
        for licence in matching
    ):
        return LicensureCheck(False, LICENSE_EXPIRED)

    return LicensureCheck(True)


def licensed_states(therapist: TherapistProfile) -> list[str]:
    """The states a therapist may currently practise in, sorted."""
    now = utcnow()
    states = {
        (licence.state or "").strip().upper()
        for licence in therapist.licenses
        if (expiry := as_utc(licence.expires_on)) is None or expiry > now
    }
    return sorted(s for s in states if s)
