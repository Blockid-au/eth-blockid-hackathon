"""Shared test defaults."""
import pytest


@pytest.fixture(autouse=True)
def _password_changes_enabled(monkeypatch):
    # production default is ADMIN_PASSWORD_LOCKED=1 (public demo); the password-change flows are tested unlocked,
    # tests of the locked mode set it back to "1" themselves (test_company_admins.py)
    monkeypatch.setenv("ADMIN_PASSWORD_LOCKED", "0")


def v5_on() -> bool:
    """VALUATION_V5 as the suite runs it. CI runs the whole suite twice (flag off and on); tests whose expectations
    differ branch on this: v4 expectations when off, v5 when on (docs/V5-READINESS.md)."""
    import os

    return os.environ.get("VALUATION_V5", "0").strip().lower() in ("1", "true", "yes", "on")


@pytest.fixture
def v5_mode() -> bool:
    return v5_on()
