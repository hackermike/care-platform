"""Run Alembic migrations on startup so the database always matches the models.

Alembic owns the schema (see CLAUDE.md). This mirrors Breakout Billing's pattern.
"""
import os

from alembic import command
from alembic.config import Config

_ROOT = os.path.dirname(os.path.dirname(__file__))


def run_migrations() -> None:
    cfg = Config(os.path.join(_ROOT, "alembic.ini"))
    command.upgrade(cfg, "head")
