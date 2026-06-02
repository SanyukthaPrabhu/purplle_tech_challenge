import sqlite3
from datetime import datetime, timezone

def shift():
    conn = sqlite3.connect('retail_analytics.db')
    c = conn.cursor()
    
    # Get today's date in YYYY-MM-DD format
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    print(f"Shifting transaction dates to: {today_str}")
    
    # Update occurred_at values
    c.execute(f"UPDATE transactions SET occurred_at = replace(occurred_at, '2026-04-10', '{today_str}')")
    conn.commit()
    
    print("Updated rows count:", conn.total_changes)
    print("Transactions range:", c.execute('select min(occurred_at), max(occurred_at) from transactions').fetchone())
    conn.close()

if __name__ == '__main__':
    shift()
