from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
REVIEW_PROFILE = {
    "META_REVIEW_TENANT_ID": "11111111-1111-4111-8111-111111111111",
    "META_REVIEW_ACCOUNT_ID": "22222222-2222-4222-8222-222222222222",
    "META_REVIEW_WABA_ID": "111111111111111",
    "META_REVIEW_PHONE_NUMBER_ID": "222222222222222",
    "META_REVIEW_RECIPIENT": "15550123456",
}
HOST_REVIEW_PROFILE = {
    "META_REVIEW_TENANT_ID": "33333333-3333-4333-8333-333333333333",
    "META_REVIEW_ACCOUNT_ID": "44444444-4444-4444-8444-444444444444",
    "META_REVIEW_WABA_ID": "333333333333333",
    "META_REVIEW_PHONE_NUMBER_ID": "444444444444444",
    "META_REVIEW_RECIPIENT": "15550654321",
}


@pytest.mark.parametrize("manifest", ("docker-compose.yml", "compose.vps.yml"))
@pytest.mark.parametrize("profile_source", ("file", "host", "absent"))
def test_review_binding_reaches_both_servers_without_privileged_secrets(
    tmp_path: Path,
    manifest: str,
    profile_source: str,
) -> None:
    """Catch omitted panel settings and divergent Compose precedence."""
    (tmp_path / manifest).write_bytes((REPOSITORY_ROOT / manifest).read_bytes())
    file_values = {
        "SUPABASE_URL": "https://supabase.example.invalid",
        "SUPABASE_PUBLISHABLE_KEY": "synthetic-publishable-key",
        "APP_MASTER_KEY": "synthetic-server-master-key",
        "META_APP_SECRET": "synthetic-meta-app-secret",
    }
    if profile_source != "absent":
        file_values.update(REVIEW_PROFILE)
    (tmp_path / ".env").write_text(
        "".join(f"{key}={value}\n" for key, value in file_values.items())
    )
    environment = {
        key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ
    }
    if profile_source == "host":
        environment.update(HOST_REVIEW_PROFILE)

    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(tmp_path / ".env"),
            "-f",
            str(tmp_path / manifest),
            "config",
            "--format",
            "json",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    expected_profile = (
        HOST_REVIEW_PROFILE if profile_source == "host" else REVIEW_PROFILE
    )
    for service in ("backend", "control-plane"):
        effective_environment = services[service]["environment"]
        for name in REVIEW_PROFILE:
            expected_value = (
                "" if profile_source == "absent" else expected_profile[name]
            )
            assert effective_environment.get(name, "") == expected_value, (
                f"{manifest}: {service} is missing or differs on {name}"
            )
    panel_environment = services["control-plane"]["environment"]
    assert not any(
        name.startswith("NEXT_PUBLIC_META_REVIEW_") for name in panel_environment
    )
    for privileged_name in ("APP_MASTER_KEY", "META_APP_SECRET", "OPENAI_API_KEY"):
        assert privileged_name not in panel_environment
