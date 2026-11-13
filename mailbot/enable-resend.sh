#!/bin/sh
set -eu
cd "$(dirname "$0")"

python3 - <<'PY'
import getpass
import os
import tempfile
from pathlib import Path

key = getpass.getpass("Ключ Resend: ").strip()
if not key.startswith("re_") or any(char.isspace() for char in key):
    raise SystemExit("Введи ключ Resend, начинающийся на re_")

target = Path("secrets/resend_api_key")
with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as secret:
    pending = Path(secret.name)
    try:
        secret.write(key.encode())
        secret.flush()
        os.chown(pending, 10001, 10001)
        pending.chmod(0o400)
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
PY

docker compose -f compose.yaml -f compose.resend.yaml up -d --no-build --no-deps --force-recreate worker
