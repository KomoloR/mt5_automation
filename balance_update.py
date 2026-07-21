import os
import json
from datetime import datetime
import requests
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv()


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
    
    
    if os.path.exists(tracker_file):
        try:
            with open(tracker_file, "r") as f:
                data = json.load(f)
                if data.get("date") == today_str:
                    return data["starting_balance"]
        except Exception:
            pass # Fallback to writing new data if file is corrupted

    # If file doesn't exist or it's a new day, write current balance as the starting point
    new_data = {
        "date": today_str,
        "starting_balance": current_balance
    }
    with open(tracker_file, "w") as f:
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
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("✅ Update sent to Telegram successfully!")
        else:
            print(f"❌ Failed to send message: {response.text}")
    except Exception as e:
        print(f"❌ Telegram API Error: {e}")

def main():
    
    if not mt5.initialize():
        print(f"❌ MT5 initialization failed. Error code: {mt5.last_error()}")
        return

    for acc in MT5_ACCOUNTS:
        print(f"Processing: {acc['name']}...")
        
        authorized = mt5.login(acc["login"], password=acc["password"], server=acc["server"])
        if not authorized:
            print(f"❌ Failed to authorize {acc['name']}. Code: {mt5.last_error()}")
            continue

        account_info = mt5.account_info()
        if account_info is None:
            print(f"❌ Failed to get info for {acc['name']}")
            continue

        current_balance = account_info.balance
        current_equity = account_info.equity
        
        daily_start_balance = get_daily_starting_balance(current_balance, acc["tracker_file"])

        deficit = max(0.0, acc["target_goal"] - current_balance)
        
        daily_allowed_loss = daily_start_balance * (acc["daily_limit_pct"] / 100)
        current_daily_loss = max(0.0, daily_start_balance - current_equity)
        daily_drawdown_remaining = max(0.0, daily_allowed_loss - current_daily_loss)

        total_allowed_loss = acc["initial_size"] * (acc["total_limit_pct"] / 100)
        current_total_loss = max(0.0, acc["initial_size"] - current_equity)
        total_drawdown_remaining = max(0.0, total_allowed_loss - current_total_loss)

        message = (
            f"📊 *Account Update: {acc['name']}*\n"
            f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"💰 *Current Balance:* ${current_balance:,.2f}\n"
            f"📈 *Current Equity:* ${current_equity:,.2f}\n\n"
            f"🎯 *Goal Deficit:* ${deficit:,.2f} remaining to hit ${acc['target_goal']:,.2f}\n\n"
            f"🛡️ *Daily Drawdown Status (Limit: {acc['daily_limit_pct']}%):*\n"
            f"  • Day Start Balance: ${daily_start_balance:,.2f}\n"
            f"  • Remaining Daily Loss Room: *${daily_drawdown_remaining:,.2f}*\n\n"
            f"🛑 *Total Drawdown Status (Limit: {acc['total_limit_pct']}%):*\n"
            f"  • Initial Balance: ${acc['initial_size']:,.2f}\n"
            f"  • Remaining Total Loss Room: *${total_drawdown_remaining:,.2f}*\n"
            f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯"
        )

        send_telegram_message(message)

    mt5.shutdown()

if __name__ == "__main__":
    main()
    
    
   

    
   