import sqlite3

def fix_db():
    conn = sqlite3.connect('egypt_buyers.db')
    cursor = conn.cursor()
    
    # Check if we have the unique index
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql LIKE '%post_url%' AND sql LIKE '%UNIQUE%'")
    unique_idx = cursor.fetchone()
    
    if unique_idx:
        idx_name = unique_idx[0]
        print(f"Found unique index on post_url: {idx_name}, dropping it...")
        cursor.execute(f"DROP INDEX {idx_name}")
        conn.commit()
        print("Dropped successfully.")
    else:
        # Check if the column definition has UNIQUE
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='buyer_leads'")
        sql = cursor.fetchone()[0]
        if 'UNIQUE' in sql and 'post_url' in sql:
            print("Table has inline UNIQUE constraint on post_url. Need to recreate table.")
            # Rename old table
            cursor.execute("ALTER TABLE buyer_leads RENAME TO buyer_leads_old")
            # Create new table (without UNIQUE on post_url)
            # Just let SQLAlchemy do it! We will drop the old one and use db.py to init.
            pass
        else:
            print("No UNIQUE constraint found on post_url.")
            
if __name__ == '__main__':
    fix_db()
