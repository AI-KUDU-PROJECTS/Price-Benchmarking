"""Herfy binding for the shared official-source SQLite schema."""
from competitors.herfy.backend import config
from competitors.shared.backend.database import (
    MIGRATIONS,
    OFFER_SNAPSHOT_COLUMNS,
    PRODUCT_SNAPSHOT_COLUMNS,
    upsert_branch,
)
from competitors.shared.backend.database_binding import DatabaseBinding

_binding = DatabaseBinding(config.DB_PATH)
init_db = _binding.init_db
get_connection = _binding.get_connection
