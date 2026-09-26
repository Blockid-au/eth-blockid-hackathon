"""Shared test defaults."""
import pytest


@pytest.fixture(autouse=True)
def _password_changes_enabled(monkeypatch):
    # production default is ADMIN_PASSWORD_LOCKED=1 (public demo); the password-change flows are tested unlocked,
    # tests of the locked mode set it back to "1" themselves (test_company_admins.py)
    monkeypatch.setenv("ADMIN_PASSWORD_LOCKED", "0")
