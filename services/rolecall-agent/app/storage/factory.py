"""Repository construction."""

from functools import lru_cache

from app.config import get_settings
from app.domain.repository import InMemoryRepository, Repository
from app.storage.firestore import FirestoreRepository


@lru_cache
def get_repository() -> Repository:
    settings = get_settings()
    if settings.repository == "firestore":
        return FirestoreRepository(settings.project_id, settings.firestore_database)
    return InMemoryRepository()
