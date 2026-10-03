import pytest

from garmin_analyzer.config import ConfigError, token_encryption_key
from garmin_analyzer.tokens import TokenCipher, TokenDecryptError, generate_key

TOKENS = '{"di_token": "access", "di_refresh_token": "refresh", "di_client_id": "client"}'


def test_tokens_round_trip_and_are_not_stored_in_the_clear() -> None:
    cipher = TokenCipher(generate_key())

    encrypted = cipher.encrypt(TOKENS)

    assert b"refresh" not in encrypted
    assert cipher.decrypt(encrypted) == TOKENS


def test_another_key_cannot_decrypt() -> None:
    encrypted = TokenCipher(generate_key()).encrypt(TOKENS)

    with pytest.raises(TokenDecryptError):
        TokenCipher(generate_key()).decrypt(encrypted)


def test_tampered_tokens_are_rejected() -> None:
    cipher = TokenCipher(generate_key())
    encrypted = bytearray(cipher.encrypt(TOKENS))
    encrypted[-1] ^= 1

    with pytest.raises(TokenDecryptError):
        cipher.decrypt(bytes(encrypted))


@pytest.mark.parametrize("keys", ["not-a-key", "{key},not-a-key"])
def test_invalid_key_is_a_configuration_error(keys: str) -> None:
    with pytest.raises(ConfigError, match="generate-key"):
        TokenCipher(keys.format(key=generate_key()))


def test_a_setting_without_any_key_is_a_configuration_error() -> None:
    with pytest.raises(ConfigError, match="holds no key"):
        TokenCipher(" , ")


def test_replacing_the_key_keeps_old_tokens_readable() -> None:
    old_key, new_key = generate_key(), generate_key()
    old = TokenCipher(old_key).encrypt(TOKENS)
    rotating = TokenCipher(f"{new_key}, {old_key}")

    assert rotating.decrypt(old) == TOKENS
    assert not rotating.is_current(old)
    # New tokens are written with the first key only, so the old one can go.
    renewed = rotating.encrypt(TOKENS)
    assert rotating.is_current(renewed)
    assert TokenCipher(new_key).decrypt(renewed) == TOKENS
    with pytest.raises(TokenDecryptError):
        TokenCipher(old_key).decrypt(renewed)


def test_key_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    key = generate_key()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)

    assert token_encryption_key() == key


def test_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)

    with pytest.raises(ConfigError, match="TOKEN_ENCRYPTION_KEY is not set"):
        token_encryption_key()
