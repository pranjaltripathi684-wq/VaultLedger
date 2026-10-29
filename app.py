import os
import io
import csv
import math
import random
import hashlib
import calendar
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, Response, send_from_directory
from db import get_db_connection, init_db, SCHEMA_FILE
import intelligence as smart

app = Flask(__name__)
# Never ship a hard-coded session key: read it from the environment, or fall back
# to a random per-process key (only used to sign flash messages on legacy pages).
app.secret_key = os.environ.get('VAULTLEDGER_SECRET_KEY') or os.urandom(32).hex()

GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

# Standard Market Reference Rates to Base (1 Foreign Currency = X USD)
DEFAULT_MARKET_RATES = {
    'USD': 1.0000,
    'EUR': 1.0920,
    'GBP': 1.2850,
    'INR': 0.0120,
    'CAD': 0.7350,
    'JPY': 0.0069
}

CURRENCY_SYMBOLS = {
    'USD': '$',
    'EUR': '€',
    'GBP': '£',
    'INR': '₹',
    'CAD': '$',
    'JPY': '¥'
}


# ============================================================================
# 1. CRYPTOGRAPHIC LEDGER ENGINE (MULTI-CURRENCY AWARE)
# ============================================================================

def compute_row_hash(prev_hash, date_str, title, amount, type_, category, notes="", currency="USD", exchange_rate=1.0):
    payload = f"{prev_hash}|{date_str}|{title.strip()}|{amount:.2f}|{type_.strip()}|{category.strip()}|{(notes or '').strip()}|{currency}|{exchange_rate:.4f}"
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def is_valid_date(value):
    """True for a real calendar date in YYYY-MM-DD form (the format the DB CHECK expects)."""
    try:
        return datetime.strptime(str(value).strip(), '%Y-%m-%d').strftime('%Y-%m-%d') == str(value).strip()
    except (TypeError, ValueError):
        return False


def resolve_exchange_rate(raw_rate, currency):
    """Use the supplied rate if it is a positive number, otherwise the market default for the currency."""
    default = DEFAULT_MARKET_RATES.get(currency, 1.0)
    if raw_rate is None or str(raw_rate).strip() == '':
        return default
    try:
        rate = float(raw_rate)
    except (TypeError, ValueError):
        return default
    if rate <= 0 or math.isnan(rate) or math.isinf(rate):
        return default
    return rate


def parse_positive_float(value):
    """Parse a finite positive number or raise ValueError."""
    number = float(value)
    if number <= 0 or math.isnan(number) or math.isinf(number):
        raise ValueError
    return number


def ensure_columns(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(transactions)")
    columns = [col[1] for col in cursor.fetchall()]

    if not columns:
        # Fresh database: the transactions table does not exist yet, so ALTER TABLE
        # below would crash. Create every table from schema.sql first.
        with open(SCHEMA_FILE, encoding='utf-8') as schema_file:
            conn.executescript(schema_file.read())
        cursor.execute("PRAGMA table_info(transactions)")
        columns = [col[1] for col in cursor.fetchall()]

    if 'prev_hash' not in columns:
        conn.execute("ALTER TABLE transactions ADD COLUMN prev_hash TEXT NOT NULL DEFAULT ''")
    if 'curr_hash' not in columns:
        conn.execute("ALTER TABLE transactions ADD COLUMN curr_hash TEXT NOT NULL DEFAULT ''")
    if 'currency' not in columns:
        conn.execute("ALTER TABLE transactions ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'")
    if 'exchange_rate' not in columns:
        conn.execute("ALTER TABLE transactions ADD COLUMN exchange_rate REAL NOT NULL DEFAULT 1.0")
    if 'account_name' not in columns:
        conn.execute("ALTER TABLE transactions ADD COLUMN account_name TEXT NOT NULL DEFAULT 'Main Checking'")

    conn.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT UNIQUE NOT NULL,
            monthly_limit REAL NOT NULL CHECK(monthly_limit > 0),
            currency TEXT NOT NULL DEFAULT 'USD'
        )
    ''')

    cursor.execute("PRAGMA table_info(budgets)")
    b_cols = [col[1] for col in cursor.fetchall()]
    if 'currency' not in b_cols:
        conn.execute("ALTER TABLE budgets ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'")

    conn.execute('''
        CREATE TABLE IF NOT EXISTS dismissed_anomalies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER UNIQUE NOT NULL
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            account_type TEXT NOT NULL,
            initial_balance REAL NOT NULL DEFAULT 0.0,
            currency TEXT NOT NULL DEFAULT 'USD',
            color TEXT NOT NULL DEFAULT '#2563eb'
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            currency TEXT NOT NULL DEFAULT 'USD',
            billing_cycle TEXT NOT NULL DEFAULT 'monthly',
            next_due_date TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Software & Subscriptions'
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS savings_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            target_amount REAL NOT NULL CHECK(target_amount > 0),
            current_amount REAL NOT NULL DEFAULT 0.0,
            target_date TEXT,
            currency TEXT NOT NULL DEFAULT 'USD',
            icon TEXT NOT NULL DEFAULT '🎯'
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS automation_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_name TEXT NOT NULL,
            match_field TEXT NOT NULL DEFAULT 'title',
            match_keyword TEXT NOT NULL,
            action_category TEXT,
            flag_if_amount_above REAL DEFAULT 0.0
        )
    ''')

    conn.commit()


def rebuild_ledger_chain(conn):
    rows = conn.execute("SELECT * FROM transactions ORDER BY id ASC").fetchall()
    last_hash = GENESIS_HASH

    for r in rows:
        curr = r['currency'] if 'currency' in r.keys() else 'USD'
        rate = r['exchange_rate'] if 'exchange_rate' in r.keys() else 1.0
        expected_hash = compute_row_hash(
            last_hash, r['date'], r['title'], r['amount'], r['type'], r['category'], r['notes'], curr, rate
        )
        conn.execute(
            "UPDATE transactions SET prev_hash = ?, curr_hash = ? WHERE id = ?",
            (last_hash, expected_hash, r['id'])
        )
        last_hash = expected_hash
    conn.commit()


def verify_ledger_integrity(conn):
    rows = conn.execute("SELECT * FROM transactions ORDER BY id ASC").fetchall()
    last_hash = GENESIS_HASH

    for r in rows:
        if r['prev_hash'] != last_hash:
            return False, r['id'], len(rows)

        curr = r['currency'] if 'currency' in r.keys() else 'USD'
        rate = r['exchange_rate'] if 'exchange_rate' in r.keys() else 1.0
        computed = compute_row_hash(
            last_hash, r['date'], r['title'], r['amount'], r['type'], r['category'], r['notes'], curr, rate
        )
        if r['curr_hash'] != computed:
            return False, r['id'], len(rows)

        last_hash = r['curr_hash']

    return True, None, len(rows)


# ============================================================================
# 2. FOREIGN EXCHANGE (FX) GAIN/LOSS ENGINE (ASC 830 / IAS 21)
# ============================================================================

def calculate_fx_holdings_and_gains(transactions, current_market_rates, home='USD'):
    """
    Computes for every foreign currency:
      - Current Net Holding Balance
      - Weighted Average Cost Basis
      - Unrealized FX Gain / Loss (Mark-to-Market vs current market rate)
      - Realized Settled FX P&L
    """
    holdings = {}
    realized_gains_total = 0.0

    # Rates are stored as "1 unit = X USD". Re-express everything in the home currency so that
    # e.g. an INR-based user sees USD as the foreign holding and values in rupees.
    home_default = DEFAULT_MARKET_RATES.get(home, 1.0)
    home_market = current_market_rates.get(home, home_default)

    for curr in DEFAULT_MARKET_RATES.keys():
        if curr != home:
            holdings[curr] = {
                'balance': 0.0,
                'total_cost_basis_usd': 0.0,
                'realized_gain_usd': 0.0,
                'avg_cost_rate': 0.0
            }

    # Chronologically process transactions to accurately maintain inventory cost basis
    sorted_tx = sorted(transactions, key=lambda x: (x['date'], x['id']))

    for t in sorted_tx:
        curr = t['currency'] if 'currency' in t.keys() else 'USD'
        if curr == home or curr not in holdings:
            continue

        amt = t['amount']
        rate_at_booking = (t['exchange_rate'] if 'exchange_rate' in t.keys() else DEFAULT_MARKET_RATES[curr]) / home_default
        h = holdings[curr]

        # Signed quantity: inflows add units, outflows remove them.
        qty = amt if t['type'] == 'income' else -amt
        bal = h['balance']

        if bal == 0 or (bal > 0) == (qty > 0):
            # Opening or extending a position (long or short): accumulate cost basis
            h['balance'] = bal + qty
            h['total_cost_basis_usd'] += qty * rate_at_booking
        else:
            # Reducing an existing position: crystallize Realized FX Gain/Loss on the
            # units closed, valued at execution rate vs. weighted average cost.
            closing_units = min(abs(qty), abs(bal))
            direction = 1 if bal > 0 else -1
            trade_realized_gain = closing_units * (rate_at_booking - h['avg_cost_rate']) * direction
            h['realized_gain_usd'] += trade_realized_gain
            realized_gains_total += trade_realized_gain

            h['balance'] = bal - direction * closing_units
            h['total_cost_basis_usd'] = h['balance'] * h['avg_cost_rate']

            leftover = abs(qty) - closing_units
            if leftover > 1e-12:
                # Position flipped sides: the remainder opens a new position at the booking rate
                h['balance'] = leftover if qty > 0 else -leftover
                h['total_cost_basis_usd'] = h['balance'] * rate_at_booking

        if abs(h['balance']) < 1e-9:
            h['balance'] = 0.0
            h['total_cost_basis_usd'] = 0.0
            h['avg_cost_rate'] = 0.0
        else:
            h['avg_cost_rate'] = h['total_cost_basis_usd'] / h['balance']

    # Calculate Mark-to-Market Unrealized Gains
    fx_summary_list = []
    total_unrealized_gain = 0.0
    total_fx_portfolio_value_usd = 0.0

    for curr, h in holdings.items():
        market_rate = current_market_rates.get(curr, DEFAULT_MARKET_RATES[curr]) / home_market
        current_val_usd = h['balance'] * market_rate
        unrealized_gain_usd = current_val_usd - h['total_cost_basis_usd']

        if h['balance'] != 0 or h['realized_gain_usd'] != 0:
            total_unrealized_gain += unrealized_gain_usd
            total_fx_portfolio_value_usd += current_val_usd

            fx_summary_list.append({
                'currency': curr,
                'balance': h['balance'],
                'market_rate': market_rate,
                'avg_cost_rate': h['avg_cost_rate'],
                'current_val_usd': current_val_usd,
                'total_cost_basis_usd': h['total_cost_basis_usd'],
                'unrealized_gain_usd': unrealized_gain_usd,
                'realized_gain_usd': h['realized_gain_usd']
            })

    return {
        'currencies': fx_summary_list,
        'total_unrealized_gain': total_unrealized_gain,
        'total_realized_gain': realized_gains_total,
        'total_net_fx_pnl': total_unrealized_gain + realized_gains_total,
        'total_fx_portfolio_value_usd': total_fx_portfolio_value_usd
    }


# ============================================================================
# 3. STATISTICAL ANOMALY & FRAUD SENTINEL
# ============================================================================

def detect_anomalies(conn, transactions):
    anomalies = []
    flagged_ids = {}

    if not transactions:
        return anomalies, flagged_ids

    dismissed_rows = conn.execute("SELECT transaction_id FROM dismissed_anomalies").fetchall()
    dismissed_ids = set(r['transaction_id'] for r in dismissed_rows)

    cat_expenses = {}
    for t in transactions:
        rate = t['exchange_rate'] if 'exchange_rate' in t.keys() else 1.0
        normalized_amount = t['amount'] * rate
        if t['type'] == 'expense':
            cat = t['category']
            cat_expenses.setdefault(cat, []).append(normalized_amount)

    cat_stats = {}
    for cat, amounts in cat_expenses.items():
        if len(amounts) >= 3:
            mean = sum(amounts) / len(amounts)
            variance = sum((x - mean) ** 2 for x in amounts) / len(amounts)
            std_dev = math.sqrt(variance)
            cat_stats[cat] = {'mean': mean, 'std_dev': std_dev}

    for t in transactions:
        if t['id'] in dismissed_ids:
            continue

        rate = t['exchange_rate'] if 'exchange_rate' in t.keys() else 1.0
        norm_amt = t['amount'] * rate

        if t['type'] == 'expense' and t['category'] in cat_stats:
            stats = cat_stats[t['category']]
            if stats['std_dev'] > 0:
                z_score = (norm_amt - stats['mean']) / stats['std_dev']
                if z_score >= 2.0:
                    msg = f"Unusual {t['category']} expense of USD {norm_amt:.2f} (Z-Score: +{z_score:.1f}σ vs category avg USD {stats['mean']:.2f})"
                    anomalies.append({
                        'type': 'outlier',
                        'level': 'danger',
                        'title': 'Statistical Outlier',
                        'message': msg,
                        'transaction_id': t['id']
                    })
                    flagged_ids[t['id']] = 'Unusually large'

    def tx_currency(row):
        return row['currency'] if 'currency' in row.keys() and row['currency'] else 'USD'

    def tx_date(row):
        try:
            return datetime.strptime(row['date'], '%Y-%m-%d')
        except (TypeError, ValueError):
            return None

    # How often each (title, amount) pair appears overall: habitual purchases (daily chai, a regular
    # Swiggy order) repeat on nearby days by design and should only be flagged if on the very same day.
    habit_counts = {}
    for t in transactions:
        k = (t['title'].strip().lower(), round(t['amount'], 2), t['type'])
        habit_counts[k] = habit_counts.get(k, 0) + 1

    sorted_by_date = sorted(transactions, key=lambda x: (x['date'], x['id']))
    for i in range(len(sorted_by_date)):
        t1 = sorted_by_date[i]
        d1 = tx_date(t1)
        if d1 is None:
            continue
        for j in range(i + 1, len(sorted_by_date)):
            t2 = sorted_by_date[j]
            d2 = tx_date(t2)
            if d2 is None:
                continue
            # List is date-sorted, so once we are past the 2-day window nothing later can match
            if (d2 - d1).days > 2:
                break

            if t1['id'] in dismissed_ids or t2['id'] in dismissed_ids:
                continue

            # Same title, same amount, same currency and same direction = duplicate candidate
            if (t1['title'].strip().lower() == t2['title'].strip().lower()
                    and t1['type'] == t2['type']
                    and tx_currency(t1) == tx_currency(t2)
                    and abs(t1['amount'] - t2['amount']) < 0.01):
                same_day = (d2 - d1).days == 0
                habitual = habit_counts.get((t1['title'].strip().lower(), round(t1['amount'], 2), t1['type']), 0) > 3
                if not same_day and habitual:
                    continue
                if same_day and habitual and t1['type'] == 'expense' and t1['amount'] * (t1['exchange_rate'] or 1) < 2:
                    # two cups of chai on one day is not a duplicate charge
                    continue
                msg = f'Possible Duplicate: "{t1["title"]}" ({tx_currency(t1)} {t1["amount"]:.2f}) on {t1["date"]} and {t2["date"]}'
                anomalies.append({
                    'type': 'duplicate',
                    'level': 'warning',
                    'title': 'Potential Duplicate Charge',
                    'message': msg,
                    'transaction_id': t2['id']
                })
                flagged_ids[t1['id']] = 'Possible duplicate'
                flagged_ids[t2['id']] = 'Possible duplicate'

    return anomalies, flagged_ids


# ============================================================================
# 4. MONTE CARLO PROBABILISTIC SIMULATION ENGINE
# ============================================================================

def run_monte_carlo_simulation(current_balance, trend_incomes, trend_expenses, num_simulations=1000, months_ahead=12):
    monthly_nets = []
    for inc, exp in zip(trend_incomes, trend_expenses):
        monthly_nets.append(inc - exp)

    if not monthly_nets:
        monthly_nets = [0.0]

    mean_net = sum(monthly_nets) / len(monthly_nets)
    if len(monthly_nets) > 1:
        variance = sum((x - mean_net) ** 2 for x in monthly_nets) / (len(monthly_nets) - 1)
        std_dev_net = math.sqrt(variance)
    else:
        std_dev_net = abs(mean_net * 0.25) or 100.0

    simulation_matrix = [[] for _ in range(months_ahead + 1)]
    for _ in range(num_simulations):
        simulation_matrix[0].append(current_balance)

    ruin_count = 0

    for trial in range(num_simulations):
        bal = current_balance
        hit_ruin = False

        for m in range(1, months_ahead + 1):
            monthly_delta = random.gauss(mean_net, std_dev_net)
            bal += monthly_delta
            simulation_matrix[m].append(bal)

            if bal < 0:
                hit_ruin = True

        if hit_ruin:
            ruin_count += 1

    risk_of_ruin = round((ruin_count / num_simulations) * 100, 1)

    p5_curve = []
    p50_curve = []
    p95_curve = []

    for m in range(months_ahead + 1):
        sorted_balances = sorted(simulation_matrix[m])
        p5_curve.append(round(sorted_balances[int(num_simulations * 0.05)], 2))
        p50_curve.append(round(sorted_balances[int(num_simulations * 0.50)], 2))
        p95_curve.append(round(sorted_balances[int(num_simulations * 0.95)], 2))

    sim_labels = ["Now"] + [f"+{m} Mo" for m in range(1, months_ahead + 1)]

    return {
        'sim_labels': sim_labels,
        'p5_curve': p5_curve,
        'p50_curve': p50_curve,
        'p95_curve': p95_curve,
        'risk_of_ruin': risk_of_ruin,
        'projected_median': p50_curve[-1],
        'projected_optimistic': p95_curve[-1],
        'projected_pessimistic': p5_curve[-1]
    }


# ============================================================================
# 5. FINANCIAL HEALTH & BUDGET HELPERS
# ============================================================================

def calculate_financial_health(total_income, total_expense):
    if total_income <= 0:
        return {'savings_rate': 0, 'score': 0, 'status': 'No Income Recorded', 'color': '#64748b'}

    savings = total_income - total_expense
    savings_rate = round((savings / total_income) * 100, 1)

    if savings_rate >= 30:
        score = min(100, int(85 + (savings_rate - 30) * 0.5))
        status = 'Excellent'
        color = '#16a34a'
    elif savings_rate >= 20:
        score = int(75 + (savings_rate - 20))
        status = 'Good'
        color = '#2563eb'
    elif savings_rate > 0:
        score = int(45 + (savings_rate * 1.5))
        status = 'Fair'
        color = '#f59e0b'
    else:
        score = max(10, int(40 + savings_rate))
        status = 'Needs Attention'
        color = '#dc2626'

    return {'savings_rate': savings_rate, 'score': score, 'status': status, 'color': color}


def current_month_expense_usd(transactions):
    """Sum of this calendar month's expenses, normalized to USD."""
    cur_month = datetime.now().strftime('%Y-%m')
    return sum(
        t['amount'] * (t['exchange_rate'] if 'exchange_rate' in t.keys() else 1.0)
        for t in transactions
        if t['type'] == 'expense' and str(t['date']).startswith(cur_month)
    )


def calculate_burn_rate_and_runway(month_expense, balance):
    """month_expense must be the CURRENT month's spending (not all-time), since the
    daily burn rate is month-to-date spending divided by days elapsed this month."""
    today = datetime.now()
    day_of_month = today.day
    _, total_days_in_month = calendar.monthrange(today.year, today.month)
    days_remaining = max(1, total_days_in_month - day_of_month + 1)

    daily_burn_rate = round(month_expense / max(1, day_of_month), 2)
    safe_daily_spend = round(balance / days_remaining, 2) if balance > 0 else 0.0

    if balance > 0 and daily_burn_rate > 0:
        runway_days = int(balance / daily_burn_rate)
    elif balance <= 0:
        runway_days = 0
    else:
        runway_days = None

    return {
        'daily_burn_rate': daily_burn_rate,
        'safe_daily_spend': safe_daily_spend,
        'days_remaining': days_remaining,
        'runway_days': runway_days
    }


def get_month_comparison(conn):
    today = datetime.now()
    cur_month = today.strftime('%Y-%m')
    first_of_this_month = today.replace(day=1)
    prev_month_date = first_of_this_month - timedelta(days=1)
    prev_month = prev_month_date.strftime('%Y-%m')

    # Fetch normalized to base USD
    rows = conn.execute('''
        SELECT 
            type,
            strftime('%Y-%m', date) as month,
            SUM(amount * exchange_rate) as total
        FROM transactions
        WHERE strftime('%Y-%m', date) IN (?, ?)
        GROUP BY type, month
    ''', (cur_month, prev_month)).fetchall()

    data = {'cur_income': 0.0, 'prev_income': 0.0, 'cur_expense': 0.0, 'prev_expense': 0.0}

    for row in rows:
        if row['month'] == cur_month:
            if row['type'] == 'income':
                data['cur_income'] = row['total']
            else:
                data['cur_expense'] = row['total']
        elif row['month'] == prev_month:
            if row['type'] == 'income':
                data['prev_income'] = row['total']
            else:
                data['prev_expense'] = row['total']

    expense_change = round(((data['cur_expense'] - data['prev_expense']) / data['prev_expense']) * 100, 1) if data['prev_expense'] > 0 else None
    income_change = round(((data['cur_income'] - data['prev_income']) / data['prev_income']) * 100, 1) if data['prev_income'] > 0 else None

    return {
        'expense_change': expense_change,
        'income_change': income_change,
        'prev_month_name': prev_month_date.strftime('%b')
    }


def get_budget_progress(conn):
    today = datetime.now()
    cur_month = today.strftime('%Y-%m')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT UNIQUE NOT NULL,
            monthly_limit REAL NOT NULL CHECK(monthly_limit > 0),
            currency TEXT NOT NULL DEFAULT 'USD'
        )
    ''')

    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(budgets)")
    b_cols = [col[1] for col in cursor.fetchall()]
    if 'currency' not in b_cols:
        conn.execute("ALTER TABLE budgets ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'")

    budgets = conn.execute('SELECT * FROM budgets ORDER BY category ASC').fetchall()
    progress_list = []

    for b in budgets:
        cat = b['category']
        limit = b['monthly_limit']
        b_curr = b['currency'] if 'currency' in b.keys() and b['currency'] else 'USD'
        b_rate = DEFAULT_MARKET_RATES.get(b_curr, 1.0)
        limit_usd = limit * b_rate

        spent_row = conn.execute('''
            SELECT SUM(amount * exchange_rate) as total
            FROM transactions
            WHERE type = 'expense' 
              AND category = ? 
              AND strftime('%Y-%m', date) = ?
        ''', (cat, cur_month)).fetchone()

        spent_usd = spent_row['total'] if spent_row and spent_row['total'] else 0.0
        percent = round((spent_usd / limit_usd) * 100, 1) if limit_usd > 0 else 0.0
        remaining_usd = round(limit_usd - spent_usd, 2)

        if percent >= 100:
            color = '#dc2626'
            status = 'Over Budget'
        elif percent >= 75:
            color = '#f59e0b'
            status = 'Near Limit'
        else:
            color = '#16a34a'
            status = 'On Track'

        progress_list.append({
            'id': b['id'],
            'category': cat,
            'limit': limit_usd,
            'spent': spent_usd,
            'currency': b_curr,
            'original_limit': limit,
            'percent': min(100, percent),
            'real_percent': percent,
            'remaining': remaining_usd,
            'color': color,
            'status': status
        })

    return progress_list


def get_7day_sparkline_data(transactions, to_selected_factor):
    today = datetime.now().date()
    dates = [today - timedelta(days=i) for i in range(6, -1, -1)]
    date_strs = [d.strftime('%Y-%m-%d') for d in dates]

    daily_inc = {d: 0.0 for d in date_strs}
    daily_exp = {d: 0.0 for d in date_strs}

    for t in transactions:
        t_date = t['date']
        if t_date in daily_inc:
            rate = t['exchange_rate'] if 'exchange_rate' in t.keys() else 1.0
            amt = t['amount'] * rate * to_selected_factor
            if t['type'] == 'income':
                daily_inc[t_date] += amt
            else:
                daily_exp[t_date] += amt

    income_points = [round(daily_inc[d], 2) for d in date_strs]
    expense_points = [round(daily_exp[d], 2) for d in date_strs]
    net_points = [round(daily_inc[d] - daily_exp[d], 2) for d in date_strs]

    return {
        'labels': [d.strftime('%b %d') for d in dates],
        'income': income_points,
        'expense': expense_points,
        'net': net_points
    }


def get_account_balances(conn, to_selected_factor):
    accounts = conn.execute("SELECT * FROM accounts ORDER BY id ASC").fetchall()
    result = []

    for acc in accounts:
        acc_name = acc['name']
        curr = acc['currency']
        rate = DEFAULT_MARKET_RATES.get(curr, 1.0)

        tx_rows = conn.execute("SELECT type, amount, exchange_rate FROM transactions WHERE account_name = ?", (acc_name,)).fetchall()
        tx_net_usd = 0.0
        for r in tx_rows:
            r_rate = r['exchange_rate'] if 'exchange_rate' in r.keys() else 1.0
            amt_usd = r['amount'] * r_rate
            if r['type'] == 'income':
                tx_net_usd += amt_usd
            else:
                tx_net_usd -= amt_usd

        initial_usd = acc['initial_balance'] * rate
        total_balance_usd = initial_usd + tx_net_usd
        total_balance_disp = round(total_balance_usd * to_selected_factor, 2)

        result.append({
            'id': acc['id'],
            'name': acc_name,
            'type': acc['account_type'],
            'currency': curr,
            'balance_disp': total_balance_disp,
            'color': acc['color']
        })

    return result


def get_upcoming_subscriptions(conn, to_selected_factor):
    today = datetime.now().date()
    subs = conn.execute("SELECT * FROM subscriptions ORDER BY next_due_date ASC").fetchall()
    result = []

    for s in subs:
        try:
            due_date = datetime.strptime(s['next_due_date'], '%Y-%m-%d').date()
            days_until = (due_date - today).days
        except ValueError:
            days_until = 30

        rate = DEFAULT_MARKET_RATES.get(s['currency'], 1.0)
        amt_disp = round(s['amount'] * rate * to_selected_factor, 2)

        result.append({
            'id': s['id'],
            'name': s['name'],
            'amount_disp': amt_disp,
            'cycle': s['billing_cycle'],
            'next_due_date': s['next_due_date'],
            'days_until': days_until,
            'category': s['category']
        })

    return result


def get_savings_goals(conn, to_selected_factor):
    goals = conn.execute("SELECT * FROM savings_goals ORDER BY id ASC").fetchall()
    result = []

    for g in goals:
        rate = DEFAULT_MARKET_RATES.get(g['currency'], 1.0)
        target_disp = round(g['target_amount'] * rate * to_selected_factor, 2)
        current_disp = round(g['current_amount'] * rate * to_selected_factor, 2)
        percent = round((current_disp / target_disp) * 100, 1) if target_disp > 0 else 0.0

        result.append({
            'id': g['id'],
            'title': g['title'],
            'target_disp': target_disp,
            'current_disp': current_disp,
            'percent': min(100.0, percent),
            'icon': g['icon'],
            'currency': g['currency'] or 'USD'
        })

    return result


def calculate_tax_estimation(total_income, total_expense):
    taxable_net = max(0.0, total_income - total_expense)
    est_tax_amount = round(taxable_net * 0.25, 2)
    est_quarterly_payment = round(est_tax_amount / 4.0, 2)

    return {
        'taxable_net': round(taxable_net, 2),
        'tax_rate_percent': 25,
        'est_tax_amount': est_tax_amount,
        'est_quarterly_payment': est_quarterly_payment
    }


# ============================================================================
# REACT API
# ============================================================================

def row_to_dict(row):
    return {key: row[key] for key in row.keys()}


def get_selected_currency(value):
    currency = (value or 'USD').upper()
    return currency if currency in DEFAULT_MARKET_RATES else 'USD'


def build_dashboard_payload(currency):
    conn = get_db_connection()
    ensure_columns(conn)
    transactions = conn.execute('SELECT * FROM transactions ORDER BY date DESC, id DESC').fetchall()
    target_rate = DEFAULT_MARKET_RATES[currency]
    factor = 1.0 / target_rate if target_rate else 1.0
    total_income_usd = sum(row['amount'] * row['exchange_rate'] for row in transactions if row['type'] == 'income')
    total_expense_usd = sum(row['amount'] * row['exchange_rate'] for row in transactions if row['type'] == 'expense')
    balance_usd = total_income_usd - total_expense_usd
    raw_budgets = get_budget_progress(conn)
    ledger_valid, compromised_id, total_verified = verify_ledger_integrity(conn)
    anomalies, flagged_ids = detect_anomalies(conn, transactions)
    burn_usd = calculate_burn_rate_and_runway(current_month_expense_usd(transactions), balance_usd)
    payload = {
        'currency': currency,
        'symbol': CURRENCY_SYMBOLS[currency],
        'currencies': [{'code': code, 'symbol': symbol} for code, symbol in CURRENCY_SYMBOLS.items()],
        'metrics': {
            'income': round(total_income_usd * factor, 2),
            'expenses': round(total_expense_usd * factor, 2),
            'balance': round(balance_usd * factor, 2),
            'health': calculate_financial_health(total_income_usd, total_expense_usd),
            'burn': {
                **burn_usd,
                'daily_burn_rate': round(burn_usd['daily_burn_rate'] * factor, 2),
                'safe_daily_spend': round(burn_usd['safe_daily_spend'] * factor, 2),
            },
            'comparison': get_month_comparison(conn),
        },
        'budgets': [{
            **budget,
            'limit': round(budget['limit'] * factor, 2),
            'spent': round(budget['spent'] * factor, 2),
            'remaining': round(budget['remaining'] * factor, 2),
        } for budget in raw_budgets],
        'transactions': [{**row_to_dict(row), 'display_amount': round(row['amount'] * row['exchange_rate'] * factor, 2), 'flag': flagged_ids.get(row['id'])} for row in transactions],
        'sparkline': get_7day_sparkline_data(transactions, factor),
        'ledger': {'valid': ledger_valid, 'compromisedId': compromised_id, 'verified': total_verified},
        'anomalies': anomalies,
        'accounts': account_names(conn),
    }
    conn.close()
    return payload


def account_names(conn):
    """Account names a transaction can be booked against (default account first)."""
    names = ['Main Checking']
    for row in conn.execute('SELECT name FROM accounts ORDER BY id ASC').fetchall():
        if row['name'] not in names:
            names.append(row['name'])
    for row in conn.execute('SELECT DISTINCT account_name FROM transactions').fetchall():
        if row['account_name'] and row['account_name'] not in names:
            names.append(row['account_name'])
    return names


def parse_transaction_payload(data):
    """Validate a JSON transaction body. Returns (fields, None) or (None, error message)."""
    required = ('title', 'amount', 'type', 'category', 'date')
    if any(not str(data.get(field, '') if data.get(field) is not None else '').strip() for field in required):
        return None, 'Title, amount, type, category, and date are required.'
    if data['type'] not in ('income', 'expense'):
        return None, 'Type must be income or expense.'
    try:
        amount = parse_positive_float(data['amount'])
    except (TypeError, ValueError):
        return None, 'Enter a valid positive transaction amount.'
    date_str = str(data['date']).strip()
    if not is_valid_date(date_str):
        return None, 'Enter a valid date (YYYY-MM-DD).'
    currency = get_selected_currency(data.get('currency'))
    return {
        'title': str(data['title']).strip(),
        'amount': amount,
        'type': data['type'],
        'category': str(data['category']).strip(),
        'date': date_str,
        'notes': str(data.get('notes') or '').strip(),
        'currency': currency,
        'rate': resolve_exchange_rate(data.get('exchange_rate'), currency),
    }, None


@app.route('/api/dashboard')
def api_dashboard():
    return jsonify(build_dashboard_payload(get_selected_currency(request.args.get('currency'))))


@app.route('/api/transactions', methods=['POST'])
def api_add_transaction():
    data = request.get_json(silent=True) or {}
    fields, error = parse_transaction_payload(data)
    if error:
        return jsonify({'error': error}), 400

    conn = get_db_connection()
    ensure_columns(conn)
    last = conn.execute('SELECT curr_hash FROM transactions ORDER BY id DESC LIMIT 1').fetchone()
    previous_hash = last['curr_hash'] if last and last['curr_hash'] else GENESIS_HASH
    current_hash = compute_row_hash(previous_hash, fields['date'], fields['title'], fields['amount'], fields['type'],
                                    fields['category'], fields['notes'], fields['currency'], fields['rate'])
    account_name = str(data.get('account_name') or 'Main Checking').strip() or 'Main Checking'
    cursor = conn.execute(
        '''INSERT INTO transactions (title, amount, type, category, date, notes, currency, exchange_rate, account_name, prev_hash, curr_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (fields['title'], fields['amount'], fields['type'], fields['category'], fields['date'], fields['notes'],
         fields['currency'], fields['rate'], account_name, previous_hash, current_hash)
    )
    conn.commit()
    transaction = conn.execute('SELECT * FROM transactions WHERE id = ?', (cursor.lastrowid,)).fetchone()
    conn.close()
    return jsonify({'transaction': row_to_dict(transaction)}), 201


@app.route('/api/transactions/<int:transaction_id>', methods=['PUT', 'DELETE'])
def api_transaction(transaction_id):
    conn = get_db_connection()
    ensure_columns(conn)
    existing = conn.execute('SELECT * FROM transactions WHERE id = ?', (transaction_id,)).fetchone()
    if existing is None:
        conn.close()
        return jsonify({'error': 'Transaction not found.'}), 404

    if request.method == 'PUT':
        data = request.get_json(silent=True) or {}
        fields, error = parse_transaction_payload(data)
        if error:
            conn.close()
            return jsonify({'error': error}), 400
        # Keep the existing account when the client does not send one
        account_name = str(data.get('account_name') or existing['account_name'] or 'Main Checking').strip()
        conn.execute('''UPDATE transactions SET title=?, amount=?, type=?, category=?, date=?, notes=?, currency=?, exchange_rate=?, account_name=? WHERE id=?''', (
            fields['title'], fields['amount'], fields['type'], fields['category'], fields['date'],
            fields['notes'], fields['currency'], fields['rate'], account_name, transaction_id
        ))
        conn.commit()
        rebuild_ledger_chain(conn)
        transaction = conn.execute('SELECT * FROM transactions WHERE id = ?', (transaction_id,)).fetchone()
        conn.close()
        return jsonify({'transaction': row_to_dict(transaction)})

    conn.execute('DELETE FROM transactions WHERE id = ?', (transaction_id,))
    conn.execute('DELETE FROM dismissed_anomalies WHERE transaction_id = ?', (transaction_id,))
    conn.commit()
    rebuild_ledger_chain(conn)
    conn.close()
    return ('', 204)


@app.route('/api/transactions/bulk', methods=['POST'])
def api_bulk_transactions():
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    selected_ids = [int(i) for i in data.get('ids', []) if str(i).isdigit()]
    if not selected_ids:
        return jsonify({'error': 'No valid transactions selected.'}), 400

    conn = get_db_connection()
    ensure_columns(conn)

    if action == 'delete':
        for tid in selected_ids:
            conn.execute('DELETE FROM transactions WHERE id = ?', (tid,))
            conn.execute('DELETE FROM dismissed_anomalies WHERE transaction_id = ?', (tid,))
        conn.commit()
        rebuild_ledger_chain(conn)
        conn.close()
        return jsonify({'message': f'Deleted {len(selected_ids)} transactions.'})

    elif action == 'recategorize':
        new_cat = str(data.get('new_category', '')).strip()
        if not new_cat:
            conn.close()
            return jsonify({'error': 'Category name required for recategorization.'}), 400
        for tid in selected_ids:
            conn.execute('UPDATE transactions SET category = ? WHERE id = ?', (new_cat, tid))
        conn.commit()
        rebuild_ledger_chain(conn)
        conn.close()
        return jsonify({'message': f'Recategorized {len(selected_ids)} transactions.'})

    conn.close()
    return jsonify({'error': 'Invalid bulk action.'}), 400


@app.route('/api/budgets', methods=['GET', 'POST'])
def api_budgets():
    conn = get_db_connection()
    ensure_columns(conn)
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        category = str(data.get('category', '')).strip()
        currency_code = get_selected_currency(data.get('currency'))
        try:
            limit = parse_positive_float(data.get('monthly_limit', 0))
            if not category:
                raise ValueError
        except (TypeError, ValueError):
            conn.close()
            return jsonify({'error': 'Provide a category and a positive monthly limit.'}), 400
        conn.execute('''INSERT INTO budgets (category, monthly_limit, currency) VALUES (?, ?, ?)
                        ON CONFLICT(category) DO UPDATE SET monthly_limit = excluded.monthly_limit, currency = excluded.currency''', (category, limit, currency_code))
        conn.commit()
    currency = get_selected_currency(request.args.get('currency'))
    factor = 1.0 / DEFAULT_MARKET_RATES[currency]
    budgets = [{
        **budget,
        'limit': round(budget['limit'] * factor, 2),
        'spent': round(budget['spent'] * factor, 2),
        'remaining': round(budget['remaining'] * factor, 2)
    } for budget in get_budget_progress(conn)]
    conn.close()
    return jsonify({
        'currency': currency,
        'symbol': CURRENCY_SYMBOLS[currency],
        'currencies': [{'code': code, 'symbol': symbol} for code, symbol in CURRENCY_SYMBOLS.items()],
        'budgets': budgets
    })


@app.route('/api/budgets/<int:budget_id>', methods=['DELETE'])
def api_delete_budget(budget_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM budgets WHERE id = ?', (budget_id,))
    conn.commit()
    conn.close()
    return ('', 204)


@app.route('/api/analytics')
def api_analytics():
    currency = get_selected_currency(request.args.get('currency'))
    factor = 1.0 / DEFAULT_MARKET_RATES[currency]
    conn = get_db_connection()
    rows = conn.execute('''SELECT strftime('%Y-%m', date) AS month, type, SUM(amount * exchange_rate) AS total
                           FROM transactions GROUP BY month, type ORDER BY month''').fetchall()
    category_rows = conn.execute('''SELECT category, SUM(amount * exchange_rate) AS total FROM transactions
                                    WHERE type = 'expense' GROUP BY category ORDER BY total DESC''').fetchall()
    monthly = {}
    for row in rows:
        monthly.setdefault(row['month'], {'income': 0.0, 'expense': 0.0})[row['type']] = round(row['total'] * factor, 2)
    months = sorted(monthly)
    incomes = [monthly[month]['income'] for month in months]
    expenses = [monthly[month]['expense'] for month in months]
    conn.close()

    has_data = len(months) > 0 and (sum(incomes) > 0 or sum(expenses) > 0)

    if not has_data:
        projection = {
            'sim_labels': [],
            'p5_curve': [],
            'p50_curve': [],
            'p95_curve': [],
            'risk_of_ruin': 0.0,
            'projected_median': 0.0,
            'projected_optimistic': 0.0,
            'projected_pessimistic': 0.0
        }
    else:
        projection = run_monte_carlo_simulation(sum(incomes) - sum(expenses), incomes, expenses)

    return jsonify({
        'currency': currency,
        'symbol': CURRENCY_SYMBOLS[currency],
        'currencies': [{'code': code, 'symbol': symbol} for code, symbol in CURRENCY_SYMBOLS.items()],
        'months': months,
        'income': incomes,
        'expenses': expenses,
        'categories': [{'category': r['category'], 'total': round(r['total'] * factor, 2)} for r in category_rows],
        'projection': projection,
    })


@app.route('/api/hub')
def api_hub():
    currency = get_selected_currency(request.args.get('currency'))
    factor = 1.0 / DEFAULT_MARKET_RATES[currency]
    conn = get_db_connection()
    ensure_columns(conn)
    rows = conn.execute('SELECT type, amount, exchange_rate FROM transactions').fetchall()
    income = sum(row['amount'] * row['exchange_rate'] for row in rows if row['type'] == 'income')
    expenses = sum(row['amount'] * row['exchange_rate'] for row in rows if row['type'] == 'expense')
    payload = {
        'currency': currency,
        'symbol': CURRENCY_SYMBOLS[currency],
        'accounts': get_account_balances(conn, factor),
        'subscriptions': get_upcoming_subscriptions(conn, factor),
        'goals': get_savings_goals(conn, factor),
        'tax': calculate_tax_estimation(income * factor, expenses * factor),
    }
    conn.close()
    return jsonify(payload)


@app.route('/api/accounts', methods=['POST'])
def api_add_account():
    data = request.get_json(silent=True) or {}
    name = str(data.get('name', '')).strip()
    try:
        balance = float(data.get('initial_balance') or 0)
        if math.isnan(balance) or math.isinf(balance):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'error': 'Enter a valid starting balance.'}), 400
    if not name:
        return jsonify({'error': 'Account name is required.'}), 400
    conn = get_db_connection()
    ensure_columns(conn)
    conn.execute('''INSERT INTO accounts (name, account_type, initial_balance, currency, color)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET account_type=excluded.account_type, initial_balance=excluded.initial_balance, currency=excluded.currency, color=excluded.color''', (
        name, str(data.get('account_type') or 'checking'), balance, get_selected_currency(data.get('currency')), str(data.get('color') or '#4b5fc0')
    ))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Account saved.'}), 201


@app.route('/api/subscriptions', methods=['POST'])
def api_add_subscription():
    data = request.get_json(silent=True) or {}
    name = str(data.get('name', '')).strip()
    due_date = str(data.get('next_due_date', '')).strip()
    try:
        amount = parse_positive_float(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Enter a positive subscription amount.'}), 400
    if not name or not due_date:
        return jsonify({'error': 'Name and next due date are required.'}), 400
    if not is_valid_date(due_date):
        return jsonify({'error': 'Enter a valid next due date (YYYY-MM-DD).'}), 400
    conn = get_db_connection()
    ensure_columns(conn)
    conn.execute('''INSERT INTO subscriptions (name, amount, currency, billing_cycle, next_due_date, category)
                    VALUES (?, ?, ?, ?, ?, ?)''', (
        name, amount, get_selected_currency(data.get('currency')), str(data.get('billing_cycle') or 'monthly'), due_date,
        str(data.get('category') or 'Software & Subscriptions').strip()
    ))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Subscription added.'}), 201


@app.route('/api/goals', methods=['POST'])
def api_add_goal():
    data = request.get_json(silent=True) or {}
    title = str(data.get('title', '')).strip()
    try:
        target = parse_positive_float(data.get('target_amount', 0))
        current = float(data.get('current_amount') or 0)
        if current < 0 or math.isnan(current) or math.isinf(current):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'error': 'Enter a positive target and a valid starting amount.'}), 400
    if not title:
        return jsonify({'error': 'Goal title is required.'}), 400
    target_date = str(data.get('target_date') or '').strip() or None
    if target_date and not is_valid_date(target_date):
        return jsonify({'error': 'Enter a valid target date (YYYY-MM-DD).'}), 400
    conn = get_db_connection()
    ensure_columns(conn)
    conn.execute('''INSERT INTO savings_goals (title, target_amount, current_amount, target_date, currency, icon)
                    VALUES (?, ?, ?, ?, ?, ?)''', (
        title, target, current, target_date, get_selected_currency(data.get('currency')), str(data.get('icon') or '🎯')
    ))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Savings goal added.'}), 201


@app.route('/api/goals/<int:goal_id>/deposit', methods=['POST'])
def api_deposit_goal(goal_id):
    data = request.get_json(silent=True) or {}
    try:
        amount = parse_positive_float(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Enter a positive deposit amount.'}), 400
    conn = get_db_connection()
    cursor = conn.execute('UPDATE savings_goals SET current_amount = current_amount + ? WHERE id = ?', (amount, goal_id))
    conn.commit()
    conn.close()
    if cursor.rowcount == 0:
        return jsonify({'error': 'Savings goal not found.'}), 404
    return jsonify({'message': 'Deposit recorded.'})


@app.route('/api/anomalies/<int:transaction_id>/dismiss', methods=['POST'])
def api_dismiss_anomaly(transaction_id):
    conn = get_db_connection()
    ensure_columns(conn)
    conn.execute('INSERT OR IGNORE INTO dismissed_anomalies (transaction_id) VALUES (?)', (transaction_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Alert dismissed.'})


@app.route('/api/audit/verify', methods=['POST'])
def api_verify_audit():
    conn = get_db_connection()
    ensure_columns(conn)
    is_valid, bad_id, total_checked = verify_ledger_integrity(conn)
    conn.close()
    return jsonify({'valid': is_valid, 'compromisedId': bad_id, 'verified': total_checked})


@app.route('/api/fx', methods=['GET', 'POST'])
def api_fx_portfolio():
    """FX positions relative to a home currency (the display currency).

    Rates in and out of this endpoint are "1 unit of X = N home units"; values are in home units.
    """
    home = get_selected_currency(request.args.get('currency') or 'INR')
    data = request.get_json(silent=True) or {}
    requested = data.get('rates') if isinstance(data, dict) else None
    usd_rates = DEFAULT_MARKET_RATES.copy()
    for code, value in (requested if isinstance(requested, dict) else {}).items():
        if code in usd_rates and code != home:
            try:
                usd_rates[code] = parse_positive_float(value) * DEFAULT_MARKET_RATES[home]
            except (TypeError, ValueError):
                pass
    conn = get_db_connection()
    ensure_columns(conn)
    transactions = conn.execute('SELECT * FROM transactions ORDER BY id ASC').fetchall()
    conn.close()

    analysis = calculate_fx_holdings_and_gains(transactions, usd_rates, home=home)
    r2 = lambda v: round(v, 2)
    home_rate = DEFAULT_MARKET_RATES[home]
    return jsonify({
        'currency': home,
        'symbol': CURRENCY_SYMBOLS[home],
        'rates': {c: round(v / home_rate, 6) for c, v in usd_rates.items() if c != home},
        'default_rates': {c: round(v / home_rate, 6) for c, v in DEFAULT_MARKET_RATES.items() if c != home},
        'analysis': {
            'currencies': [{
                'currency': h['currency'], 'balance': r2(h['balance']), 'market_rate': h['market_rate'],
                'avg_cost_rate': h['avg_cost_rate'], 'cost': r2(h['total_cost_basis_usd']),
                'value': r2(h['current_val_usd']), 'unrealized': r2(h['unrealized_gain_usd']),
                'realized': r2(h['realized_gain_usd']),
            } for h in analysis['currencies']],
            'total_unrealized_gain': r2(analysis['total_unrealized_gain']),
            'total_realized_gain': r2(analysis['total_realized_gain']),
            'total_net_fx_pnl': r2(analysis['total_net_fx_pnl']),
            'total_value': r2(analysis['total_fx_portfolio_value_usd']),
        },
    })


# ============================================================================
# 5b. SMART FEATURES API (see intelligence.py)
# ============================================================================

def format_money_text(usd, currency):
    """Human formatting for insight sentences: Indian digit grouping for INR, whole units above 100."""
    value = usd / DEFAULT_MARKET_RATES[currency]
    symbol = CURRENCY_SYMBOLS[currency]
    decimals = 0 if (currency == 'JPY' or abs(value) >= 100) else 2
    text = f"{abs(value):,.{decimals}f}"
    if currency == 'INR':
        whole, _, frac = f"{abs(value):.{decimals}f}".partition('.')
        if len(whole) > 3:
            head, tail = whole[:-3], whole[-3:]
            groups = []
            while len(head) > 2:
                groups.insert(0, head[-2:])
                head = head[:-2]
            if head:
                groups.insert(0, head)
            whole = ','.join(groups + [tail])
        text = whole + ('.' + frac if frac else '')
    return ('-' if value < 0 else '') + symbol + text


def load_smart_context(conn):
    ensure_columns(conn)
    transactions = conn.execute('SELECT * FROM transactions ORDER BY date ASC, id ASC').fetchall()
    rules = conn.execute('SELECT * FROM automation_rules ORDER BY id ASC').fetchall()
    subscriptions = conn.execute('SELECT * FROM subscriptions ORDER BY next_due_date ASC').fetchall()
    budgets = conn.execute('SELECT * FROM budgets ORDER BY category ASC').fetchall()
    return transactions, rules, subscriptions, budgets


def today_local():
    return datetime.now().date()


@app.route('/api/overview')
def api_overview():
    currency = get_selected_currency(request.args.get('currency') or 'INR')
    factor = 1.0 / DEFAULT_MARKET_RATES[currency]
    conn = get_db_connection()
    transactions, rules, subscriptions, budgets = load_smart_context(conn)
    today = today_local()
    recurring = smart.detect_recurring(transactions, today, [s['name'] for s in subscriptions])
    forecast = smart.build_forecast(transactions, budgets, recurring, subscriptions, today, DEFAULT_MARKET_RATES)
    anomalies, flagged = detect_anomalies(conn, transactions)
    due_soon = smart.due_soon(recurring, subscriptions, today, DEFAULT_MARKET_RATES, days=10)
    insights = smart.build_insights(transactions, forecast, recurring, anomalies, today,
                                    lambda usd: format_money_text(usd, currency), due_soon)
    ledger_valid, compromised_id, verified = verify_ledger_integrity(conn)
    accounts = account_names(conn)
    conn.close()

    conv = lambda v: round(v * factor, 2)
    recent = sorted(transactions, key=lambda t: (t['date'], t['id']), reverse=True)[:8]
    all_time_net = sum(smart.base_amount(t) if t['type'] == 'income' else -smart.base_amount(t) for t in transactions)
    return jsonify({
        'currency': currency,
        'today': today.isoformat(),
        'month_label': today.strftime('%B %Y'),
        'prev_month_label': (today.replace(day=1) - timedelta(days=1)).strftime('%B'),
        'day': forecast['day'], 'days_in_month': forecast['days_in_month'], 'days_left': forecast['days_left'],
        'totals': {
            'spent': conv(forecast['spent_usd']),
            'income': conv(forecast['income_month_usd']),
            'prev_same_day': conv(forecast['prev_same_day_usd']),
            'prev_total': conv(forecast['prev_total_usd']),
            'projected': conv(forecast['projected_total_usd']),
            'committed': conv(forecast['committed_usd']),
            'balance': conv(all_time_net),
        },
        'safe': {
            'per_day': conv(forecast['safe_per_day_usd']),
            'today_left': conv(forecast['safe_today_left_usd']),
            'basis': forecast['safe_basis'],
            'income_basis': conv(forecast['income_basis_usd']),
            'income_is_typical': forecast['income_is_typical'],
        },
        'curves': {
            'this': [conv(v) for v in forecast['this_cum_usd']],
            'prev': [conv(v) for v in forecast['prev_cum_usd']],
            'projection': [conv(v) for v in forecast['projection_usd']],
        },
        'budgets': [{
            'id': b['id'], 'category': b['category'], 'currency': b['currency'], 'status': b['status'],
            'limit': conv(b['limit_usd']), 'spent': conv(b['spent_usd']), 'projected': conv(b['projected_usd']),
            'left': conv(b['left_usd']), 'per_day_left': conv(b['per_day_left_usd']), 'overshoot': conv(b['overshoot_usd']),
        } for b in forecast['budgets']],
        'upcoming': [{**{k: v for k, v in u.items() if k != 'amount_usd'}, 'amount': conv(u['amount_usd'])} for u in due_soon],
        'insights': insights,
        'anomalies': anomalies,
        'recent': [{**row_to_dict(t), 'display_amount': conv(smart.base_amount(t)), 'flag': flagged.get(t['id'])} for t in recent],
        'ledger': {'valid': ledger_valid, 'compromisedId': compromised_id, 'verified': verified},
        'accounts': accounts,
        'count': len(transactions),
    })


@app.route('/api/ledger')
def api_ledger():
    """Every entry with display amount and running balance (chronological, in display currency)."""
    currency = get_selected_currency(request.args.get('currency') or 'INR')
    factor = 1.0 / DEFAULT_MARKET_RATES[currency]
    conn = get_db_connection()
    ensure_columns(conn)
    transactions = conn.execute('SELECT * FROM transactions ORDER BY date ASC, id ASC').fetchall()
    anomalies, flagged = detect_anomalies(conn, transactions)
    accounts = account_names(conn)
    categories = [r['category'] for r in conn.execute(
        'SELECT category, COUNT(*) AS n FROM transactions GROUP BY category ORDER BY n DESC').fetchall()]
    conn.close()
    running = 0.0
    rows = []
    for t in transactions:
        amount = smart.base_amount(t) * factor
        running += amount if t['type'] == 'income' else -amount
        rows.append({**row_to_dict(t), 'display_amount': round(amount, 2), 'running_balance': round(running, 2),
                     'flag': flagged.get(t['id'])})
    rows.reverse()
    return jsonify({'currency': currency, 'transactions': rows, 'accounts': accounts, 'categories': categories,
                    'anomalies': anomalies})


@app.route('/api/parse', methods=['POST'])
def api_parse_entry():
    data = request.get_json(silent=True) or {}
    text = str(data.get('text') or '')[:300]
    currency = get_selected_currency(data.get('currency') or 'INR')
    conn = get_db_connection()
    transactions, rules, _, _ = load_smart_context(conn)
    accounts = [a for a in account_names(conn) if a != 'Main Checking']
    conn.close()
    return jsonify(smart.parse_entry(text, today_local(), transactions, rules, currency, accounts))


@app.route('/api/suggest')
def api_suggest_category():
    conn = get_db_connection()
    transactions, rules, _, _ = load_smart_context(conn)
    conn.close()
    return jsonify(smart.suggest_category(request.args.get('title', '')[:200], transactions, rules))


@app.route('/api/categories')
def api_categories():
    conn = get_db_connection()
    ensure_columns(conn)
    used = [r['category'] for r in conn.execute(
        'SELECT category, COUNT(*) AS n FROM transactions GROUP BY category ORDER BY n DESC').fetchall()]
    accounts = account_names(conn)
    conn.close()
    seeds = [c for c in smart.SEED_CATEGORIES if c not in used]
    return jsonify({'categories': used + seeds, 'accounts': accounts})


@app.route('/api/rules', methods=['GET', 'POST'])
def api_rules():
    conn = get_db_connection()
    ensure_columns(conn)
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        keyword = str(data.get('keyword') or '').strip().lower()
        category = str(data.get('category') or '').strip()
        if not keyword or not category:
            conn.close()
            return jsonify({'error': 'Enter a word to match and the category to use.'}), 400
        existing = conn.execute('SELECT id FROM automation_rules WHERE match_keyword = ?', (keyword,)).fetchone()
        if existing:
            conn.execute('UPDATE automation_rules SET action_category = ?, rule_name = ? WHERE id = ?',
                         (category, f'{keyword} → {category}', existing['id']))
        else:
            conn.execute('INSERT INTO automation_rules (rule_name, match_field, match_keyword, action_category) VALUES (?, ?, ?, ?)',
                         (f'{keyword} → {category}', 'title', keyword, category))
        if data.get('apply_existing'):
            conn.execute("UPDATE transactions SET category = ? WHERE LOWER(title) LIKE ?", (category, f'%{keyword}%'))
            conn.commit()
            rebuild_ledger_chain(conn)
        conn.commit()
    rules = [{'id': r['id'], 'keyword': r['match_keyword'], 'category': r['action_category']}
             for r in conn.execute('SELECT * FROM automation_rules ORDER BY match_keyword ASC').fetchall()]
    counts = {}
    for r in rules:
        counts[r['id']] = conn.execute('SELECT COUNT(*) AS n FROM transactions WHERE LOWER(title) LIKE ?',
                                       (f"%{r['keyword']}%",)).fetchone()['n']
    conn.close()
    return jsonify({'rules': [{**r, 'matches': counts[r['id']]} for r in rules]})


@app.route('/api/rules/<int:rule_id>', methods=['DELETE'])
def api_delete_rule(rule_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM automation_rules WHERE id = ?', (rule_id,))
    conn.commit()
    conn.close()
    return ('', 204)


@app.route('/api/recurring')
def api_recurring():
    currency = get_selected_currency(request.args.get('currency') or 'INR')
    factor = 1.0 / DEFAULT_MARKET_RATES[currency]
    conn = get_db_connection()
    transactions, _, subscriptions, _ = load_smart_context(conn)
    conn.close()
    today = today_local()
    detected = smart.detect_recurring(transactions, today, [s['name'] for s in subscriptions])
    tracked = []
    for s in subscriptions:
        due = smart.to_date(s['next_due_date'])
        usd = s['amount'] * DEFAULT_MARKET_RATES.get(s['currency'], 1.0)
        per_month = {'weekly': 52 / 12, 'monthly': 1, 'quarterly': 1 / 3, 'yearly': 1 / 12}.get(s['billing_cycle'], 1)
        tracked.append({'id': s['id'], 'name': s['name'], 'amount': s['amount'], 'currency': s['currency'],
                        'display_amount': round(usd * factor, 2), 'cycle': s['billing_cycle'],
                        'next_date': s['next_due_date'], 'days_until': (due - today).days if due else None,
                        'category': s['category'], 'monthly': round(usd * per_month * factor, 2)})
    tracked_keys = {smart.normalize_title(s['name']) for s in subscriptions}
    monthly_out = sum(t['monthly'] for t in tracked) + sum(
        r['monthly_usd'] * factor for r in detected if r['type'] == 'expense' and r['key'] not in tracked_keys)
    return jsonify({
        'currency': currency,
        'tracked': tracked,
        'detected': [{**r, 'display_amount': round(r['amount_usd'] * factor, 2), 'monthly': round(r['monthly_usd'] * factor, 2)}
                     for r in detected],
        'monthly_out': round(monthly_out, 2),
    })


@app.route('/api/subscriptions/<int:sub_id>', methods=['DELETE'])
def api_delete_subscription(sub_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM subscriptions WHERE id = ?', (sub_id,))
    conn.commit()
    conn.close()
    return ('', 204)


@app.route('/api/goals/<int:goal_id>', methods=['DELETE'])
def api_delete_goal(goal_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM savings_goals WHERE id = ?', (goal_id,))
    conn.commit()
    conn.close()
    return ('', 204)


@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
def api_delete_account(account_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM accounts WHERE id = ?', (account_id,))
    conn.commit()
    conn.close()
    return ('', 204)


@app.route('/api/reports')
def api_reports():
    """Monthly totals, savings rate, top categories by month and the Monte Carlo outlook."""
    currency = get_selected_currency(request.args.get('currency') or 'INR')
    factor = 1.0 / DEFAULT_MARKET_RATES[currency]
    conn = get_db_connection()
    ensure_columns(conn)
    transactions = conn.execute('SELECT * FROM transactions ORDER BY date ASC').fetchall()
    conn.close()
    months = sorted({str(t['date'])[:7] for t in transactions})[-12:]
    income = {m: 0.0 for m in months}
    expense = {m: 0.0 for m in months}
    by_cat = {}
    for t in transactions:
        m = str(t['date'])[:7]
        if m not in income:
            continue
        v = smart.base_amount(t) * factor
        if t['type'] == 'income':
            income[m] += v
        else:
            expense[m] += v
            by_cat.setdefault(t['category'], {mm: 0.0 for mm in months})[m] += v
    top = sorted(by_cat.items(), key=lambda kv: sum(kv[1].values()), reverse=True)
    categories = [{'category': c, 'total': round(sum(v.values()), 2), 'by_month': [round(v[m], 2) for m in months]}
                  for c, v in top]
    incomes = [round(income[m], 2) for m in months]
    expenses = [round(expense[m], 2) for m in months]
    has_data = any(incomes) or any(expenses)
    balance = sum(smart.base_amount(t) * factor * (1 if t['type'] == 'income' else -1) for t in transactions)
    projection = run_monte_carlo_simulation(balance, incomes, expenses) if has_data else None
    return jsonify({
        'currency': currency,
        'months': months,
        'labels': [datetime.strptime(m, '%Y-%m').strftime('%b %y') for m in months],
        'income': incomes, 'expenses': expenses,
        'savings_rate': [round((i - e) / i * 100, 1) if i > 0 else None for i, e in zip(incomes, expenses)],
        'categories': categories,
        'balance': round(balance, 2),
        'projection': projection,
    })


# ============================================================================
# 6. APPLICATION ROUTES
# ============================================================================

@app.route('/legacy')
def index():
    conn = get_db_connection()
    ensure_columns(conn)

    transactions = conn.execute(
        'SELECT * FROM transactions ORDER BY date DESC, id DESC'
    ).fetchall()

    # Determine display currency: via query param ?currency=... or auto-detect from latest transaction
    selected_currency = request.args.get('currency')
    if not selected_currency or selected_currency not in DEFAULT_MARKET_RATES:
        if transactions and 'currency' in transactions[0].keys() and transactions[0]['currency']:
            selected_currency = transactions[0]['currency']
        else:
            selected_currency = 'USD'

    # Conversion factor from Base USD to selected currency
    target_rate = DEFAULT_MARKET_RATES.get(selected_currency, 1.0)
    to_selected_factor = (1.0 / target_rate) if target_rate > 0 else 1.0
    curr_symbol = CURRENCY_SYMBOLS.get(selected_currency, '$')

    # Base USD normalized totals
    total_income_usd = sum(row['amount'] * (row['exchange_rate'] if 'exchange_rate' in row.keys() else 1.0) for row in transactions if row['type'] == 'income')
    total_expense_usd = sum(row['amount'] * (row['exchange_rate'] if 'exchange_rate' in row.keys() else 1.0) for row in transactions if row['type'] == 'expense')
    balance_usd = total_income_usd - total_expense_usd

    # Convert totals for Dashboard display
    total_income = total_income_usd * to_selected_factor
    total_expense = total_expense_usd * to_selected_factor
    balance = balance_usd * to_selected_factor

    health_stats = calculate_financial_health(total_income_usd, total_expense_usd)

    burn_stats_usd = calculate_burn_rate_and_runway(current_month_expense_usd(transactions), balance_usd)
    burn_stats = {
        'daily_burn_rate': burn_stats_usd['daily_burn_rate'] * to_selected_factor,
        'safe_daily_spend': burn_stats_usd['safe_daily_spend'] * to_selected_factor,
        'days_remaining': burn_stats_usd['days_remaining'],
        'runway_days': burn_stats_usd['runway_days']
    }

    comparison = get_month_comparison(conn)
    sparkline_data = get_7day_sparkline_data(transactions, to_selected_factor)

    account_balances = get_account_balances(conn, to_selected_factor)
    upcoming_subscriptions = get_upcoming_subscriptions(conn, to_selected_factor)
    savings_goals = get_savings_goals(conn, to_selected_factor)
    tax_stats = calculate_tax_estimation(total_income, total_expense)
    
    # Convert category budgets to selected display currency
    raw_budget_progress = get_budget_progress(conn)
    budget_progress = []
    for b in raw_budget_progress:
        budget_progress.append({
            'id': b['id'],
            'category': b['category'],
            'limit': b['limit'] * to_selected_factor,
            'spent': b['spent'] * to_selected_factor,
            'percent': b['percent'],
            'real_percent': b['real_percent'],
            'remaining': b['remaining'] * to_selected_factor,
            'color': b['color'],
            'status': b['status']
        })

    is_valid, bad_id, total_checked = verify_ledger_integrity(conn)
    anomalies, flagged_ids = detect_anomalies(conn, transactions)

    conn.close()

    return render_template(
        'index.html',
        transactions=transactions,
        total_income=total_income,
        total_expense=total_expense,
        balance=balance,
        selected_currency=selected_currency,
        curr_symbol=curr_symbol,
        currency_symbols=CURRENCY_SYMBOLS,
        health_stats=health_stats,
        burn_stats=burn_stats,
        comparison=comparison,
        sparkline_data=sparkline_data,
        account_balances=account_balances,
        upcoming_subscriptions=upcoming_subscriptions,
        savings_goals=savings_goals,
        tax_stats=tax_stats,
        budget_progress=budget_progress,
        ledger_valid=is_valid,
        compromised_id=bad_id,
        total_verified=total_checked,
        anomalies=anomalies,
        flagged_ids=flagged_ids
    )


# NEW: DEDICATED FX GAIN/LOSS PORTFOLIO VIEW
@app.route('/fx', methods=['GET', 'POST'])
def fx_portfolio():
    conn = get_db_connection()
    ensure_columns(conn)

    transactions = conn.execute('SELECT * FROM transactions ORDER BY id ASC').fetchall()
    conn.close()

    # User can optionally simulate custom exchange rates via form
    active_rates = DEFAULT_MARKET_RATES.copy()
    if request.method == 'POST':
        for curr in active_rates.keys():
            if curr != 'USD':
                val = request.form.get(f'rate_{curr}')
                if val:
                    try:
                        active_rates[curr] = parse_positive_float(val)
                    except ValueError:
                        flash(f'Ignored invalid {curr} rate (must be a positive number).', 'warning')

    fx_analysis = calculate_fx_holdings_and_gains(transactions, active_rates)

    return render_template(
        'fx_portfolio.html',
        fx=fx_analysis,
        rates=active_rates,
        default_rates=DEFAULT_MARKET_RATES
    )


@app.route('/financial-hub')
def financial_hub():
    conn = get_db_connection()
    ensure_columns(conn)

    selected_currency = request.args.get('currency', 'USD').upper()
    if selected_currency not in DEFAULT_MARKET_RATES:
        selected_currency = 'USD'

    to_selected_factor = 1.0 / DEFAULT_MARKET_RATES[selected_currency]
    curr_symbol = CURRENCY_SYMBOLS.get(selected_currency, '$')

    account_balances = get_account_balances(conn, to_selected_factor)
    upcoming_subscriptions = get_upcoming_subscriptions(conn, to_selected_factor)
    savings_goals = get_savings_goals(conn, to_selected_factor)

    tx_rows = conn.execute("SELECT type, amount, exchange_rate FROM transactions").fetchall()
    tot_inc_usd = sum(r['amount'] * (r['exchange_rate'] if 'exchange_rate' in r.keys() else 1.0) for r in tx_rows if r['type'] == 'income')
    tot_exp_usd = sum(r['amount'] * (r['exchange_rate'] if 'exchange_rate' in r.keys() else 1.0) for r in tx_rows if r['type'] == 'expense')
    
    taxable_net_usd = max(0.0, tot_inc_usd - tot_exp_usd)
    tax_rate = 0.25
    est_tax_usd = taxable_net_usd * tax_rate
    est_qtr_usd = est_tax_usd / 4.0

    tax_stats = {
        'taxable_net': round(taxable_net_usd * to_selected_factor, 2),
        'est_tax_amount': round(est_tax_usd * to_selected_factor, 2),
        'est_quarterly_payment': round(est_qtr_usd * to_selected_factor, 2)
    }

    conn.close()

    return render_template(
        'financial_hub.html',
        selected_currency=selected_currency,
        curr_symbol=curr_symbol,
        currency_symbols=CURRENCY_SYMBOLS,
        account_balances=account_balances,
        upcoming_subscriptions=upcoming_subscriptions,
        savings_goals=savings_goals,
        tax_stats=tax_stats
    )


@app.route('/accounts/add', methods=['POST'])
def add_account():
    name = request.form.get('name', '').strip()
    account_type = request.form.get('account_type', 'checking').strip() or 'checking'
    init_bal = request.form.get('initial_balance', '0').strip() or '0'
    currency = get_selected_currency(request.form.get('currency'))
    color = request.form.get('color', '#2563eb').strip() or '#2563eb'

    if not name:
        flash('Account name is required.', 'error')
        return redirect(url_for('financial_hub'))

    try:
        bal = float(init_bal)
        if math.isnan(bal) or math.isinf(bal):
            raise ValueError
    except ValueError:
        flash('Invalid balance format.', 'error')
        return redirect(url_for('financial_hub'))

    conn = get_db_connection()
    ensure_columns(conn)
    # Upsert keeps the row id stable (INSERT OR REPLACE would delete and re-create it)
    conn.execute(
        """INSERT INTO accounts (name, account_type, initial_balance, currency, color) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET account_type=excluded.account_type, initial_balance=excluded.initial_balance,
           currency=excluded.currency, color=excluded.color""",
        (name, account_type, bal, currency, color)
    )
    conn.commit()
    conn.close()
    flash(f'Account "{name}" saved successfully.', 'success')
    return redirect(url_for('financial_hub'))


@app.route('/subscriptions/add', methods=['POST'])
def add_subscription():
    name = request.form.get('name', '').strip()
    amount_raw = request.form.get('amount', '0').strip()
    currency = get_selected_currency(request.form.get('currency'))
    billing_cycle = request.form.get('billing_cycle', 'monthly').strip() or 'monthly'
    next_due_date = request.form.get('next_due_date', '').strip()
    category = request.form.get('category', 'Software & Subscriptions').strip() or 'Software & Subscriptions'

    if not name or not next_due_date:
        flash('Subscription name and next due date are required.', 'error')
        return redirect(url_for('financial_hub'))
    if not is_valid_date(next_due_date):
        flash('Enter a valid next due date.', 'error')
        return redirect(url_for('financial_hub'))
    try:
        amt = parse_positive_float(amount_raw)
    except ValueError:
        flash('Subscription amount must be a positive number.', 'error')
        return redirect(url_for('financial_hub'))

    conn = get_db_connection()
    ensure_columns(conn)
    conn.execute(
        "INSERT INTO subscriptions (name, amount, currency, billing_cycle, next_due_date, category) VALUES (?, ?, ?, ?, ?, ?)",
        (name, amt, currency, billing_cycle, next_due_date, category)
    )
    conn.commit()
    conn.close()
    flash(f'Subscription "{name}" created successfully.', 'success')
    return redirect(url_for('financial_hub'))


@app.route('/savings/add', methods=['POST'])
def add_savings_goal():
    title = request.form.get('title', '').strip()
    target_raw = request.form.get('target_amount', '0').strip()
    current_raw = request.form.get('current_amount', '0').strip() or '0'
    icon = request.form.get('icon', '🎯').strip() or '🎯'
    currency = get_selected_currency(request.form.get('currency'))

    if not title:
        flash('Goal title is required.', 'error')
        return redirect(url_for('financial_hub'))
    try:
        target = parse_positive_float(target_raw)
        current = float(current_raw)
        if current < 0 or math.isnan(current) or math.isinf(current):
            raise ValueError
    except ValueError:
        flash('Target must be positive and the starting amount cannot be negative.', 'error')
        return redirect(url_for('financial_hub'))

    conn = get_db_connection()
    ensure_columns(conn)
    conn.execute(
        "INSERT INTO savings_goals (title, target_amount, current_amount, currency, icon) VALUES (?, ?, ?, ?, ?)",
        (title, target, current, currency, icon)
    )
    conn.commit()
    conn.close()
    flash(f'Savings Goal "{title}" created successfully.', 'success')
    return redirect(url_for('financial_hub'))


@app.route('/anomalies/dismiss/<int:id>', methods=['POST'])
def dismiss_anomaly(id):
    conn = get_db_connection()
    conn.execute('INSERT OR IGNORE INTO dismissed_anomalies (transaction_id) VALUES (?)', (id,))
    conn.commit()
    conn.close()

    flash('✅ Duplicate marked as authorized and dismissed from alert sentinel.', 'success')
    return redirect(url_for('index'))


@app.route('/anomalies/recheck', methods=['POST'])
def recheck_anomalies():
    conn = get_db_connection()
    transactions = conn.execute('SELECT * FROM transactions').fetchall()
    anomalies, _ = detect_anomalies(conn, transactions)
    conn.close()

    if anomalies:
        flash(f'🔍 Audit Complete: Sentinel found {len(anomalies)} active financial anomalies requiring review.', 'warning')
    else:
        flash('✨ Audit Complete: No unaddressed anomalies or suspicious duplicate charges detected!', 'success')

    return redirect(url_for('index'))


@app.route('/audit/verify', methods=['POST'])
def audit_verify():
    conn = get_db_connection()
    ensure_columns(conn)
    is_valid, bad_id, total_checked = verify_ledger_integrity(conn)
    conn.close()

    if is_valid:
        flash(f'✅ Ledger Verification Passed: All {total_checked} cryptographic SHA-256 blocks are valid and untampered.', 'success')
    else:
        flash(f'🚨 Security Alert: Ledger chain integrity check FAILED at Transaction #{bad_id}! Unauthorized tampering detected.', 'error')

    return redirect(url_for('index'))


@app.route('/analytics')
def analytics():
    conn = get_db_connection()

    trend_rows = conn.execute('''
        SELECT 
            strftime('%Y-%m', date) as month,
            type,
            SUM(amount * exchange_rate) as total
        FROM transactions
        GROUP BY month, type
        ORDER BY month ASC
    ''').fetchall()

    month_dict = {}
    for r in trend_rows:
        m = r['month']
        if m not in month_dict:
            month_dict[m] = {'income': 0.0, 'expense': 0.0}
        month_dict[m][r['type']] = round(r['total'], 2)

    trend_months = sorted(list(month_dict.keys()))
    trend_incomes = [month_dict[m]['income'] for m in trend_months]
    trend_expenses = [month_dict[m]['expense'] for m in trend_months]

    tot_inc = sum(trend_incomes)
    tot_exp = sum(trend_expenses)
    current_balance = tot_inc - tot_exp

    cat_rows = conn.execute('''
        SELECT category, SUM(amount * exchange_rate) as total
        FROM transactions
        WHERE type = 'expense'
        GROUP BY category
        ORDER BY total DESC
    ''').fetchall()

    cat_labels = [r['category'] for r in cat_rows]
    cat_totals = [round(r['total'], 2) for r in cat_rows]

    monte_carlo = run_monte_carlo_simulation(current_balance, trend_incomes, trend_expenses)

    conn.close()

    return render_template(
        'analytics.html',
        trend_months=trend_months,
        trend_incomes=trend_incomes,
        trend_expenses=trend_expenses,
        cat_labels=cat_labels,
        cat_totals=cat_totals,
        monte_carlo=monte_carlo
    )


def read_transaction_form(existing=None):
    """Validate a legacy transaction form. Returns (fields, None) or (None, error message).

    When editing, a missing currency / rate field keeps the transaction's existing value
    instead of silently converting it to USD at rate 1.0.
    """
    title = request.form.get('title', '').strip()
    amount_raw = request.form.get('amount', '').strip()
    type_ = request.form.get('type', '').strip()
    category = request.form.get('category', '').strip()
    date = request.form.get('date', '').strip()
    notes = request.form.get('notes', '').strip()

    if not title or not amount_raw or not type_ or not category or not date:
        return None, 'All fields except notes are required.'
    if type_ not in ('income', 'expense'):
        return None, 'Type must be income or expense.'
    if not is_valid_date(date):
        return None, 'Enter a valid date.'
    try:
        amount = parse_positive_float(amount_raw)
    except ValueError:
        return None, 'Amount must be a number greater than zero.'

    if 'currency' in request.form:
        currency = get_selected_currency(request.form.get('currency'))
    else:
        currency = existing['currency'] if existing is not None and existing['currency'] else 'USD'

    if 'exchange_rate' in request.form:
        exchange_rate = resolve_exchange_rate(request.form.get('exchange_rate'), currency)
    elif existing is not None and existing['currency'] == currency:
        exchange_rate = existing['exchange_rate']
    else:
        exchange_rate = DEFAULT_MARKET_RATES.get(currency, 1.0)

    return {
        'title': title, 'amount': amount, 'type': type_, 'category': category, 'date': date,
        'notes': notes, 'currency': currency, 'exchange_rate': exchange_rate,
    }, None


@app.route('/add', methods=['GET', 'POST'])
def add_transaction():
    if request.method == 'POST':
        fields, error = read_transaction_form()
        if error:
            flash(error, 'error')
            return redirect(url_for('add_transaction'))

        conn = get_db_connection()
        ensure_columns(conn)

        last_row = conn.execute("SELECT curr_hash FROM transactions ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = last_row['curr_hash'] if last_row and last_row['curr_hash'] else GENESIS_HASH

        curr_hash = compute_row_hash(prev_hash, fields['date'], fields['title'], fields['amount'], fields['type'],
                                     fields['category'], fields['notes'], fields['currency'], fields['exchange_rate'])

        conn.execute(
            '''INSERT INTO transactions (title, amount, type, category, date, notes, currency, exchange_rate, prev_hash, curr_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (fields['title'], fields['amount'], fields['type'], fields['category'], fields['date'], fields['notes'],
             fields['currency'], fields['exchange_rate'], prev_hash, curr_hash)
        )
        conn.commit()
        conn.close()

        flash(f"Transaction booked in {fields['currency']} (Rate: {fields['exchange_rate']:.4f}) & cryptographically sealed!", 'success')
        return redirect(url_for('index'))

    return render_template('add_transaction.html', rates=DEFAULT_MARKET_RATES)


@app.route('/delete/<int:id>', methods=['POST'])
def delete_transaction(id):
    conn = get_db_connection()
    ensure_columns(conn)
    conn.execute('DELETE FROM transactions WHERE id = ?', (id,))
    conn.execute('DELETE FROM dismissed_anomalies WHERE transaction_id = ?', (id,))
    conn.commit()

    rebuild_ledger_chain(conn)
    conn.close()

    flash('Transaction removed and ledger chain successfully re-sealed.', 'warning')
    return redirect(url_for('index'))


@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_transaction(id):
    conn = get_db_connection()
    ensure_columns(conn)
    transaction = conn.execute('SELECT * FROM transactions WHERE id = ?', (id,)).fetchone()

    if transaction is None:
        conn.close()
        flash('Transaction not found.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        fields, error = read_transaction_form(existing=transaction)
        if error:
            conn.close()
            flash(error, 'error')
            return redirect(url_for('edit_transaction', id=id))

        conn.execute(
            'UPDATE transactions SET title=?, amount=?, type=?, category=?, date=?, notes=?, currency=?, exchange_rate=? WHERE id=?',
            (fields['title'], fields['amount'], fields['type'], fields['category'], fields['date'], fields['notes'],
             fields['currency'], fields['exchange_rate'], id)
        )
        conn.commit()

        rebuild_ledger_chain(conn)
        conn.close()

        flash('Transaction updated and ledger chain re-sealed.', 'info')
        return redirect(url_for('index'))

    conn.close()
    return render_template('edit_transaction.html', transaction=transaction, rates=DEFAULT_MARKET_RATES)


@app.route('/budgets', methods=['GET', 'POST'])
def manage_budgets():
    if request.method == 'POST':
        category = request.form.get('category', '').strip()
        limit_raw = request.form.get('monthly_limit', '').strip()
        currency = get_selected_currency(request.form.get('currency'))

        if not category or not limit_raw:
            flash('Category and monthly limit are required.', 'error')
            return redirect(url_for('manage_budgets'))

        try:
            limit = parse_positive_float(limit_raw)
        except ValueError:
            flash('Monthly limit must be a number greater than zero.', 'error')
            return redirect(url_for('manage_budgets'))

        conn = get_db_connection()
        ensure_columns(conn)
        conn.execute('''
            INSERT INTO budgets (category, monthly_limit, currency)
            VALUES (?, ?, ?)
            ON CONFLICT(category) DO UPDATE SET monthly_limit = excluded.monthly_limit, currency = excluded.currency
        ''', (category, limit, currency))
        conn.commit()
        conn.close()

        flash(f'Budget for "{category}" updated successfully!', 'success')
        return redirect(url_for('manage_budgets'))

    conn = get_db_connection()
    ensure_columns(conn)
    budgets = conn.execute('SELECT * FROM budgets ORDER BY category ASC').fetchall()
    conn.close()
    return render_template('budgets.html', budgets=budgets, currency_symbols=CURRENCY_SYMBOLS)


@app.route('/budgets/delete/<int:id>', methods=['POST'])
def delete_budget(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM budgets WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Budget removed successfully!', 'warning')
    return redirect(url_for('manage_budgets'))


@app.route('/export/csv')
def export_csv():
    conn = get_db_connection()
    ensure_columns(conn)
    transactions = conn.execute('SELECT * FROM transactions ORDER BY date DESC, id DESC').fetchall()
    conn.close()

    def safe_cell(value):
        # Prevent CSV/formula injection when the file is opened in Excel or Sheets
        text = '' if value is None else str(value)
        return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(['ID', 'Date', 'Title', 'Category', 'Type', 'Currency', 'Amount', 'FX_Rate_to_USD', 'Normalized_USD', 'Notes', 'SHA256_Hash'])

    for t in transactions:
        curr = t['currency'] if 'currency' in t.keys() else 'USD'
        rate = t['exchange_rate'] if 'exchange_rate' in t.keys() else 1.0
        writer.writerow([
            t['id'],
            t['date'],
            safe_cell(t['title']),
            safe_cell(t['category']),
            t['type'].capitalize(),
            curr,
            f"{t['amount']:.2f}",
            f"{rate:.4f}",
            f"{t['amount'] * rate:.2f}",
            safe_cell(t['notes'] or ''),
            t['curr_hash'] if 'curr_hash' in t.keys() else ''
        ])

    output.seek(0)
    filename = f"multicurrency_transactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route('/transactions/bulk', methods=['POST'])
def bulk_transactions():
    conn = get_db_connection()
    ensure_columns(conn)

    action = request.form.get('action')
    raw_ids = request.form.get('selected_ids', '')
    selected_ids = [int(i) for i in raw_ids.split(',') if i.strip().isdigit()]

    if not selected_ids:
        conn.close()
        flash('No transactions selected for bulk action.', 'warning')
        return redirect(url_for('index'))

    if action == 'delete':
        for tid in selected_ids:
            conn.execute('DELETE FROM transactions WHERE id = ?', (tid,))
            conn.execute('DELETE FROM dismissed_anomalies WHERE transaction_id = ?', (tid,))
        conn.commit()
        rebuild_ledger_chain(conn)
        flash(f'Successfully deleted {len(selected_ids)} transactions.', 'warning')

    elif action == 'recategorize':
        new_cat = request.form.get('new_category', '').strip()
        if new_cat:
            for tid in selected_ids:
                conn.execute('UPDATE transactions SET category = ? WHERE id = ?', (new_cat, tid))
            conn.commit()
            rebuild_ledger_chain(conn)
            flash(f'Recategorized {len(selected_ids)} transactions to "{new_cat}".', 'success')
        else:
            flash('Category name required for bulk recategorization.', 'error')

    conn.close()
    return redirect(url_for('index'))


@app.route('/savings/deposit/<int:id>', methods=['POST'])
def deposit_savings(id):
    conn = get_db_connection()
    ensure_columns(conn)

    amt_raw = request.form.get('deposit_amount', '0')
    try:
        amt = parse_positive_float(amt_raw)
        conn.execute('UPDATE savings_goals SET current_amount = current_amount + ? WHERE id = ?', (amt, id))
        conn.commit()
        flash('Goal deposit recorded successfully!', 'success')
    except ValueError:
        flash('Deposit amount must be a positive number.', 'error')

    conn.close()
    # The deposit form lives on the Financial Hub page, so return there
    return redirect(url_for('financial_hub'))


FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend', 'dist')


@app.route('/')
@app.route('/<path:path>')
def react_frontend(path=''):
    """Serve the compiled React app while allowing Flask to own API routes."""
    if path == 'api' or path.startswith('api/'):
        # Unknown API URLs must fail as JSON, not return the HTML shell with a 200
        return jsonify({'error': 'Not found.'}), 404
    requested_file = os.path.join(FRONTEND_DIST, path)
    if path and os.path.isfile(requested_file):
        return send_from_directory(FRONTEND_DIST, path)
    if os.path.isfile(os.path.join(FRONTEND_DIST, 'index.html')):
        return send_from_directory(FRONTEND_DIST, 'index.html')
    return Response(
        'React client not built. Run `npm install` and `npm run build` in the frontend folder, or use `npm run dev` for development.',
        status=503,
        mimetype='text/plain'
    )


def initialize_database():
    """Create missing tables/columns on startup and re-seal any rows that were never hashed
    (e.g. rows that existed before the ledger columns were added)."""
    init_db()
    conn = get_db_connection()
    try:
        ensure_columns(conn)
        unsealed = conn.execute("SELECT COUNT(*) AS n FROM transactions WHERE curr_hash = '' OR prev_hash = ''").fetchone()['n']
        if unsealed:
            rebuild_ledger_chain(conn)
    finally:
        conn.close()


initialize_database()


if __name__ == '__main__':
    # Debug mode exposes the interactive Werkzeug debugger (remote code execution) and runs a
    # reloader that breaks PyInstaller builds, so it is opt-in: set VAULTLEDGER_DEBUG=1.
    debug_mode = os.environ.get('VAULTLEDGER_DEBUG', '').lower() in ('1', 'true', 'yes')
    app.run(host='127.0.0.1', port=int(os.environ.get('VAULTLEDGER_PORT', '5000')), debug=debug_mode)
