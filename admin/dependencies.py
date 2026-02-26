"""
Admin app dependencies: DatabaseManager instance and ADMIN_SECRET.

The admin process creates its own DatabaseManager — separate from the main app.
"""

import os
import logging

from src.database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")

admin_db = DatabaseManager(db_url=os.environ.get("DATABASE_URL"))
