import pytest

from app.config import Settings
from app.ops import extraction_credits


@pytest.mark.parametrize(
    "command, extra",
    [
        ("status", []),
        ("grant", ["--units", "5", "--request-id", "fund-1"]),
        ("resolve", ["--reservation", "extraction:test", "--decision", "refund"]),
    ],
)
def test_cli_uses_same_account_as_deployment_settings(monkeypatch, command, extra):
    seen = []

    async def capture(args):
        seen.append(args.account)
        return {}

    monkeypatch.setattr(extraction_credits, "run", capture)
    monkeypatch.setattr(
        "sys.argv", ["extraction_credits", command, "--account", " pipeline-budget ", *extra]
    )
    extraction_credits.main()
    settings = Settings(_env_file=None, extraction_credit_account=" pipeline-budget ")
    assert seen == [settings.extraction_credit_account]
