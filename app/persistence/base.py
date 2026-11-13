"""Shared base for the repository modules.

``Repository`` (see ``app/persistence/repository.py``) composes one small class per
aggregate. Each of them only needs the pool, so the base is a single attribute.
"""

from __future__ import annotations

from app.persistence.db import Database


class DbRepository:
    def __init__(self, db: Database):
        self.db = db
