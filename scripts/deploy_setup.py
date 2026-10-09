"""Explicit offline foundation job, separate from HTTP startup and paid ingestion."""

import json
import subprocess
import sys

from pydantic import ValidationError

from app.config import DemoControlSettings, PublicDemoSettings

STEPS = (
    ("migrate", "alembic", "upgrade", "head"),
    ("provision", "scripts.provision_roles"),
    ("seed", "scripts.seed"),
    ("verify", "scripts.verify_data"),
    ("policy", "scripts.demo_policy", "--configure"),
)


def main() -> int:
    try:
        if not PublicDemoSettings().public_demo_enabled:
            raise ValueError("Enable public controls for deployment setup")
        DemoControlSettings()  # Require the fourth secret before changing anything.
    except ValidationError, ValueError:
        print(json.dumps({"status": "error", "error": "deployment_configuration"}))
        return 1
    for step, module, *args in STEPS:
        try:
            subprocess.run(
                [sys.executable, "-m", module, *args],
                check=True,
                capture_output=True,
                timeout=180,
            )
        except subprocess.SubprocessError, OSError:
            # Child stdout/stderr and exceptions may contain connection details.
            print(json.dumps({"step": step, "status": "error"}))
            return 1
        print(json.dumps({"step": step, "status": "ok"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
