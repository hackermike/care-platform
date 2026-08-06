from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.tokens import hash_token, new_token, tokens_equal


def test_hash_is_not_the_password():
    h = hash_password("hunter2-hunter2")
    assert h != "hunter2-hunter2"
    assert h.startswith("$argon2")


def test_verify_accepts_the_right_password():
    assert verify_password("hunter2-hunter2", hash_password("hunter2-hunter2"))


def test_verify_rejects_the_wrong_password():
    assert not verify_password("nope", hash_password("hunter2-hunter2"))


def test_hashes_are_salted():
    assert hash_password("same") != hash_password("same")


def test_long_passphrases_are_not_truncated():
    """bcrypt would silently ignore everything past 72 bytes, making these two
    equivalent. Argon2 does not — this is why it was chosen."""
    base = "a" * 72
    assert not verify_password(base + "different-tail", hash_password(base + "X"))


def test_verify_survives_a_corrupt_hash():
    assert not verify_password("anything", "not-a-real-hash")


def test_corrupt_hash_needs_rehash():
    assert needs_rehash("not-a-real-hash")


def test_current_hash_does_not_need_rehash():
    assert not needs_rehash(hash_password("hunter2-hunter2"))


class TestTokens:
    def test_tokens_are_unique(self):
        assert new_token() != new_token()

    def test_hash_is_stable_and_opaque(self):
        token = new_token()
        assert hash_token(token) == hash_token(token)
        assert token not in hash_token(token)

    def test_comparison(self):
        assert tokens_equal("abc", "abc")
        assert not tokens_equal("abc", "abd")
