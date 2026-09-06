#!/usr/bin/env python3
"""Generate the ADMIN_USERNAME/ADMIN_PASSWORD_HASH/SECRET_KEY env lines for
the single-admin login.

Usage:
    cd backend
    python3 scripts/create_admin.py

Prompts for a username and password (hidden input), then prints the three
env var lines to add to your systemd unit's [Service] section (or a .env
file, if you wire one up) -- never prints the plaintext password.
"""
from __future__ import annotations

import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password  # noqa: E402


def main() -> int:
    username = input("Admin username: ").strip()
    if not username:
        print("Username cannot be empty.", file=sys.stderr)
        return 1

    password = getpass.getpass("Admin password: ")
    if len(password) < 8:
        print("Password should be at least 8 characters.", file=sys.stderr)
        return 1
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match.", file=sys.stderr)
        return 1

    password_hash = hash_password(password)
    secret_key = secrets.token_hex(32)

    print("\nAdd these to /etc/systemd/system/options-app.service under [Service],")
    print("then `systemctl daemon-reload && systemctl restart options-app`:\n")
    print(f"Environment=ADMIN_USERNAME={username}")
    print(f"Environment=ADMIN_PASSWORD_HASH={password_hash}")
    print(f"Environment=SECRET_KEY={secret_key}")
    print(
        "\n(SECRET_KEY signs session cookies -- keep it secret and stable; "
        "changing it logs everyone out.)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
