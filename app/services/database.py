# from . import __all__  # silence linters
from ..extensions import get_db_connection


# In database.py

from ..extensions import get_engine
from sqlalchemy import text  # <-- ADD THIS IMPORT

def ensure_indexes(table_name: str):
    """Ensure database indexes exist for optimal performance"""
    engine = get_engine()
    
    indexes = [
        f"CREATE INDEX IF NOT EXISTS idx_date_committed ON `{table_name}`(`DATE_COMMITTED`)",
        f"CREATE INDEX IF NOT EXISTS idx_hour_committed ON `{table_name}`(`HOUR_COMMITTED`)",
        f"CREATE INDEX IF NOT EXISTS idx_barangay ON `{table_name}`(`BARANGAY`)",
        f"CREATE INDEX IF NOT EXISTS idx_accident_hotspot ON `{table_name}`(`ACCIDENT_HOTSPOT`)",
        f"CREATE INDEX IF NOT EXISTS idx_date_hour ON `{table_name}`(`DATE_COMMITTED`, `HOUR_COMMITTED`)",
        f"CREATE INDEX IF NOT EXISTS idx_gender ON `{table_name}`(`GENDER`)",
        f"CREATE INDEX IF NOT EXISTS idx_offense_type ON `{table_name}`(`OFFENSE_TYPE`)",
        f"CREATE INDEX IF NOT EXISTS idx_alcohol_involvement ON `{table_name}`(`ALCOHOL_INVOLVEMENT`)",
    ]
    
    with engine.begin() as conn:
        for sql in indexes:
            try:
                conn.execute(text(sql))  # <-- WRAP sql WITH text()
            except Exception as e:
                pass  # Index already exists


def list_tables() -> set[str]:
    """
    List all tables in the database, excluding system tables.
    The 'users' table is excluded as it's for authentication only.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SHOW TABLES")
    tables = {t[0] for t in cur.fetchall()}
    cur.close()
    conn.close()
    
    # Exclude the users table from the list
    tables.discard('users')
    
    return tables

