import os
import json
import logging
from datetime import datetime
import requests
import MetaTrader5 as mt5
from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

# --- Logging setup: writes to a file since Task Scheduler has no console ---
LOG_PATH = os.path.join(BASE_DIR, "run_log.txt")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

def log_and_print(msg, level="info"):
    print(msg)
    getattr(logging, level)(msg)


TELEGRAM_BOT_TOKEN = os.getenv("BALANCE_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHANNEL_CHAT_ID")

FP_LOGIN = int(os.getenv("FP_LOGIN"))
FP_PASS = os.getenv("FP_PASSWORD")
FP_SERVER = os.getenv("FP_SERVER")

MVN_LOGIN = int(os.getenv("MAVEN_LOGIN"))
MVN_PASS = os.getenv("MAVEN_PASSWORD")
MVN_SERVER = os.getenv("MAVEN_SERVER")

MT5_ACCOUNTS = [
    {
        "name": "FundingPips Account",
        "login": FP_LOGIN,
        "password": FP_PASS,
        "server": FP_SERVER,
        "target_goal": 2700.00,
        "initial_size": 2500.00,
        "daily_limit_pct": 5.0,
        "total_limit_pct": 10.0,
        "tracker_file": "fp_acc_tracker.json"
    },
    # {
    #     "name": "Maven Trading Account",
    #     "login": MVN_LOGIN,
    #     "password": MVN_PASS,
    #     "server": MVN_SERVER,
    #     "target_goal": 20800.00,
    #     "initial_size": 20000.00,
    #     "daily_limit_pct": 0.0,
    #     "total_limit_pct": 10.0,
    #     "tracker_file": "maven_acc_tracker.json"
    # }
]


def get_daily_starting_balance(current_balance, tracker_file):
    today_str = datetime.now().strftime("%Y-%m-%d")

    # FIX: use the absolute path so this doesn't depend on the process's
    # current working directory (Task Scheduler's default cwd is System32).
    tracker_path = os.path.join(BASE_DIR, tracker_file)

    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r") as f:
                data = json.load(f)
                if data.get("date") == today_str:
                    return data["starting_balance"]
        except Exception as e:
            logging.warning(f"Tracker file read failed, resetting: {e}")

    new_data = {
        "date": today_str,
        "starting_balance": current_balance
    }
    with open(tracker_path, "w") as f:
        json.dump(new_data, f)

    return current_balance


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            log_and_print("✅ Update sent to Telegram successfully!")
        else:
            log_and_print(f"❌ Failed to send message: {response.text}", level="error")
    except Exception as e:
        log_and_print(f"❌ Telegram API Error: {e}", level="error")


def main():
    logging.info("=" * 40)
    logging.info("Script run started")

    if not mt5.initialize():
        log_and_print(f"❌ MT5 initialization failed. Error code: {mt5.last_error()}", level="error")
        return

    logging.info("MT5 initialized successfully")

    account_blocks = []

    for acc in MT5_ACCOUNTS:
        log_and_print(f"Processing: {acc['name']}...")

        authorized = mt5.login(acc["login"], password=acc["password"], server=acc["server"])
        if not authorized:
            log_and_print(f"❌ Failed to authorize {acc['name']}. Code: {mt5.last_error()}", level="error")
            continue

        account_info = mt5.account_info()
        if account_info is None:
            log_and_print(f"❌ Failed to get info for {acc['name']}", level="error")
            continue

        current_balance = account_info.balance
        current_equity = account_info.equity

        daily_start_balance = get_daily_starting_balance(current_balance, acc["tracker_file"])

        deficit = max(0.0, acc["target_goal"] - current_balance)

        # Daily loss allowance (not the remaining room — the limit itself)
        daily_limit_amount = daily_start_balance * (acc["daily_limit_pct"] / 100)

        # Total drawdown floor: the balance level that represents the max total loss
        total_allowed_loss = acc["initial_size"] * (acc["total_limit_pct"] / 100)
        max_dd_floor = acc["initial_size"] - total_allowed_loss

        short_name = acc["name"].replace(" Account", "").upper()

        block = (
            f"💳 {short_name}\n"
            f"💰 Balance : `${current_balance:,.2f}`\n"
            f"📉 Daily limit : `-${daily_limit_amount:,.0f}`\n"
            f"📉 Max DD floor : `${max_dd_floor:,.0f}`\n"
            f"🎯 Profit target : `${acc['target_goal']:,.0f}`\n"
            f"🧩 Deficit : ${deficit:,.0f}"
        )
        account_blocks.append(block)

    if account_blocks:
        # Monday (weekday() == 0) gets the "New Trading Week" header;
        # every other day gets a plain daily update header.
        if datetime.now().weekday() == 0:
            header = "🌅 New Trading Week - ACCOUNTS UPDATE"
        else:
            header = "📅 Daily Accounts Update"

        message = (
            f"{header}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            + "\n\n".join(account_blocks)
        )
        send_telegram_message(message)
    else:
        log_and_print("⚠️ No account data collected — nothing sent to Telegram.", level="warning")

    mt5.shutdown()
    logging.info("Script run finished")


if __name__ == "__main__":
    main()