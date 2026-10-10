import pytest

from app import auth


@pytest.fixture(autouse=True)
def password(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "correct horse")
    monkeypatch.delenv("SESSION_SECRET", raising=False)


def test_password_check():
    assert auth.check_password("correct horse")
    assert not auth.check_password("correct horse ")
    assert not auth.check_password("")


def test_token_round_trip_and_expiry():
    token = auth.make_token(now=1_000_000)
    assert auth.valid_token(token, now=1_000_000 + 60)
    assert not auth.valid_token(token, now=1_000_000 + auth.MAX_AGE + 1)


def test_tampered_tokens_are_rejected():
    token = auth.make_token()
    version, expires, sig = token.split(".")
    assert not auth.valid_token(f"{version}.{int(expires) + 10**6}.{sig}")
    assert not auth.valid_token(token[:-2] + "xx")
    assert not auth.valid_token("garbage")
    assert not auth.valid_token(None)


def test_changing_the_password_logs_everyone_out(monkeypatch):
    token = auth.make_token()
    monkeypatch.setenv("DASHBOARD_PASSWORD", "new password")
    assert not auth.valid_token(token)


def test_session_secret_takes_precedence(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "s3cret")
    token = auth.make_token()
    monkeypatch.setenv("DASHBOARD_PASSWORD", "rotated")
    assert auth.valid_token(token)


def test_editing_disabled_without_password(monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSWORD")
    assert not auth.editing_enabled()
    assert not auth.check_password("anything")
    assert not auth.valid_token("v1.9999999999.abc")
