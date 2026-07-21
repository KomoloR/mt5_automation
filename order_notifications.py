"""
Continuously polls MT5 for:
  1. New pending orders placed  -> sends a Telegram message with entry/SL/TP
  2. Pending orders removed before being filled -> deletes that Telegram message
  3. Open positions closed via Take Profit -> sends a message with updated
     balance/equity
  4. Open positions closed via Stop Loss -> sends a message with updated
     balance, equity, daily drawdown remaining, and max drawdown remaining
    

This is NOT a Task Scheduler "run once daily" script - it runs continuously
in a loop with a short sleep, because MT5's API has no push/webhook
mechanism; polling is the only option."""

import os
import json
import time
import logging
from datetime import datetime

import requests
import MetaTrader5 as mt5
from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

LOG_PATH = os.path.join(BASE_DIR, "order_notify_log.txt")
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

# Which account this instance monitors. Since MT5's terminal/API only ever
# holds one login at a time, this script watches ONE account per run.
# Defaults to the FundingPips account - change to MVN_* to monitor that one
# instead (run a second instance of this script for the other account).
ACCOUNT_LOGIN = int(os.getenv("FP_LOGIN"))
ACCOUNT_PASSWORD = os.getenv("FP_PASSWORD")
ACCOUNT_SERVER = os.getenv("FP_SERVER")

# Same drawdown parameters as balance_update.py, used to compute the
# remaining daily/max drawdown room for the SL-hit message below. Keep
# these in sync with the corresponding entry in balance_update.py.
INITIAL_SIZE = 2500.00
DAILY_LIMIT_PCT = 5.0
TOTAL_LIMIT_PCT = 10.0
TRACKER_FILE = os.path.join(BASE_DIR, "fp_acc_tracker.json")

STATE_FILE = os.path.join(BASE_DIR, "order_notify_state.json")
POLL_INTERVAL_SECONDS = 5

ORDER_TYPE_MAP = {
    mt5.ORDER_TYPE_BUY: "BUY (MARKET)",
    mt5.ORDER_TYPE_SELL: "SELL (MARKET)",
    mt5.ORDER_TYPE_BUY_LIMIT: "BUY LIMIT",
    mt5.ORDER_TYPE_SELL_LIMIT: "SELL LIMIT",
    mt5.ORDER_TYPE_BUY_STOP: "BUY STOP",
    mt5.ORDER_TYPE_SELL_STOP: "SELL STOP",
    mt5.ORDER_TYPE_BUY_STOP_LIMIT: "BUY STOP LIMIT",
    mt5.ORDER_TYPE_SELL_STOP_LIMIT: "SELL STOP LIMIT",
}


# --- State persistence ------------------------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            log_and_print(f"⚠️ Could not read state file, starting fresh: {e}", level="warning")
    return {"orders": {}, "positions": {}, "seeded": False}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# --- Drawdown helper (mirrors balance_update.py) ----------------------------

def get_daily_starting_balance(current_balance):
    today_str = datetime.now().strftime("%Y-%m-%d")

    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE, "r") as f:
                data = json.load(f)
                if data.get("date") == today_str:
                    return data["starting_balance"]
        except Exception as e:
            logging.warning(f"Tracker file read failed, resetting: {e}")

    new_data = {"date": today_str, "starting_balance": current_balance}
    with open(TRACKER_FILE, "w") as f:
        json.dump(new_data, f)

    return current_balance


# --- Telegram helpers --------------------------------------------------------

def send_message(text):
    """Sends a message, returns the Telegram message_id (or None on failure)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            msg_id = resp.json()["result"]["message_id"]
            log_and_print(f"✅ Telegram message sent (id={msg_id})")
            return msg_id
        else:
            log_and_print(f"❌ Telegram send failed: {resp.text}", level="error")
            return None
    except Exception as e:
        log_and_print(f"❌ Telegram send error: {e}", level="error")
        return None


def delete_message(message_id):
    if message_id is None:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id}
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            log_and_print(f"🗑️ Telegram message deleted (id={message_id})")
        else:
            log_and_print(f"❌ Telegram delete failed: {resp.text}", level="error")
    except Exception as e:
        log_and_print(f"❌ Telegram delete error: {e}", level="error")


# --- Message formatting -------------------------------------------------------

def format_order_message(order):
    type_str = ORDER_TYPE_MAP.get(order.type, f"TYPE_{order.type}")
    return (
        f"📥 *New Order Placed*\n"
        f"💱 {order.symbol} — {type_str}\n"
        f"🎯 Entry : `{order.price_open}`\n"
        f"🛑 SL : `{order.sl}`\n"
        f"🏁 TP : `{order.tp}`\n"
        f"📦 Volume : `{order.volume_initial}`"
    )


def format_tp_message(symbol, balance, equity):
    return (
        f"✅ *Take Profit Hit!*\n"
        f"💱 {symbol}\n"
        f"💰 Balance : `${balance:,.2f}`\n"
        f"📈 Equity : `${equity:,.2f}`"
    )


def format_sl_message(symbol, balance, equity, daily_dd_remaining, max_dd_remaining):
    return (
        f"🛑 *Stop Loss Hit*\n"
        f"💱 {symbol}\n"
        f"💰 Balance : `${balance:,.2f}`\n"
        f"📈 Equity : `${equity:,.2f}`\n"
        f"📉 Daily drawdown remaining : `${daily_dd_remaining:,.2f}`\n"
        f"🛑 Max drawdown remaining : `${max_dd_remaining:,.2f}`"
    )


# --- Polling logic -------------------------------------------------------------

def poll_orders(state):
    current = {str(o.ticket): o for o in (mt5.orders_get() or [])}
    known = state["orders"]

    # New pending orders
    for ticket_str, order in current.items():
        if ticket_str not in known:
            if not state["seeded"]:
                # First-ever run: just record existing orders, don't spam
                # notifications for things that were already pending.
                known[ticket_str] = {"message_id": None}
                continue
            msg_id = send_message(format_order_message(order))
            known[ticket_str] = {"message_id": msg_id}
            log_and_print(f"New pending order detected: {ticket_str} ({order.symbol})")

    # Orders that vanished since last poll
    for ticket_str in list(known.keys()):
        if ticket_str not in current:
            info = known.pop(ticket_str)
            hist = mt5.history_orders_get(ticket=int(ticket_str))
            final_state = hist[0].state if hist else None

            if final_state == mt5.ORDER_STATE_FILLED:
                # Order got filled -> it becomes a position; poll_positions()
                # will pick that up separately. Leave the "order placed"
                # message in the channel as a record.
                log_and_print(f"Order {ticket_str} was filled.")
            elif final_state in (mt5.ORDER_STATE_CANCELED, mt5.ORDER_STATE_EXPIRED, mt5.ORDER_STATE_REJECTED):
                log_and_print(f"Order {ticket_str} was cancelled/expired/rejected — deleting message.")
                delete_message(info.get("message_id"))
            else:
                # Unknown reason it disappeared (e.g. history not available
                # yet) - err on the side of deleting the notification.
                log_and_print(f"Order {ticket_str} disappeared with unknown state ({final_state}).", level="warning")
                delete_message(info.get("message_id"))


def poll_positions(state):
    current = {str(p.ticket): p for p in (mt5.positions_get() or [])}
    known = state["positions"]

    for ticket_str, pos in current.items():
        if ticket_str not in known:
            known[ticket_str] = {"symbol": pos.symbol}

    for ticket_str in list(known.keys()):
        if ticket_str not in current:
            info = known.pop(ticket_str)
            deals = mt5.history_deals_get(position=int(ticket_str)) or []
            closing_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
            reason = closing_deals[-1].reason if closing_deals else None

            if reason == mt5.DEAL_REASON_TP:
                account_info = mt5.account_info()
                if account_info is not None:
                    log_and_print(f"Position {ticket_str} closed via TP.")
                    send_message(format_tp_message(info["symbol"], account_info.balance, account_info.equity))
            elif reason == mt5.DEAL_REASON_SL:
                account_info = mt5.account_info()
                if account_info is not None:
                    log_and_print(f"Position {ticket_str} closed via SL.")

                    balance = account_info.balance
                    equity = account_info.equity

                    daily_start_balance = get_daily_starting_balance(balance)
                    daily_allowed_loss = daily_start_balance * (DAILY_LIMIT_PCT / 100)
                    current_daily_loss = max(0.0, daily_start_balance - equity)
                    daily_dd_remaining = max(0.0, daily_allowed_loss - current_daily_loss)

                    total_allowed_loss = INITIAL_SIZE * (TOTAL_LIMIT_PCT / 100)
                    current_total_loss = max(0.0, INITIAL_SIZE - equity)
                    max_dd_remaining = max(0.0, total_allowed_loss - current_total_loss)

                    send_message(format_sl_message(
                        info["symbol"], balance, equity, daily_dd_remaining, max_dd_remaining
                    ))
            else:
                log_and_print(f"Position {ticket_str} closed (reason={reason}) — not TP/SL, no message sent.")


# --- Main loop -------------------------------------------------------------

def main():
    logging.info("=" * 40)
    logging.info("Order notification watcher starting")

    if not mt5.initialize():
        log_and_print(f"❌ MT5 initialization failed: {mt5.last_error()}", level="error")
        return

    if not mt5.login(ACCOUNT_LOGIN, password=ACCOUNT_PASSWORD, server=ACCOUNT_SERVER):
        log_and_print(f"❌ MT5 login failed: {mt5.last_error()}", level="error")
        mt5.shutdown()
        return

    log_and_print("✅ Connected to MT5. Watching for order/position changes...")

    state = load_state()

    try:
        while True:
            try:
                poll_orders(state)
                poll_positions(state)
                state["seeded"] = True
                save_state(state)
            except Exception as e:
                log_and_print(f"❌ Poll cycle error: {e}", level="error")

            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        log_and_print("Stopped by user (Ctrl+C).")
    finally:
        save_state(state)
        mt5.shutdown()
        logging.info("Order notification watcher stopped")


if __name__ == "__main__":
    main()