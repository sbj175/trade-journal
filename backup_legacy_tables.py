#!/usr/bin/env python3
"""
Backup Legacy Tables
Creates a backup of legacy trade tables before removal
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = "trade_journal.db"
BACKUP_DIR = Path("legacy_backups")

def backup_legacy_tables():
    """Backup legacy tables to JSON files"""

    # Create backup directory
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Tables to backup
    legacy_tables = ['trades', 'option_legs', 'stock_legs']

    backup_summary = {
        'timestamp': timestamp,
        'database': DB_PATH,
        'tables': {}
    }

    for table_name in legacy_tables:
        print(f"\nBacking up {table_name}...")

        # Get count
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]

        # Get all rows
        cursor.execute(f"SELECT * FROM {table_name}")
        rows = [dict(row) for row in cursor.fetchall()]

        # Save to JSON
        backup_file = BACKUP_DIR / f"{table_name}_{timestamp}.json"
        with open(backup_file, 'w') as f:
            json.dump(rows, f, indent=2, default=str)

        print(f"  ✓ Backed up {count} rows to {backup_file}")
        backup_summary['tables'][table_name] = {
            'count': count,
            'file': str(backup_file)
        }

    # Save summary
    summary_file = BACKUP_DIR / f"backup_summary_{timestamp}.json"
    with open(summary_file, 'w') as f:
        json.dump(backup_summary, f, indent=2)

    conn.close()

    print(f"\n{'='*60}")
    print("Backup Complete!")
    print(f"Summary saved to: {summary_file}")
    print(f"{'='*60}")

    return backup_summary

if __name__ == "__main__":
    print("="*60)
    print("LEGACY TABLE BACKUP")
    print("="*60)
    print("\nThis will backup the following tables:")
    print("  - trades")
    print("  - option_legs")
    print("  - stock_legs")
    print(f"\nBackup location: {BACKUP_DIR.absolute()}")

    response = input("\nProceed with backup? (yes/no): ").strip().lower()
    if response == 'yes':
        backup_legacy_tables()
    else:
        print("Backup cancelled.")
