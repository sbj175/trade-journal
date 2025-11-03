#!/usr/bin/env python3
"""
Drop Legacy Tables
Removes legacy trade system tables from the database
Run backup_legacy_tables.py first!
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = "trade_journal.db"
BACKUP_DIR = Path("legacy_backups")

def verify_backup_exists():
    """Verify that a backup has been created"""
    if not BACKUP_DIR.exists():
        print("❌ ERROR: No backup directory found!")
        print(f"   Please run backup_legacy_tables.py first")
        return False

    backup_files = list(BACKUP_DIR.glob("backup_summary_*.json"))
    if not backup_files:
        print("❌ ERROR: No backup found!")
        print(f"   Please run backup_legacy_tables.py first")
        return False

    latest_backup = max(backup_files, key=lambda p: p.stat().st_mtime)
    print(f"✓ Found backup: {latest_backup}")
    return True

def drop_legacy_tables():
    """Drop legacy tables from database"""

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Tables to drop (in order to respect foreign keys)
    tables_to_drop = [
        'option_legs',    # Has FK to trades
        'stock_legs',     # Has FK to trades
        'trades'          # Parent table
    ]

    print("\nDropping tables...")

    for table_name in tables_to_drop:
        try:
            # Check if table exists
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name=?
            """, (table_name,))

            if cursor.fetchone():
                cursor.execute(f"DROP TABLE {table_name}")
                print(f"  ✓ Dropped {table_name}")
            else:
                print(f"  ⊘ {table_name} doesn't exist (already dropped?)")

        except Exception as e:
            print(f"  ❌ Error dropping {table_name}: {e}")
            conn.rollback()
            conn.close()
            return False

    conn.commit()
    conn.close()

    print(f"\n{'='*60}")
    print("Legacy tables successfully removed!")
    print(f"{'='*60}")

    return True

def verify_tables_dropped():
    """Verify tables were actually dropped"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table'
        AND name IN ('trades', 'option_legs', 'stock_legs')
        ORDER BY name
    """)

    remaining = cursor.fetchall()
    conn.close()

    if remaining:
        print("\n⚠️  WARNING: Some tables still exist:")
        for table in remaining:
            print(f"  - {table[0]}")
        return False
    else:
        print("\n✓ Verification successful: All legacy tables removed")
        return True

if __name__ == "__main__":
    print("="*60)
    print("DROP LEGACY TABLES")
    print("="*60)

    print("\n⚠️  WARNING: This will permanently remove:")
    print("  - trades table")
    print("  - option_legs table")
    print("  - stock_legs table")
    print("\nThese are no longer used by the application (V2 system is active)")

    # Verify backup exists
    print("\nChecking for backup...")
    if not verify_backup_exists():
        sys.exit(1)

    print("\n" + "="*60)
    response = input("Type 'DROP LEGACY TABLES' to confirm: ").strip()

    if response == 'DROP LEGACY TABLES':
        print()
        if drop_legacy_tables():
            verify_tables_dropped()
            print("\n✓ Migration complete!")
        else:
            print("\n❌ Migration failed!")
            sys.exit(1)
    else:
        print("\nCancelled.")
