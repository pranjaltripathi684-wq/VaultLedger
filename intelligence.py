"""
VaultLedger intelligence engine.

Everything here runs locally on the user's own data, with no external services:

  * suggest_category()   - learns categories from past entries, user rules and a seed vocabulary
  * parse_entry()        - turns "Lunch 250 yesterday" into a structured transaction
  * detect_recurring()   - finds repeating charges / income (rent, Netflix, salary)
  * build_forecast()     - month-end projection, budget pacing and safe-to-spend
  * build_insights()     - short plain-English observations about the month

All money is handled in USD base (amount * exchange_rate) internally and converted to the
display currency by the caller-supplied factor.
"""
import re
import calendar
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

SEED_CATEGORIES = {
    'Food & Dining': 'swiggy zomato restaurant lunch dinner breakfast cafe coffee chai tea pizza burger dominos '
                     'mcdonalds kfc starbucks biryani snacks food meal dosa thali canteen bakery juice eatery',
    'Groceries': 'grocery groceries bigbasket blinkit zepto instamart dmart vegetables veggies milk fruits '
                 'supermarket kirana eggs bread ration',
    'Transport': 'uber ola rapido metro bus train irctc cab taxi auto rickshaw petrol diesel fuel parking toll '
                 'fastag commute',
    'Housing': 'rent maintenance landlord pg hostel society housing',
    'Utilities': 'electricity water gas internet wifi broadband jio airtel recharge mobile bill bescom '
                 'postpaid prepaid cylinder',
    'Subscriptions': 'netflix spotify prime hotstar youtube icloud chatgpt subscription github notion '
                     'membership adobe canva',
    'Shopping': 'amazon flipkart myntra ajio meesho nykaa clothes shoes shirt jeans shopping gadget',
    'Health': 'pharmacy medicine medicines doctor hospital apollo medplus gym clinic dental checkup',
    'Entertainment': 'movie movies pvr inox bookmyshow concert game games steam party',
    'Education': 'course udemy coursera book books fees tuition college exam',
    'Travel': 'hotel airbnb oyo makemytrip goibibo trip travel flight indigo vacation',
    'Salary': 'salary payroll stipend paycheck wages bonus',
    'Freelance': 'freelance client invoice consulting upwork fiverr project',
    'Refunds & interest': 'refund cashback interest dividend reimbursement',
    'Gifts': 'gift gifts birthday wedding donation charity',
}
INCOME_CATEGORIES = {'Salary', 'Freelance', 'Refunds & interest'}
INCOME_WORDS = {'salary', 'received', 'receive', 'credited', 'credit', 'refund', 'cashback', 'income', 'earned',
                'stipend', 'payroll', 'dividend', 'interest', 'reimbursement', 'got', 'payout', 'bonus'}

SEED_INDEX = {}
for _cat, _words in SEED_CATEGORIES.items():
    for _w in _words.split():
        SEED_INDEX[_w] = _cat

STOPWORDS = {'a', 'an', 'the', 'to', 'of', 'in', 'on', 'at', 'for', 'with', 'via', 'using', 'by', 'and', 'my',
             'from', 'spent', 'spend', 'paid', 'pay', 'bought', 'buy', 'got', 'was', 'is', 'some', 'rs', 'inr'}

CURRENCY_WORDS = {
    '₹': 'INR', 'rs': 'INR', 'rs.': 'INR', 'inr': 'INR', 'rupee': 'INR', 'rupees': 'INR', 'rupaye': 'INR',
    '$': 'USD', 'usd': 'USD', 'dollar': 'USD', 'dollars': 'USD', 'bucks': 'USD',
    '€': 'EUR', 'eur': 'EUR', 'euro': 'EUR', 'euros': 'EUR',
    '£': 'GBP', 'gbp': 'GBP', 'pound': 'GBP', 'pounds': 'GBP', 'quid': 'GBP',
    'cad': 'CAD', 'c$': 'CAD',
    '¥': 'JPY', 'jpy': 'JPY', 'yen': 'JPY',
}

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})
WEEKDAYS = {d.lower(): i for i, d in enumerate(calendar.day_name)}
WEEKDAYS.update({d.lower(): i for i, d in enumerate(calendar.day_abbr)})


def tokenize(text):
    return [t for t in re.findall(r"[a-z]+", (text or '').lower()) if len(t) > 1]


def normalize_title(title):
    """'Netflix Oct 2026' and 'netflix' -> 'netflix' (used for recurring + exact matches)."""
    words = [t for t in tokenize(title) if t not in MONTHS and t not in STOPWORDS]
    return ' '.join(words)


def base_amount(row):
    return row['amount'] * (row['exchange_rate'] or 1.0)


def to_date(value):
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 1. Auto-categorization
# ---------------------------------------------------------------------------

def suggest_category(title, transactions, rules=(), limit=3):
    """Rank likely categories for a title.

    Sources, strongest first:
      rule     - a user rule whose keyword appears in the title (always wins)
      history  - entries with the same normalized title, then shared words
      keyword  - built-in vocabulary
    Returns {'suggestions': [{category, score, source}], 'type': 'income'|'expense'|None}
    """
    text = (title or '').lower()
    norm = normalize_title(title)
    tokens = set(tokenize(title))
    scores = defaultdict(float)
    sources = {}

    for rule in rules:
        kw = (rule['match_keyword'] or '').strip().lower()
        if kw and rule['action_category'] and kw in text:
            scores[rule['action_category']] += 10.0
            sources[rule['action_category']] = 'rule'

    if norm:
        exact = Counter(t['category'] for t in transactions if normalize_title(t['title']) == norm)
        total = sum(exact.values())
        for cat, n in exact.items():
            scores[cat] += 4.0 * n / total
            sources.setdefault(cat, 'history')

    if tokens:
        token_votes = defaultdict(Counter)
        for t in transactions:
            for tok in set(tokenize(t['title'])) - STOPWORDS:
                token_votes[tok][t['category']] += 1
        for tok in tokens - STOPWORDS:
            votes = token_votes.get(tok)
            if votes:
                n = sum(votes.values())
                for cat, c in votes.items():
                    scores[cat] += 1.5 * c / n
                    sources.setdefault(cat, 'history')

    for tok in tokens:
        cat = SEED_INDEX.get(tok)
        if cat:
            # Prefer the user's own spelling of a similar category if they have one
            own = _match_user_category(cat, transactions)
            scores[own] += 1.0
            sources.setdefault(own, 'keyword')

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    top_total = sum(s for _, s in ranked) or 1.0
    suggestions = [{'category': c, 'score': round(s / top_total, 2), 'source': sources[c]} for c, s in ranked]

    entry_type = None
    if tokens & INCOME_WORDS:
        entry_type = 'income'
    elif suggestions:
        best = suggestions[0]['category']
        history_types = Counter(t['type'] for t in transactions if t['category'] == best)
        if history_types:
            entry_type = history_types.most_common(1)[0][0]
        else:
            entry_type = 'income' if best in INCOME_CATEGORIES else 'expense'
    return {'suggestions': suggestions, 'type': entry_type}


def _match_user_category(seed_cat, transactions):
    seed_words = set(tokenize(seed_cat))
    for t in transactions:
        if seed_words & set(tokenize(t['category'])):
            return t['category']
    return seed_cat


# ---------------------------------------------------------------------------
# 2. Natural-language quick entry
# ---------------------------------------------------------------------------

_AMOUNT_RE = re.compile(
    r"(?P<pre>[₹$€£¥]|c\$|rs\.?|inr|usd|eur|gbp|cad|jpy)?\s*"
    r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<mult>k|thousand|l|lakh|lac|lakhs|cr|crore)?\b\s*"
    r"(?P<post>rupees?|rupaye|rs\.?|inr|dollars?|bucks|usd|euros?|eur|pounds?|quid|gbp|cad|yen|jpy)?",
    re.IGNORECASE,
)
_MULTIPLIERS = {'k': 1e3, 'thousand': 1e3, 'l': 1e5, 'lakh': 1e5, 'lac': 1e5, 'lakhs': 1e5, 'cr': 1e7, 'crore': 1e7}


def _parse_date(text, today):
    """Find a date expression. Returns (date, matched_span_text) or (None, None)."""
    low = text.lower()
    patterns = [
        (r"\bday before yesterday\b", lambda m: today - timedelta(days=2)),
        (r"\byesterday\b|\byday\b", lambda m: today - timedelta(days=1)),
        (r"\btoday\b|\btonight\b|\bthis morning\b", lambda m: today),
        (r"\b(\d{1,2}) days? ago\b", lambda m: today - timedelta(days=int(m.group(1)))),
        (r"\blast week\b", lambda m: today - timedelta(days=7)),
        (r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: date(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
        # 12/10 or 12/10/2026 (day first, Indian convention)
        (r"\b(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?\b",
         lambda m: _safe_date(_year(m.group(3), today), int(m.group(2)), int(m.group(1)), today)),
        # 12 oct / 12th october
        (r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + '|'.join(sorted(MONTHS, key=len, reverse=True)) + r")\b",
         lambda m: _safe_date(None, MONTHS[m.group(2)], int(m.group(1)), today)),
        # oct 12
        (r"\b(" + '|'.join(sorted(MONTHS, key=len, reverse=True)) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b",
         lambda m: _safe_date(None, MONTHS[m.group(1)], int(m.group(2)), today)),
        # (last) monday
        (r"\b(?:on\s+)?(last\s+)?(" + '|'.join(sorted(WEEKDAYS, key=len, reverse=True)) + r")\b",
         lambda m: _weekday(today, WEEKDAYS[m.group(2)], bool(m.group(1)))),
    ]
    for pattern, builder in patterns:
        m = re.search(pattern, low)
        if m:
            try:
                d = builder(m)
            except (ValueError, KeyError):
                d = None
            if d:
                return d, text[m.start():m.end()]
    return None, None


def _year(raw, today):
    if not raw:
        return None
    y = int(raw)
    return y + 2000 if y < 100 else y


def _safe_date(year, month, day, today):
    if year is None:
        candidate = date(today.year, month, day)
        # "12 dec" typed in January means last December, not the future
        if candidate > today + timedelta(days=31):
            candidate = date(today.year - 1, month, day)
        return candidate
    return date(year, month, day)


def _weekday(today, weekday, explicit_last):
    delta = (today.weekday() - weekday) % 7
    if delta == 0 and explicit_last:
        delta = 7
    return today - timedelta(days=delta)


def parse_entry(text, today, transactions, rules=(), default_currency='INR', accounts=()):
    """Parse free text like 'Uber 340 yesterday' or 'salary 85k on 1 oct' into a transaction draft."""
    original = (text or '').strip()
    working = ' ' + original + ' '
    result = {'title': '', 'amount': None, 'currency': default_currency, 'date': today.isoformat(),
              'type': 'expense', 'category': '', 'account_name': None, 'notes': ''}
    understood = {'amount': False, 'currency': False, 'date': False, 'category': None, 'type': False}

    # Account mentions ("via HDFC", "from cash")
    for acc in sorted(accounts, key=len, reverse=True):
        m = re.search(r"\b(?:via|using|from|with|on)?\s*" + re.escape(acc.lower()) + r"\b", working.lower())
        if m:
            result['account_name'] = acc
            working = working[:m.start()] + ' ' + working[m.end():]
            break

    d, span = _parse_date(working, today)
    if d:
        result['date'] = d.isoformat()
        understood['date'] = True
        working = working.replace(span, ' ', 1)
        working = re.sub(r"\b(on|dated)\s+(?=\s|$)", ' ', working, flags=re.IGNORECASE)

    best = None
    for m in _AMOUNT_RE.finditer(working):
        has_currency = bool(m.group('pre') or m.group('post'))
        candidate = (has_currency, m)
        if best is None or (has_currency and not best[0]):
            best = candidate
    if best:
        m = best[1]
        try:
            value = float(m.group('num').replace(',', ''))
            if m.group('mult'):
                value *= _MULTIPLIERS[m.group('mult').lower()]
            result['amount'] = round(value, 2)
            understood['amount'] = value > 0
        except ValueError:
            pass
        marker = (m.group('pre') or m.group('post') or '').lower()
        if marker:
            code = CURRENCY_WORDS.get(marker) or CURRENCY_WORDS.get(marker.rstrip('s')) or CURRENCY_WORDS.get(marker.rstrip('.'))
            if code:
                result['currency'] = code
                understood['currency'] = True
        working = working[:m.start()] + ' ' + working[m.end():]

    # Standalone currency words left over ("250 for lunch in dollars")
    for tok in re.findall(r"[a-z₹$€£¥.]+", working.lower()):
        if tok in CURRENCY_WORDS and not understood['currency']:
            result['currency'] = CURRENCY_WORDS[tok]
            understood['currency'] = True

    words = re.findall(r"[A-Za-z][A-Za-z&'\-]*", working)
    lowered = [w.lower() for w in words]
    is_income = bool(set(lowered) & INCOME_WORDS) or bool(re.search(r"\b(got paid|paid by|payment from)\b", original.lower()))
    title_words = [w for w in words if w.lower() not in STOPWORDS and w.lower() not in CURRENCY_WORDS
                   and w.lower() not in {'received', 'credited', 'income', 'earned', 'expense'}]
    title = ' '.join(title_words).strip()
    if title:
        title = title[0].upper() + title[1:]

    suggestion = suggest_category(title or original, transactions, rules)
    if suggestion['suggestions']:
        top = suggestion['suggestions'][0]
        result['category'] = top['category']
        understood['category'] = top['source']
    if is_income or suggestion['type'] == 'income':
        result['type'] = 'income'
        understood['type'] = True
    result['title'] = title or result['category'] or 'Untitled'

    missing = [f for f in ('amount',) if not understood['amount']]
    if not result['category']:
        missing.append('category')
    return {'entry': result, 'understood': understood, 'missing': missing,
            'alternatives': [s['category'] for s in suggestion['suggestions'][1:]]}


# ---------------------------------------------------------------------------
# 3. Recurring detection
# ---------------------------------------------------------------------------

CADENCES = [
    ('weekly', 7, 5, 9),
    ('monthly', 30.4, 25, 36),
    ('quarterly', 91, 80, 100),
    ('yearly', 365, 340, 390),
]


def _add_cadence(d, cadence, median_gap):
    if cadence == 'monthly':
        month = d.month + 1
        year = d.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))
    if cadence == 'yearly':
        try:
            return d.replace(year=d.year + 1)
        except ValueError:
            return d + timedelta(days=365)
    return d + timedelta(days=round(median_gap))


def detect_recurring(transactions, today, tracked_names=()):
    """Find series of entries with the same normalized title, a steady cadence and similar amounts."""
    groups = defaultdict(list)
    for t in transactions:
        key = normalize_title(t['title'])
        if key:
            groups[(key, t['type'], t['currency'] or 'USD')].append(t)

    tracked = {normalize_title(n) for n in tracked_names}
    found = []
    for (key, type_, currency), rows in groups.items():
        rows = sorted(rows, key=lambda r: (r['date'], r['id']))
        dates = [to_date(r['date']) for r in rows]
        if None in dates or len(rows) < 2:
            continue
        gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
        if not gaps:
            continue
        median_gap = statistics.median(gaps)
        cadence = next((name for name, _, lo, hi in CADENCES if lo <= median_gap <= hi), None)
        if not cadence:
            continue
        if cadence == 'weekly' and len(rows) < 3:
            continue
        # Most gaps must agree with the cadence
        _, _, lo, hi = next(c for c in CADENCES if c[0] == cadence)
        if sum(1 for g in gaps if lo <= g <= hi) < max(1, round(len(gaps) * 0.6)):
            continue
        amounts = [r['amount'] for r in rows]
        median_amount = statistics.median(amounts)
        spread = (max(amounts) - min(amounts)) / median_amount if median_amount else 1
        if spread > 0.6:
            continue
        last = dates[-1]
        next_date = _add_cadence(last, cadence, median_gap)
        # Roll forward if the expected date has long passed (it may simply not be logged yet)
        status = 'upcoming'
        if next_date < today - timedelta(days=7):
            status = 'missed'
        days_until = (next_date - today).days
        per_month = {'weekly': 52 / 12, 'monthly': 1, 'quarterly': 1 / 3, 'yearly': 1 / 12}[cadence]
        rate = rows[-1]['exchange_rate'] or 1.0
        found.append({
            'key': key,
            'name': rows[-1]['title'],
            'type': type_,
            'category': Counter(r['category'] for r in rows).most_common(1)[0][0],
            'currency': currency,
            'amount': round(statistics.median(amounts[-3:]), 2),
            'amount_usd': round(statistics.median(amounts[-3:]) * rate, 4),
            'fixed_amount': spread <= 0.15,
            'cadence': cadence,
            'occurrences': len(rows),
            'last_date': last.isoformat(),
            'next_date': next_date.isoformat(),
            'days_until': days_until,
            'status': status,
            'monthly_usd': round(statistics.median(amounts[-3:]) * rate * per_month, 4),
            'tracked': key in tracked,
        })
    found.sort(key=lambda r: (r['status'] != 'upcoming', r['days_until']))
    return found


# ---------------------------------------------------------------------------
# 4. Forecasts and budget pacing
# ---------------------------------------------------------------------------

def _month_bounds(d):
    first = d.replace(day=1)
    days = calendar.monthrange(d.year, d.month)[1]
    return first, days


def _prev_month(d):
    first = d.replace(day=1)
    return (first - timedelta(days=1)).replace(day=1)


def build_forecast(transactions, budgets, recurring, subscriptions, today, rates):
    """Month-end projection, cumulative spending curves, budget pacing and safe-to-spend (all in USD)."""
    first, days_in_month = _month_bounds(today)
    day = today.day
    days_left = days_in_month - day  # days after today
    month_key = today.strftime('%Y-%m')
    prev_first = _prev_month(today)
    prev_key = prev_first.strftime('%Y-%m')
    prev_days = calendar.monthrange(prev_first.year, prev_first.month)[1]

    def in_month(t, key):
        return str(t['date']).startswith(key)

    expenses_month = [t for t in transactions if t['type'] == 'expense' and in_month(t, month_key) and to_date(t['date']) and to_date(t['date']) <= today]
    expenses_prev = [t for t in transactions if t['type'] == 'expense' and in_month(t, prev_key)]
    income_month = sum(base_amount(t) for t in transactions if t['type'] == 'income' and in_month(t, month_key))

    # Daily cumulative curves
    def cumulative(rows, n_days):
        per_day = [0.0] * (n_days + 1)
        for t in rows:
            d = to_date(t['date'])
            if d and 1 <= d.day <= n_days:
                per_day[d.day] += base_amount(t)
        out, running = [], 0.0
        for i in range(1, n_days + 1):
            running += per_day[i]
            out.append(running)
        return out

    this_cum = cumulative(expenses_month, days_in_month)[:day]
    prev_cum = cumulative(expenses_prev, prev_days)
    spent = this_cum[-1] if this_cum else 0.0
    prev_total = prev_cum[-1] if prev_cum else 0.0
    prev_same_day = prev_cum[min(day, prev_days) - 1] if prev_cum else 0.0

    # Recurring items still to come this month (detected + tracked subscriptions), USD
    month_end = first.replace(day=days_in_month)
    upcoming = []
    seen = set()
    for r in recurring:
        nd = to_date(r['next_date'])
        if r['type'] == 'expense' and r['status'] == 'upcoming' and nd and today < nd <= month_end:
            upcoming.append({'name': r['name'], 'date': r['next_date'], 'amount_usd': r['amount_usd'], 'category': r['category']})
            seen.add(r['key'])
    for s in subscriptions:
        nd = to_date(s['next_due_date'])
        if nd and today < nd <= month_end and normalize_title(s['name']) not in seen:
            upcoming.append({'name': s['name'], 'date': s['next_due_date'],
                             'amount_usd': s['amount'] * rates.get(s['currency'], 1.0), 'category': s['category']})
    committed = sum(u['amount_usd'] for u in upcoming)

    # Pace of everyday (non-recurring) spending, smoothed for the first days of a month
    recurring_keys = {r['key'] for r in recurring if r['type'] == 'expense'}
    recurring_spent = sum(base_amount(t) for t in expenses_month if normalize_title(t['title']) in recurring_keys)
    everyday_spent = spent - recurring_spent
    pace = everyday_spent / max(day, 7) if day < 7 else everyday_spent / day
    if day < 7 and prev_total:
        # Blend in last month's everyday pace while this month's sample is tiny
        prev_recurring = sum(base_amount(t) for t in expenses_prev if normalize_title(t['title']) in recurring_keys)
        prev_pace = (prev_total - prev_recurring) / prev_days
        weight = day / 7
        pace = pace * weight + prev_pace * (1 - weight)
    projected_total = spent + pace * days_left + committed

    projection_curve = []
    running = spent
    upcoming_by_day = defaultdict(float)
    for u in upcoming:
        upcoming_by_day[to_date(u['date']).day] += u['amount_usd']
    for d_ in range(day + 1, days_in_month + 1):
        running += pace + upcoming_by_day[d_]
        projection_curve.append(running)

    # Income basis for safe-to-spend: this month's income, or the typical month if higher
    monthly_incomes = defaultdict(float)
    for t in transactions:
        if t['type'] == 'income':
            monthly_incomes[str(t['date'])[:7]] += base_amount(t)
    recent_full = [v for k, v in sorted(monthly_incomes.items()) if k < month_key][-3:]
    typical_income = statistics.mean(recent_full) if recent_full else 0.0
    expected_income_left = sum(r['amount_usd'] for r in recurring
                               if r['type'] == 'income' and r['status'] == 'upcoming'
                               and to_date(r['next_date']) and today < to_date(r['next_date']) <= month_end)
    income_basis = max(income_month + expected_income_left, typical_income)
    all_time_net = sum(base_amount(t) if t['type'] == 'income' else -base_amount(t) for t in transactions)

    if income_basis > 0:
        pool = income_basis - spent - committed
        basis = 'income'
    else:
        pool = all_time_net - committed
        basis = 'balance'
    days_for_split = days_left + 1  # including today
    spent_today = sum(base_amount(t) for t in expenses_month if to_date(t['date']) == today)
    safe_per_day = max(0.0, (pool + spent_today) / days_for_split)
    safe_today_left = max(0.0, safe_per_day - spent_today)

    # Budget pacing
    budget_rows = []
    for b in budgets:
        limit_usd = b['monthly_limit'] * rates.get(b['currency'] or 'USD', 1.0)
        cat_rows = [t for t in expenses_month if t['category'] == b['category']]
        cat_spent = sum(base_amount(t) for t in cat_rows)
        cat_recurring = sum(base_amount(t) for t in cat_rows if normalize_title(t['title']) in recurring_keys)
        cat_everyday = cat_spent - cat_recurring
        cat_pace = cat_everyday / max(day, 7)
        cat_committed = sum(u['amount_usd'] for u in upcoming if u['category'] == b['category'])
        cat_projected = cat_spent + cat_pace * days_left + cat_committed
        if cat_spent > limit_usd:
            status = 'over'
        elif cat_projected > limit_usd * 1.02:
            status = 'at_risk'
        else:
            status = 'on_track'
        left = limit_usd - cat_spent
        budget_rows.append({
            'id': b['id'], 'category': b['category'], 'currency': b['currency'] or 'USD',
            'limit_usd': limit_usd, 'spent_usd': cat_spent, 'projected_usd': cat_projected,
            'left_usd': left, 'per_day_left_usd': max(0.0, left) / days_for_split,
            'overshoot_usd': max(0.0, cat_projected - limit_usd), 'status': status,
        })

    return {
        'day': day, 'days_in_month': days_in_month, 'days_left': days_left,
        'spent_usd': spent, 'income_month_usd': income_month,
        'prev_total_usd': prev_total, 'prev_same_day_usd': prev_same_day,
        'projected_total_usd': projected_total, 'committed_usd': committed, 'upcoming': sorted(upcoming, key=lambda u: u['date']),
        'this_cum_usd': this_cum, 'prev_cum_usd': prev_cum, 'projection_usd': projection_curve,
        'safe_per_day_usd': safe_per_day, 'income_basis_usd': income_basis,
        'income_is_typical': income_basis > income_month + expected_income_left, 'safe_today_left_usd': safe_today_left, 'safe_basis': basis,
        'typical_income_usd': typical_income, 'budgets': budget_rows,
    }


# ---------------------------------------------------------------------------
# 5. Plain-English insights
# ---------------------------------------------------------------------------

def due_soon(recurring, subscriptions, today, rates, days=10):
    """Recurring charges/income and tracked subscriptions expected within `days` (crosses month ends)."""
    horizon = today + timedelta(days=days)
    items, seen = [], set()
    for s in subscriptions:
        nd = to_date(s['next_due_date'])
        if nd and today <= nd <= horizon:
            seen.add(normalize_title(s['name']))
            items.append({'name': s['name'], 'date': s['next_due_date'], 'type': 'expense', 'category': s['category'],
                          'amount_usd': s['amount'] * rates.get(s['currency'], 1.0), 'source': 'tracked'})
    for r in recurring:
        nd = to_date(r['next_date'])
        if r['key'] in seen or r['status'] != 'upcoming' or not nd or not (today <= nd <= horizon):
            continue
        items.append({'name': r['name'], 'date': r['next_date'], 'type': r['type'], 'category': r['category'],
                      'amount_usd': r['amount_usd'], 'source': 'detected'})
    return sorted(items, key=lambda i: i['date'])


def build_insights(transactions, forecast, recurring, anomalies, today, fmt, upcoming_items=None):
    """Short observations ranked by usefulness. `fmt(usd)` formats an amount in the display currency."""
    out = []
    month_key = today.strftime('%Y-%m')
    prev_key = _prev_month(today).strftime('%Y-%m')
    day = today.day

    for b in forecast['budgets']:
        if b['status'] == 'over':
            out.append({'tone': 'alert', 'weight': 100, 'title': f"{b['category']} is over budget",
                        'body': f"You've spent {fmt(b['spent_usd'])} of {fmt(b['limit_usd'])}, "
                                f"{fmt(b['spent_usd'] - b['limit_usd'])} more than planned."})
        elif b['status'] == 'at_risk':
            out.append({'tone': 'warn', 'weight': 90, 'title': f"{b['category']} is on pace to go over",
                        'body': f"At this rate you'll spend about {fmt(b['projected_usd'])} against a "
                                f"{fmt(b['limit_usd'])} limit. Keeping to {fmt(b['per_day_left_usd'])} a day keeps it on track."})

    soon = [u for u in (upcoming_items if upcoming_items is not None else forecast['upcoming']) if u.get('type', 'expense') == 'expense']
    if soon:
        first_day = to_date(soon[0]['date'])
        days = (first_day - today).days
        when = 'today' if days == 0 else 'tomorrow' if days == 1 else f"in {days} days"
        bundle = [u for u in soon if u['date'] == soon[0]['date']]
        names = ', '.join(u['name'] for u in bundle[:-1]) + (' and ' if len(bundle) > 1 else '') + bundle[-1]['name']
        total = sum(u['amount_usd'] for u in bundle)
        out.append({'tone': 'info', 'weight': 70 - days, 'title': f"{names} {'are' if len(bundle) > 1 else 'is'} due {when}",
                    'body': f"About {fmt(total)} on {first_day.strftime('%a %d %b').replace(' 0', ' ')}."
                            + (f" {len(soon) - len(bundle)} more bill{'s' if len(soon) - len(bundle) > 1 else ''} in the next 10 days." if len(soon) > len(bundle) else '')})

    prev_same = forecast['prev_same_day_usd']
    spent = forecast['spent_usd']
    if prev_same > 0 and spent > 0 and day >= 5:
        change = (spent - prev_same) / prev_same
        if abs(change) >= 0.15:
            more = change > 0
            out.append({'tone': 'warn' if more else 'good', 'weight': 60,
                        'title': f"Spending is {abs(change):.0%} {'higher' if more else 'lower'} than this time last month",
                        'body': f"{fmt(spent)} so far, compared with {fmt(prev_same)} by day {day} last month."})

    # Category shifts, month-to-date vs the same days last month
    cur = defaultdict(float)
    prev = defaultdict(float)
    for t in transactions:
        if t['type'] != 'expense':
            continue
        d = to_date(t['date'])
        if not d or d.day > day:
            continue
        key = str(t['date'])[:7]
        if key == month_key:
            cur[t['category']] += base_amount(t)
        elif key == prev_key:
            prev[t['category']] += base_amount(t)
    shifts = []
    floor = max(spent * 0.05, 1.0)
    for cat in set(cur) | set(prev):
        a, b_ = cur.get(cat, 0.0), prev.get(cat, 0.0)
        if max(a, b_) < floor or b_ == 0:
            continue
        ratio = (a - b_) / b_
        if abs(ratio) >= 0.3:
            shifts.append((abs(a - b_), cat, a, b_, ratio))
    for _, cat, a, b_, ratio in sorted(shifts, reverse=True)[:2]:
        up = ratio > 0
        out.append({'tone': 'warn' if up else 'good', 'weight': 55,
                    'title': f"{cat} {'up' if up else 'down'} {abs(ratio):.0%}",
                    'body': f"{fmt(a)} this month against {fmt(b_)} at the same point last month."})

    if forecast['prev_total_usd'] > 0 and forecast['days_left'] > 3:
        diff = forecast['projected_total_usd'] - forecast['prev_total_usd']
        if abs(diff) / forecast['prev_total_usd'] >= 0.08:
            out.append({'tone': 'info', 'weight': 50,
                        'title': f"Heading for about {fmt(forecast['projected_total_usd'])} this month",
                        'body': f"That's {fmt(abs(diff))} {'more' if diff > 0 else 'less'} than last month's "
                                f"{fmt(forecast['prev_total_usd'])}, including known bills still to come."})

    for r in recurring:
        if r['type'] == 'income' and r['status'] == 'missed':
            out.append({'tone': 'warn', 'weight': 65, 'title': f"No {r['name'].lower()} recorded yet",
                        'body': f"It usually arrives {r['cadence']}; the last one was on {r['last_date']}."})
    new_recurring = [r for r in recurring if r['type'] == 'expense' and not r['tracked'] and r['status'] == 'upcoming']
    if new_recurring:
        r = new_recurring[0]
        out.append({'tone': 'info', 'weight': 40, 'title': f"{r['name']} looks like a {r['cadence']} charge",
                    'body': f"About {fmt(r['amount_usd'])} each time, {r['occurrences']} times so far. "
                            f"Track it under Recurring to plan around it.", 'action': 'recurring'})

    month_exp = [t for t in transactions if t['type'] == 'expense' and str(t['date']).startswith(month_key)]
    if len(month_exp) >= 5:
        biggest = max(month_exp, key=base_amount)
        if base_amount(biggest) >= spent * 0.25:
            out.append({'tone': 'info', 'weight': 30, 'title': f"{biggest['title']} is your largest expense this month",
                        'body': f"{fmt(base_amount(biggest))}, {base_amount(biggest) / spent:.0%} of everything you've spent."})

    if anomalies:
        dupes = sum(1 for a in anomalies if a['type'] == 'duplicate')
        outliers = len(anomalies) - dupes
        parts = []
        if dupes:
            parts.append(f"{dupes} possible duplicate{'s' if dupes > 1 else ''}")
        if outliers:
            parts.append(f"{outliers} unusually large expense{'s' if outliers > 1 else ''}")
        out.append({'tone': 'warn', 'weight': 75, 'title': 'Worth a second look', 'body': ' and '.join(parts).capitalize() + '.',
                    'action': 'review'})

    income = forecast['income_month_usd']
    if income > 0 and day >= 10:
        rate = (income - spent) / income
        if rate >= 0.2:
            out.append({'tone': 'good', 'weight': 20, 'title': f"You've kept {rate:.0%} of this month's income",
                        'body': f"{fmt(income - spent)} of {fmt(income)} is still unspent."})

    if spent == 0 and day >= 3 and not any(t['type'] == 'expense' and str(t['date']).startswith(month_key) for t in transactions):
        out.append({'tone': 'info', 'weight': 45, 'title': 'No spending recorded this month yet',
                    'body': 'Add entries as you go and the estimates here sharpen within a few days.'})

    out.sort(key=lambda i: i['weight'], reverse=True)
    return out[:7]
