"""Exercise Compose environment projection with synthetic settings; never start services."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("api", "worker", "scheduler")


def resolved_environment(values: dict[str, str]) -> dict:
    # Explicit file and a minimal child environment prevent reading the user's .env
    # or accidentally activating their destinations. `config` makes no deliveries.
    command = (
        [os.environ["PROCURE_COMPOSE_BINARY"]]
        if os.environ.get("PROCURE_COMPOSE_BINARY") else ["docker", "compose"]
    )
    with tempfile.TemporaryDirectory() as directory:
        settings = Path(directory) / "synthetic.env"
        settings.write_text("\n".join(f"{key}='{value}'" for key, value in values.items()))
        result = subprocess.run(
            command + ["--env-file", str(settings), "-f", str(ROOT / "docker-compose.yml"),
                       "config", "--format", "json"],
            env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=30,
            check=True,
        )
    return json.loads(result.stdout)["services"]


class ComposeEnvironmentTests(unittest.TestCase):
    def test_defaults_disable_external_delivery_and_error_tracking(self) -> None:
        services = resolved_environment({})
        for service in SERVICES:
            values = services[service]["environment"]
            self.assertEqual(values.get("NOTIFICATION_EXTERNAL_ENABLED"), "false")
            self.assertEqual(json.loads(values["NOTIFICATION_WEBHOOK_DESTINATIONS"]), {})
            self.assertEqual(json.loads(values["NOTIFICATION_WEBHOOK_FORMATS"]), {})
            self.assertEqual(json.loads(values["NOTIFICATION_EMAIL_RECIPIENTS"]), {})
            self.assertEqual(values.get("SENTRY_ENABLED"), "false")
            self.assertEqual(values.get("SENTRY_DSN"), "")

    def test_operator_settings_reach_all_backend_processes_without_json_corruption(self) -> None:
        configured = {
            "NOTIFICATION_EXTERNAL_ENABLED": "true",
            "NOTIFICATION_WEBHOOK_DESTINATIONS": '{"owner":"https://example.invalid/$canary"}',
            "NOTIFICATION_WEBHOOK_FORMATS": '{"owner":"slack"}',
            "NOTIFICATION_SMTP_HOST": "smtp.example.invalid",
            "NOTIFICATION_SMTP_PORT": "2525",
            "NOTIFICATION_SMTP_STARTTLS": "true",
            "NOTIFICATION_SMTP_USERNAME": "synthetic-user",
            "NOTIFICATION_SMTP_PASSWORD": "synthetic-$canary",
            "NOTIFICATION_EMAIL_SENDER": "demo@example.invalid",
            "NOTIFICATION_EMAIL_RECIPIENTS": '{"owner":"test@example.invalid"}',
            "SENTRY_ENABLED": "true",
            "SENTRY_DSN": "https://synthetic@example.invalid/1",
            "SENTRY_ENVIRONMENT": "contract-test",
            "SENTRY_TRACES_SAMPLE_RATE": "0.1",
            "RELEASE_REVISION": "synthetic-revision",
            "NORMALIZATION_BATCH_SIZE": "17",
        }
        services = resolved_environment(configured)
        for service in SERVICES:
            for key, value in configured.items():
                with self.subTest(service=service, key=key):
                    # `config` escapes literal dollars for reusable Compose output.
                    # This is serialization, not a second environment interpolation:
                    # github.com/docker/compose/blob/v5.5.1/cmd/compose/config.go#L191-L193
                    self.assertEqual(
                        services[service]["environment"].get(key), value.replace("$", "$$")
                    )


if __name__ == "__main__":
    unittest.main()
