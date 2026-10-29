# 🛡️ VaultLedger — Personal Treasury & Multi-Currency Engine

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
![Flask](https://img.shields.io/badge/Flask-3.0%2B-black?style=flat-square&logo=flask)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react)
![Vite](https://img.shields.io/badge/Vite-5.0-646CFF?style=flat-square&logo=vite)
![Security](https://img.shields.io/badge/Ledger-SHA--256%20Merkle-emerald?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

**VaultLedger** is a local-first, privacy-focused personal finance management platform and accounting engine built with Python (Flask), React 18, and SQLite. Features real-time multi-currency conversion, cryptographic SHA-256 ledger integrity verification, statistical fraud sentinel detection, and foreign exchange gain/loss tracking.

---

## Smart features (all offline, on your own data)

- **Write entries in plain words.** Type `Lunch 250 yesterday`, `salary 85k on 1 Nov`, `coffee 4.50 euros` or `Netflix 649 via HDFC` on the Overview and press Enter. Amount, currency, date, account, direction and category are filled in for you, and you can see what it understood before saving.
- **Categories that learn.** Suggestions come from how you categorised similar entries before, then from a vocabulary of common Indian merchants (Swiggy, Zomato, Uber, Blinkit, Jio...). Rules on *Categories & rules* always win and can re-file past entries.
- **Forecasts.** A month-end spending estimate that combines your everyday pace with bills still due, a free-to-spend-per-day figure, and per-budget warnings such as "on pace to go over by ₹1,200".
- **Recurring detection.** Rent, subscriptions, bills and salary are found from the ledger by name, schedule and amount; track them with one click so they count before they're paid.
- **Notes.** Short plain-English observations each month: budgets at risk, bills due soon, categories up or down against the same point last month, possible duplicates.

Code: `intelligence.py` (engine) and the `/api/overview`, `/api/parse`, `/api/suggest`, `/api/recurring`, `/api/rules` and `/api/reports` endpoints in `app.py`.

Keyboard: `N` new entry, `/` search the ledger, `1`–`8` switch sections, `P` hide amounts.

## ✨ Core Features

### 🛡️ 1. Cryptographic Ledger Integrity
- **SHA-256 Merkle Verification**: Every transaction generates a cryptographic hash incorporating the previous row's signature.
- **Tamper Alert Drawer**: Detects direct database manipulation or unauthorized row modification with one-click integrity verification.

### 💱 2. Multi-Currency & FX Engine (ASC 830 / IAS 21)
- **Multi-Currency Support**: Native handling of `USD ($)`, `EUR (€)`, `GBP (£)`, `INR (₹)`, `CAD ($)`, and `JPY (¥)`.
- **Weighted Average Cost Basis**: Maintains inventory acquisition rates across inflows and crystallizes realized P&L on outflows.
- **Mark-to-Market Valuation**: Computes unrealized paper gains/losses based on real-time market exchange rates.
- **FX Rate Simulator**: Interactive what-if inputs to test exchange rate fluctuation impact on portfolio value.

### 🚨 3. Statistical Fraud Sentinel
- **Outlier Detection**: Automated Z-score algorithm flagging unusual category spending spikes ($\ge +2.0\sigma$).
- **Duplicate Charge Detection**: Detects identical title and amount transactions occurring within a 48-hour window.
- **One-Click Dismissal**: Mark flagged charges as authorized to dismiss sentinel alerts.

### 📊 4. Overview & Financial Health
- **Live Cash Flow Metrics**: Instant totals for income, expenses, net balance, and month-over-month comparisons.
- **Financial Health Score**: Dynamic algorithm scoring savings rates (0–100) with financial status indicators.
- **Runway & Burn Rate Pace**: Calculates daily burn rate, safe daily spend limits, and remaining cash runway in days.

### ⚡ 5. Financial Hub
- **Multi-Account Wallets**: Track balances across Checking, Savings, Credit Cards, and Crypto Wallets.
- **Subscription Sentinel**: Visual timeline tracking upcoming recurring subscriptions (e.g., Netflix, Spotify, Rent).
- **Visual Savings Goal Jars**: Target goal cards with progress rings, initial funds, and interactive deposit triggers.
- **Tax Liability Estimator**: Real-time estimated quarterly tax liability calculator for freelance and multi-currency income.

### 🎯 6. Category Budgets & Bulk Operations
- **Category Guardrails**: Set monthly spending limits with progress indicators (`On Track`, `Near Limit`, `Over Budget`).
- **Floating Bulk Toolbar**: Multi-select row checkboxes for **Bulk Delete** and **Bulk Recategorize**.
- **Instant Category Chips**: Filter transactions by `Income`, `Dining`, `Housing`, `Transport`, or `Sentinel Flagged`.

### ⌨️ 7. Hotkeys & Privacy Mode
- `Press A` → Open Quick Add Transaction modal.
- `Press /` → Focus instant transaction search bar.
- `Press P` → Toggle Privacy Mode (blur financial numbers).

---

## 🛠️ Tech Stack

- **Backend**: Python 3.10+, Flask, SQLite3, hashlib, pyinstaller
- **Frontend**: React 18, Vite, CSS3 Glassmorphism (Dark / Light mode)
- **Architecture**: REST API endpoints with React Single Page Application frontend

---

## 📂 Project Structure

```text
VaultLedger/
├── app.py                     # Flask REST API server & cryptographic ledger engine
├── db.py                      # SQLite database connection helper
├── schema.sql                 # Base database table schemas
├── Start-FinanceTracker.bat   # 1-Click Windows batch launcher
├── Start-FinanceTracker.vbs   # 1-Click silent Windows launcher (no CMD window)
├── CreateDesktopShortcut.bat  # Script to generate desktop shortcut icon
├── FinanceTracker.spec        # PyInstaller recipe: `pyinstaller FinanceTracker.spec` builds dist/VaultLedger.exe
├── static/
│   ├── css/                   # Modular CSS stylesheets (theme, components, dashboard)
│   └── styles.css             # CSS entrypoint
├── templates/                 # Jinja2 template fallbacks
├── frontend/                  # React 18 SPA frontend workspace
│   ├── src/
│   │   ├── App.jsx            # Main React SPA component
│   │   └── styles.css         # Component glassmorphism styles
│   ├── dist/                  # Production compiled React bundle
│   ├── package.json
│   └── vite.config.js
└── requirements.txt           # Python backend dependencies
```

---

## 🚀 Quick Start

### Option 1: Standalone Launcher (Windows)
Double-click any of the following files in the project folder:
- **`Start-FinanceTracker.vbs`**: Silent 1-click Terminal Launcher 

### Option 2: Run from Source

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/your-username/VaultLedger.git
   cd VaultLedger
   ```

2. **Install Python Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the Application**:
   ```bash
   python app.py
   ```

4. **Open in Browser**:
   Navigate to [http://127.0.0.1:5000](http://127.0.0.1:5000).

---

