"""``pids-admin`` — operational commands.

pids-admin seed --site config/sites/site-alpha.yaml
    pids-admin index-procedures --dir config/sops
    Upsert the site, zones and tags, and create the demo accounts whose
    passwords are read from SEED_*_PASSWORD environment variables (generated
    into .env by `make env`). Passwords are never printed.
pids-admin create-user --email E --name N --role guard [--tag T] --password-env VAR
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import select

from pids_core.site import SiteConfig
from pids_server.db import models as m
from pids_server.db.session import Database
from pids_server.security import hash_password
from pids_server.settings import get_settings
from pids_server.site_store import upsert_site

DEMO_USERS = [
    ("admin@pids.local", "Site Administrator", m.Role.ADMIN, None, "SEED_ADMIN_PASSWORD"),
    (
        "operator@pids.local",
        "Control Room Operator",
        m.Role.OPERATOR,
        None,
        "SEED_OPERATOR_PASSWORD",
    ),
    (
        "guard.alpha@pids.local",
        "Guard — Patrol Alpha",
        m.Role.GUARD,
        "patrol-alpha",
        "SEED_GUARD_PASSWORD",
    ),
    (
        "guard.bravo@pids.local",
        "Guard — Patrol Bravo",
        m.Role.GUARD,
        "patrol-bravo",
        "SEED_GUARD_PASSWORD",
    ),
]


async def _ensure_user(
    db: Database, email: str, name: str, role: m.Role, tag: str | None, password: str
) -> bool:
    async with db.session() as s:
        existing = await s.scalar(select(m.User).where(m.User.email == email))
        if existing is not None:
            return False
        s.add(
            m.User(
                email=email, name=name, role=role, tag_id=tag, password_hash=hash_password(password)
            )
        )
        await s.commit()
        return True


async def seed(site_path: Path) -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    cfg = SiteConfig.from_yaml(site_path)
    async with db.session() as s:
        await upsert_site(s, cfg)
        await s.commit()
    sys.stdout.write(f"site {cfg.site.id}: {len(cfg.zones)} zones, {len(cfg.tags)} tags\n")
    for email, name, role, tag, env in DEMO_USERS:
        password = os.environ.get(env)
        if not password:
            sys.stdout.write(f"skip {email}: {env} not set\n")
            continue
        created = await _ensure_user(db, email, name, role, tag, password)
        sys.stdout.write(f"{'created' if created else 'exists '} {role.value:8s} {email}\n")
    await db.dispose()


async def create_user(email: str, name: str, role: str, tag: str | None, password_env: str) -> None:
    password = os.environ.get(password_env)
    if not password or len(password) < 12:
        raise SystemExit(f"{password_env} must hold a password of at least 12 characters")
    db = Database(get_settings().database_url)
    created = await _ensure_user(db, email, name, m.Role(role), tag, password)
    await db.dispose()
    sys.stdout.write("created\n" if created else "already exists\n")


async def index_procedures(folder: Path) -> None:
    """(Re)build the agent's procedure index from the SOP markdown files."""
    from pids_server.agent import procedures

    db = Database(get_settings().database_url)
    async with db.session() as s:
        n = await procedures.index(s, folder)
        await s.commit()
    await db.dispose()
    sys.stdout.write(f"indexed {n} procedure sections from {folder}\n")


async def reset_site(site_id: str) -> None:
    """Clear one site's alerts, history and agent reports (users, zones and tags stay).

    For rehearsals: restart the decision service afterwards so its in-memory alert
    state starts clean too (``make demo-reset`` does both).
    """
    from sqlalchemy import delete

    db = Database(get_settings().database_url)
    async with db.session() as s:
        counts = {}
        for model in (m.AgentReport, m.Observation, m.Alert):  # events/notifications cascade
            res = await s.execute(delete(model).where(model.site_id == site_id))
            counts[model.__tablename__] = res.rowcount  # type: ignore[attr-defined]
        await s.commit()
    await db.dispose()
    sys.stdout.write(f"reset {site_id}: {counts}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pids-admin", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed")
    s.add_argument("--site", type=Path, required=True)
    u = sub.add_parser("create-user")
    u.add_argument("--email", required=True)
    u.add_argument("--name", required=True)
    u.add_argument("--role", choices=[r.value for r in m.Role], required=True)
    u.add_argument("--tag")
    u.add_argument("--password-env", required=True)
    rs = sub.add_parser("reset-site")
    rs.add_argument("--site", required=True)
    ip = sub.add_parser("index-procedures")
    ip.add_argument("--dir", type=Path, default=Path("config/sops"))
    args = ap.parse_args(argv)
    if args.cmd == "seed":
        asyncio.run(seed(args.site))
    elif args.cmd == "reset-site":
        asyncio.run(reset_site(args.site))
    elif args.cmd == "index-procedures":
        asyncio.run(index_procedures(args.dir))
    else:
        asyncio.run(create_user(args.email, args.name, args.role, args.tag, args.password_env))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
