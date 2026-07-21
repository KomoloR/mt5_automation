# MT5 Balance & Order Notifications

Automation scripts that connect to MetaTrader 5 via the Python API and post
account and trade updates to a private Telegram channel.

## What's in this project

### `balance_update.py`
Runs once (via Windows Task Scheduler, daily). For each configured MT5
account, it logs in, pulls current balance/equity, and posts a formatted
update to Telegram showing:
- Current balance
- Daily loss limit and max drawdown floor
- Profit target and remaining deficit

The message header automatically switches between a "New Trading Week"
banner on Mondays and a plain "Daily Update" banner the rest of the week.

Tracks each account's daily starting balance in a small JSON file
(`fp_acc_tracker.json`) so daily drawdown can be measured against the
balance at the start of that trading day.

### `order_notifications.py`
Runs continuously (started at Windows logon, not on a schedule) and polls
MT5 every few seconds for:
- **New pending orders placed** → posts entry price, SL, TP, and volume
- **Pending orders cancelled/deleted before being filled** → deletes the
  corresponding Telegram message
- **Positions closed via Take Profit** → posts updated balance/equity
- **Positions closed via Stop Loss** → posts updated balance, equity,
  remaining daily drawdown, and remaining max drawdown

State (which orders/positions are already known, and their Telegram
message IDs) is kept in `order_notify_state.json` so the script can resume
correctly if restarted.

## Requirements

- Windows, with the MetaTrader 5 desktop terminal installed and logged in
- Python 3.12
- A Telegram bot, added as an **admin** of your channel with permission to
  post and delete messages
- The channel's numeric chat ID (see note below if your channel is private)

Install dependencies:
```bash
pip install MetaTrader5 python-dotenv requests
```

## Setup

1. Copy `.env.example` to `.env` and fill in your real values (see below).
   **Never commit `.env`** — it's already excluded via `.gitignore`.
2. Make sure the MT5 desktop terminal is open and logged in before running
   either script — the Python API attaches to the running terminal rather
   than launching it standalone.
3. Run manually first to confirm everything connects:
   ```bash
   python balance_update.py
   python order_notifications.py
   ```

### `.env` variables

```env
# Telegram
BALANCE_BOT_TOKEN=your_bot_token_here
CHANNEL_CHAT_ID=your_numeric_channel_id_here   # e.g. -1001234567890

# FundingPips account (can be any broker/propfirm acc.)
FP_LOGIN=your_mt5_login
FP_PASSWORD=your_mt5_password
FP_SERVER=your_broker_server_name



If your Telegram channel is **private**, `CHANNEL_CHAT_ID` must be the
numeric chat ID (always starts with `-100` for channels) rather than a
`@username` — private channels don't have a public handle. Get it by
posting once in the channel, then checking
`https://api.telegram.org/bot<TOKEN>/getUpdates` for the `chat.id` field.

## Running on a schedule (Windows Task Scheduler)

**`balance_update.py`** — daily trigger:
- Action: `<project>\.venv\Scripts\python.exe` with argument `balance_update.py`
- Start in: the project folder
- General tab: "Run only when user is logged on" (MT5's API needs an
  interactive desktop session)

**`order_notifications.py`** — continuous, so trigger differs:
- Trigger: "At log on" instead of a daily time
- Settings tab: uncheck "Stop the task if it runs longer than..."
- Settings tab: check "If the task is already running, do not start a new
  instance"
- Same "Run only when user is logged on" requirement as above

## Logs

Both scripts write their own log file next to the script
(`run_log.txt` and `order_notify_log.txt`) since Task Scheduler doesn't
show console output. Check these first if a message doesn't arrive when
expected.

## Notes

- Drawdown parameters (`INITIAL_SIZE`, `DAILY_LIMIT_PCT`, `TOTAL_LIMIT_PCT`)
  are currently duplicated between `balance_update.py` and
  `order_notifications.py` — keep them in sync if your prop firm's limits
  change.
- Files like `fp_acc_tracker.json`, `order_notify_state.json`, and the log
  files are runtime-generated and excluded from version control.