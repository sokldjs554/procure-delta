import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.mark.parametrize("account", [None, "", "   "])
def test_enabled_billing_requires_an_explicit_account(account):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            extraction_mode="hosted",
            extraction_credits_enabled=True,
            extraction_credit_account=account,
        )


def test_deterministic_pipeline_cannot_enable_hosted_billing():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            extraction_mode="deterministic",
            extraction_credits_enabled=True,
            extraction_credit_account="pipeline-budget",
        )


@pytest.mark.parametrize("units", [0, -1, True, 1.5])
def test_credit_units_must_be_positive_whole_units(units):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, extraction_credit_units=units)


def test_credit_settings_load_from_deployment_environment(monkeypatch):
    monkeypatch.setenv("EXTRACTION_MODE", "hosted")
    monkeypatch.setenv("EXTRACTION_CREDITS_ENABLED", "true")
    monkeypatch.setenv("EXTRACTION_CREDIT_ACCOUNT", "pipeline-budget")
    monkeypatch.setenv("EXTRACTION_CREDIT_UNITS", "2")
    settings = Settings(_env_file=None)
    assert settings.extraction_credit_units == 2
    assert settings.extraction_credits_enabled is True
