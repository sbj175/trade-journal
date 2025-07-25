#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect("trade_journal.db")
cursor = conn.cursor()

# Get table names
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print("Tables in database:")
for table in tables:
    print(f"  {table[0]}")

print("\n" + "="*50)

# Check orders table schema
print("\nORDERS table schema:")
cursor.execute("PRAGMA table_info(orders)")
columns = cursor.fetchall()
for col in columns:
    print(f"  {col[1]} ({col[2]})")

print("\n" + "="*50)

# Check positions table schema
print("\nPOSITIONS_NEW table schema:")
cursor.execute("PRAGMA table_info(positions_new)")
columns = cursor.fetchall()
for col in columns:
    print(f"  {col[1]} ({col[2]})")

print("\n" + "="*50)

# Check chains table schema
print("\nORDER_CHAINS table schema:")
cursor.execute("PRAGMA table_info(order_chains)")
columns = cursor.fetchall()
for col in columns:
    print(f"  {col[1]} ({col[2]})")

conn.close()