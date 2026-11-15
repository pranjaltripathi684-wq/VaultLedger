"""Fill an empty VaultLedger database with ~6 months of realistic sample data.

Used by the hosted demo (api/index.py) so a visitor lands on a populated app.
Dates are relative to today, so "this month" always has activity.
Run locally with:  VAULTLEDGER_DB=demo.db python demo_seed.py
"""
import random
from datetime import date, timedelta

from db import get_db_connection, init_db

INR = 0.0120   # 1 INR = X USD (matches DEFAULT_MARKET_RATES in app.py)
USD = 1.0
EUR = 1.0920

ACCOUNTS = [
    ('HDFC Savings', 'checking', 42000, 'INR', '#4b5fc0'),
    ('ICICI Credit Card', 'credit', 0, 'INR', '#c0504b'),
    ('Cash Wallet', 'cash', 3000, 'INR', '#3f9b6b'),
    ('Wise USD', 'savings', 250, 'USD', '#b8862f'),
]

BUDGETS = [
    ('Food & Dining', 6000), ('Groceries', 5000), ('Transport', 2500),
    ('Shopping', 4000), ('Entertainment', 1500), ('Subscriptions', 1200),
]

RULES = [('swiggy', 'Food & Dining'), ('zomato', 'Food & Dining'), ('uber', 'Transport'),
         ('blinkit', 'Groceries'), ('netflix', 'Subscriptions')]


def month_start(d, back):
    y, m = d.year, d.month - back
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def build_transactions(today):
    rng = random.Random(42)
    rows = []  # (date, title, amount, type, category, notes, currency, rate, account)

    def add(d, title, amount, type_, cat, acct='HDFC Savings', notes='', cur='INR', rate=INR):
        if d <= today:
            rows.append((d.isoformat(), title, round(amount, 2), type_, cat, notes, cur, rate, acct))

    for back in range(5, -1, -1):
        start = month_start(today, back)
        def day(n):
            return start + timedelta(days=n - 1)

        # Income
        add(day(1), 'Internship stipend', 25000, 'income', 'Income', notes='Monthly stipend')
        if back % 2 == 0:
            add(day(12), 'Freelance web project (Upwork)', rng.choice([180, 240, 300]), 'income', 'Income',
                acct='Wise USD', cur='USD', rate=USD)
        # Fixed / recurring costs
        add(day(3), 'PG rent', 9500, 'expense', 'Housing')
        add(day(5), 'Jio fiber broadband', 699, 'expense', 'Utilities')
        add(day(8), 'Airtel postpaid', 399, 'expense', 'Utilities')
        add(day(10), 'Netflix', 199, 'expense', 'Subscriptions', acct='ICICI Credit Card')
        add(day(10), 'Spotify', 119, 'expense', 'Subscriptions', acct='ICICI Credit Card')
        add(day(15), 'GitHub Copilot', 10, 'expense', 'Subscriptions', acct='ICICI Credit Card', cur='USD', rate=USD)
        add(day(20), 'SIP - Nifty index fund', 3000, 'expense', 'Investments', notes='Monthly SIP')

        # Variable spending spread across the month
        for _ in range(rng.randint(7, 10)):
            add(day(rng.randint(1, 28)), rng.choice(['Swiggy order', 'Zomato dinner', 'Cafe coffee', 'Canteen lunch',
                                                     'Dominos pizza', 'Chai and snacks']),
                rng.uniform(80, 650), 'expense', 'Food & Dining', acct=rng.choice(['HDFC Savings', 'Cash Wallet']))
        for _ in range(rng.randint(3, 5)):
            add(day(rng.randint(1, 28)), rng.choice(['Blinkit groceries', 'DMart run', 'Zepto milk and eggs']),
                rng.uniform(250, 1400), 'expense', 'Groceries')
        for _ in range(rng.randint(4, 7)):
            add(day(rng.randint(1, 28)), rng.choice(['Uber to college', 'Rapido bike', 'Namma Metro card recharge', 'Ola auto']),
                rng.uniform(60, 420), 'expense', 'Transport', acct=rng.choice(['HDFC Savings', 'Cash Wallet']))
        for _ in range(rng.randint(1, 3)):
            add(day(rng.randint(1, 28)), rng.choice(['Amazon order', 'Flipkart - headphones', 'Myntra shirt', 'Books']),
                rng.uniform(300, 2200), 'expense', 'Shopping', acct='ICICI Credit Card')
        if rng.random() < 0.7:
            add(day(rng.randint(1, 28)), rng.choice(['Movie tickets (PVR)', 'Bowling with friends', 'Concert entry']),
                rng.uniform(300, 900), 'expense', 'Entertainment')

    # A couple of one-offs so the anomaly detector has something to find
    add(month_start(today, 2) + timedelta(days=17), 'Laptop repair', 7800, 'expense', 'Shopping',
        acct='ICICI Credit Card', notes='Motherboard fix')
    add(month_start(today, 1) + timedelta(days=21), 'Train tickets to Lucknow (IRCTC)', 2650, 'expense', 'Transport',
        notes='Trip home')
    add(month_start(today, 3) + timedelta(days=8), 'Hackathon prize', 150, 'income', 'Income',
        acct='Wise USD', cur='EUR', rate=EUR)

    rows.sort(key=lambda r: r[0])
    return rows


def seed(conn=None):
    """Seed only if the ledger is empty. Returns number of transactions inserted."""
    own = conn is None
    if own:
        init_db()
        conn = get_db_connection()
    try:
        if conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]:
            return 0
        today = date.today()
        conn.executemany('INSERT OR IGNORE INTO accounts (name, account_type, initial_balance, currency, color) '
                         'VALUES (?, ?, ?, ?, ?)', ACCOUNTS)
        conn.executemany('INSERT OR IGNORE INTO budgets (category, monthly_limit, currency) VALUES (?, ?, ?)',
                         [(c, lim, 'INR') for c, lim in BUDGETS])
        conn.executemany('INSERT INTO automation_rules (rule_name, match_field, match_keyword, action_category) '
                         'VALUES (?, ?, ?, ?)', [(f'{k} → {c}', 'title', k, c) for k, c in RULES])
        nxt = month_start(today, -1)
        conn.executemany('INSERT INTO subscriptions (name, amount, currency, billing_cycle, next_due_date, category) '
                         'VALUES (?, ?, ?, ?, ?, ?)', [
                             ('Netflix', 199, 'INR', 'monthly', (nxt + timedelta(days=9)).isoformat(), 'Subscriptions'),
                             ('Spotify', 119, 'INR', 'monthly', (nxt + timedelta(days=9)).isoformat(), 'Subscriptions'),
                             ('GitHub Copilot', 10, 'USD', 'monthly', (nxt + timedelta(days=14)).isoformat(), 'Subscriptions'),
                         ])
        conn.executemany('INSERT INTO savings_goals (title, target_amount, current_amount, target_date, currency, icon) '
                         'VALUES (?, ?, ?, ?, ?, ?)', [
                             ('New laptop', 85000, 31000, (today + timedelta(days=150)).isoformat(), 'INR', '💻'),
                             ('Emergency fund', 60000, 22500, None, 'INR', '🛟'),
                         ])
        rows = build_transactions(today)
        conn.executemany('INSERT INTO transactions (title, amount, type, category, date, notes, currency, '
                         'exchange_rate, account_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         [(t, a, ty, c, d, n, cur, r, acc) for d, t, a, ty, c, n, cur, r, acc in rows])
        conn.commit()
        return len(rows)
    finally:
        if own:
            conn.close()


if __name__ == '__main__':
    print(f'Inserted {seed()} demo transactions.')
