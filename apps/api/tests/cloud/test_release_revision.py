import pytest

from app.config import Settings


def test_render_commit_identifies_the_running_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RELEASE_REVISION", raising=False)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    assert Settings(_env_file=None).release_revision == "a" * 40


def test_explicit_release_revision_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELEASE_REVISION", "b" * 40)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    assert Settings(_env_file=None).release_revision == "b" * 40
    explicit = Settings(_env_file=None, release_revision="test-release")
    assert explicit.release_revision == "test-release"


def test_local_release_default_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RELEASE_REVISION", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    assert Settings(_env_file=None).release_revision == "development"
