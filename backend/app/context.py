from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .config import Settings
from .db import Database
from .providers.registry import ProviderRegistry

log = logging.getLogger("cloudreader")


@dataclass
class AppContext:
    settings: Settings
    db: Database
    providers: ProviderRegistry
    worker: object | None = field(default=None)

    @classmethod
    def create(cls, settings: Settings, providers: ProviderRegistry | None = None) -> "AppContext":
        settings.ensure_dirs()
        db = Database(settings.db_path)
        db.migrate()
        ctx = cls(settings, db, providers or ProviderRegistry.from_settings(settings))
        from .services.profiles import ensure_default_profiles

        ensure_default_profiles(ctx)
        return ctx
