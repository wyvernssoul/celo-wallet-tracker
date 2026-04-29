"""
Celo Dev Wallet Tracker (Multi-User)
======================================
Track saldo USDT & USDC developer di jaringan Celo.
Siapa aja yang klik /start di bot, otomatis dapet notif.

Cara pakai:
    pip install -r requirements.txt
    python tracker.py
"""

import time
import json
import os
import requests
import threading
from datetime import datetime
from web3 import Web3

# ============================================================
# TELEGRAM CONFIG
# ============================================================
BOT_TOKEN = "8719727830:AAHjJkNfDTtLrqTkrMNZBWmF6nqKNzJrNyU"
ADMIN_CHAT_ID = "6293608654"  # Chat ID kamu (owner)

# File simpan semua user yang /start
USERS_FILE = "users.json"

# ============================================================
# CELO RPC & TOKEN CONTRACTS
# ============================================================
CELO_RPC = "https://forno.celo.org"

USDT_ADDR = Web3.to_checksum_address("0x48065fbBE25f71C9282ddf5e1cD6D6A887483D5e")
USDC_ADDR = Web3.to_checksum_address("0xcebA9300f2b948710d2653dD7B07f33A8B32118C")

ERC20_ABI = json.loads(
    '[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],'
    '"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],'
    '"type":"function"},{"constant":true,"inputs":[],"name":"decimals",'
    '"outputs":[{"name":"","type":"uint8"}],"type":"function"}]'
)

# ============================================================
# WALLET CONFIG
# ============================================================
WALLETS = [
    {
        "name": "Dev Eropa 🇪🇺",
        "address": "0x65Cc602e616CA786bDB4Bab00A6272060f0082fB",
        "tokens": ["USDC", "USDT"],
        "alert_low": 150,
        "alert_empty": 0,
        "min_notif": 1000,      # Notif kalau perubahan >= $1000
    },
    {
        "name": "Dev Amerika 🇺🇸",
        "address": "0x74667d9eDD871150cE38EBC26355758ba31F44B5",
        "tokens": ["USDC"],
        "alert_low": 150,
        "alert_empty": 0,
        "min_notif": 1000,
    },
    {
        "name": "Deposit Dev 🏦",
        "address": "0xCb205D7ca9840393f43941dDEAc6a7bF8deD4c5a",
        "tokens": ["USDC", "USDT"],
        "alert_low": 500,
        "alert_empty": 50,
        "min_notif": 1000,
    },
]

CHECK_INTERVAL = 3

# ============================================================
# GLOBALS
# ============================================================
w3 = Web3(Web3.HTTPProvider(CELO_RPC))
last_balances = {}
alert_sent = {}
last_message_ids = {}   # {chat_id: message_id} — per user
LOG_FILE = "balance_log.json"


# ============================================================
# USER MANAGEMENT
# ============================================================
def load_users():
    """Load semua chat_id user yang pernah /start."""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Default: admin aja
    return [ADMIN_CHAT_ID]


def save_users(users):
    """Simpan list user."""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f)


def add_user(chat_id):
    """Tambah user baru."""
    users = load_users()
    chat_id_str = str(chat_id)
    if chat_id_str not in users:
        users.append(chat_id_str)
        save_users(users)
        print(f"  [+] New user: {chat_id_str}")
        return True
    return False


# ============================================================
# TELEGRAM POLLING (listen /start dari user baru)
# ============================================================
def poll_telegram_updates():
    """Background thread: listen pesan masuk dari Telegram."""
    last_update_id = 0
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

    while True:
        try:
            resp = requests.get(url, params={
                "offset": last_update_id + 1,
                "timeout": 30,
            }, timeout=35)
            data = resp.json()

            if data.get("ok"):
                for update in data.get("result", []):
                    last_update_id = update["update_id"]
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    first_name = msg.get("from", {}).get("first_name", "")

                    if not chat_id:
                        continue

                    if text == "/start":
                        is_new = add_user(chat_id)

                        # Kirim saldo saat ini ke user baru
                        if last_balances:
                            balance_msg = build_main_message(last_balances)
                            mid = send_to_user(chat_id, balance_msg)
                            if mid:
                                last_message_ids[chat_id] = mid


                    elif text == "/status":
                        # Kirim saldo saat ini
                        if last_balances:
                            balance_msg = build_main_message(last_balances)
                            send_to_user(chat_id, balance_msg)

        except Exception as e:
            print(f"  [!] Polling error: {e}")
            time.sleep(5)


# ============================================================
# BLOCKCHAIN
# ============================================================
def get_balance(wallet_addr, token_addr):
    try:
        contract = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
        raw = contract.functions.balanceOf(
            Web3.to_checksum_address(wallet_addr)
        ).call()
        decimals = contract.functions.decimals().call()
        return round(raw / (10 ** decimals), 2)
    except Exception as e:
        print(f"  [!] Error: {e}")
        return None


def get_wallet_balances(wallet_cfg):
    result = {}
    addr = wallet_cfg["address"]
    for token in wallet_cfg["tokens"]:
        if token == "USDC":
            result["USDC"] = get_balance(addr, USDC_ADDR)
        elif token == "USDT":
            result["USDT"] = get_balance(addr, USDT_ADDR)
    return result


# ============================================================
# TELEGRAM SEND
# ============================================================
def send_to_user(chat_id, message):
    """Kirim pesan ke 1 user, return message_id."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return data["result"]["message_id"]
        else:
            print(f"  [!] Telegram error ({chat_id}): {data.get('description','')}")
    except Exception as e:
        print(f"  [!] Telegram failed ({chat_id}): {e}")
    return None


def delete_from_user(chat_id, message_id):
    """Hapus pesan dari 1 user."""
    if not message_id:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
    try:
        requests.post(url, json={
            "chat_id": chat_id,
            "message_id": message_id,
        }, timeout=10)
    except Exception:
        pass


def send_to_all(message):
    """Kirim pesan ke semua user, return {chat_id: message_id}."""
    users = load_users()
    result = {}
    for chat_id in users:
        mid = send_to_user(chat_id, message)
        if mid:
            result[chat_id] = mid
    return result


def delete_all_old_messages():
    """Hapus pesan lama dari semua user."""
    for chat_id, mid in last_message_ids.items():
        delete_from_user(chat_id, mid)


def send_alert_to_all(message):
    """Kirim alert ke semua user (gak dihapus)."""
    send_to_all(message)


# ============================================================
# FORMAT
# ============================================================
def format_usd(val):
    if val is None:
        return "N/A"
    return f"${val:,.2f}"


def build_main_message(all_balances):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    msg = f"🟢 <b>Wallet Tracker</b>\n"
    msg += f"⏰ {now}\n"
    msg += f"{'─' * 30}\n\n"

    for w in WALLETS:
        addr = w["address"]
        balances = all_balances.get(addr, {})

        msg += f"<b>{w['name']}</b>\n"
        msg += f"📍 <code>{addr}</code>\n"

        for token in w["tokens"]:
            val = balances.get(token, 0) or 0
            msg += f"  💵 {token}: <b>{format_usd(val)}</b>\n"

        total = sum(balances.get(t, 0) or 0 for t in w["tokens"])
        msg += f"  📊 Total: <b>{format_usd(total)}</b>\n\n"

    return msg


# ============================================================
# CEK & NOTIF
# ============================================================
def check_all_wallets():
    all_balances = {}
    has_change = False
    alerts = []

    for w in WALLETS:
        addr = w["address"]
        current = get_wallet_balances(w)
        all_balances[addr] = current
        prev = last_balances.get(addr, {})

        min_notif = w.get("min_notif", 0)

        for token in w["tokens"]:
            cur_val = current.get(token, 0) or 0
            prev_val = prev.get(token, 0) or 0
            diff = cur_val - prev_val
            alert_key = f"{addr}_{token}"

            # Cek perubahan saldo — cuma notif kalau >= min_notif
            if prev and abs(diff) >= max(min_notif, 0.01):
                has_change = True
                if diff > 0 and alert_key in alert_sent:
                    del alert_sent[alert_key]

            # Alert saldo habis (tetap jalan, gak kena min_notif)
            if w["alert_empty"] > 0 and cur_val < w["alert_empty"]:
                if alert_sent.get(alert_key) != "empty":
                    alerts.append(
                        f"🚨 <b>{w['name']} {token} saldo habis!</b>\n"
                        f"Sisa: <b>{format_usd(cur_val)}</b>"
                    )
                    alert_sent[alert_key] = "empty"

            # Alert saldo rendah (tetap jalan, gak kena min_notif)
            elif w["alert_low"] > 0 and cur_val < w["alert_low"]:
                if alert_sent.get(alert_key) != "low":
                    alerts.append(
                        f"⚠️ <b>{w['name']} {token} low balance!</b>\n"
                        f"Sisa: <b>{format_usd(cur_val)}</b>"
                    )
                    alert_sent[alert_key] = "low"

    return all_balances, has_change, alerts


def save_log(entry):
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []
    logs.append(entry)
    if len(logs) > 500:
        logs = logs[-500:]
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)


# ============================================================
# MAIN
# ============================================================
def main():
    global last_message_ids

    print("=" * 55)
    print("  Celo Dev Wallet Tracker (Multi-User)")
    print("=" * 55)
    print()

    if not w3.is_connected():
        print("[!] Gagal connect ke Celo RPC!")
        return

    users = load_users()
    print(f"[OK] Connected ke Celo")
    print(f"[*] Tracking {len(WALLETS)} wallet(s)")
    print(f"[*] Users: {len(users)}")
    print(f"[*] Interval: {CHECK_INTERVAL} detik")
    print()

    # Start background thread: listen /start dari user baru
    t = threading.Thread(target=poll_telegram_updates, daemon=True)
    t.start()
    print("[OK] Telegram listener started")

    # Startup: ambil saldo awal & kirim ke semua user
    print("[*] Mengambil saldo awal...")
    for w in WALLETS:
        last_balances[w["address"]] = get_wallet_balances(w)

    msg = build_main_message(last_balances)
    last_message_ids = send_to_all(msg)
    print(f"[OK] Pesan awal terkirim ke {len(last_message_ids)} user!")

    # Alert awal
    _, _, startup_alerts = check_all_wallets()
    for alert_msg in startup_alerts:
        send_alert_to_all(alert_msg)

    for w in WALLETS:
        last_balances[w["address"]] = get_wallet_balances(w)

    print()
    print("[*] Monitoring... (Ctrl+C untuk stop)")
    print()

    cycle = 0
    try:
        while True:
            all_balances, has_change, alerts = check_all_wallets()

            if has_change:
                now = datetime.now().strftime("%H:%M:%S")
                print(f"  [{now}] Balance changed! Updating all users...")

                # Hapus pesan lama dari semua user
                delete_all_old_messages()

                # Kirim pesan baru ke semua user
                msg = build_main_message(all_balances)
                last_message_ids = send_to_all(msg)

                save_log({
                    "type": "change",
                    "balances": {a: b for a, b in all_balances.items()},
                    "waktu": datetime.now().isoformat(),
                })

                for w in WALLETS:
                    last_balances[w["address"]] = all_balances[w["address"]]

            # Alert ke semua user
            for alert_msg in alerts:
                send_alert_to_all(alert_msg)
                now = datetime.now().strftime("%H:%M:%S")
                print(f"  [{now}] Alert sent to all users!")

            cycle += 1
            if cycle % (60 // CHECK_INTERVAL) == 0:
                now = datetime.now().strftime("%H:%M:%S")
                users = load_users()
                print(f"  [{now}] ♥ Running... (cycle #{cycle}, {len(users)} users)")

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n[STOP] Tracker dihentikan.")
        send_to_all("🔴 <b>Tracker Stopped</b>")


if __name__ == "__main__":
    main()
