"""Password hashing.

Argon2id via argon2-cffi. Chosen over bcrypt because bcrypt silently truncates
input at 72 bytes, which turns a long passphrase into a weaker secret than the
user believes they chose.
"""
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with older/weaker parameters than current."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True
