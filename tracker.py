"""
Celo Dev Wallet Tracker
========================
Track saldo USDT & USDC developer di jaringan Celo.
1 pesan Telegram yang selalu di-update.
Alert singkat kalau saldo rendah/habis.

Cara pakai:
    pip install -r requirements.txt
    python tracker.py
"""

import time
import json
import os
import requests
from datetime import datetime
from web3 import Web3

# ============================================================
# TELEGRAM CONFIG
# ============================================================
BOT_TOKEN = "8719727830:AAHjJkNfDTtLrqTkrMNZBWmF6nqKNzJrNyU"
CHAT_ID = "6293608654"

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
    },
    {
        "name": "Dev Amerika 🇺🇸",
        "address": "0x74667d9eDD871150cE38EBC26355758ba31F44B5",
        "tokens": ["USDC"],
        "alert_low": 150,
        "alert_empty": 0,
    },
    {
        "name": "Deposit Dev 🏦",
        "address": "0xCb205D7ca9840393f43941dDEAc6a7bF8deD4c5a",
        "tokens": ["USDC", "USDT"],
        "alert_low": 500,
        "alert_empty": 50,
    },
]

CHECK_INTERVAL = 3

# ============================================================
# GLOBALS
# ============================================================
w3 = Web3(Web3.HTTPProvider(CELO_RPC))
last_balances = {}
alert_sent = {}
last_message_id = None  # ID pesan terakhir di Telegram (buat dihapus)
LOG_FILE = "balance_log.json"


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
# TELEGRAM
# ============================================================
def send_telegram(message):
    """Kirim pesan baru, return message_id."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return data["result"]["message_id"]
        else:
            print(f"  [!] Telegram error: {data}")
    except Exception as e:
        print(f"  [!] Telegram failed: {e}")
    return None


def delete_telegram(message_id):
    """Hapus pesan lama."""
    if not message_id:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "message_id": message_id,
        }, timeout=10)
    except Exception:
        pass


def send_alert(message):
    """Kirim alert terpisah (gak dihapus)."""
    send_telegram(message)


# ============================================================
# FORMAT PESAN UTAMA
# ============================================================
def format_usd(val):
    if val is None:
        return "N/A"
    return f"${val:,.2f}"


def build_main_message(all_balances):
    """Buat pesan utama dengan saldo semua wallet."""
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
    """Cek semua wallet, return (all_balances, has_change, alerts)."""
    all_balances = {}
    has_change = False
    alerts = []

    for w in WALLETS:
        addr = w["address"]
        current = get_wallet_balances(w)
        all_balances[addr] = current
        prev = last_balances.get(addr, {})

        for token in w["tokens"]:
            cur_val = current.get(token, 0) or 0
            prev_val = prev.get(token, 0) or 0
            diff = cur_val - prev_val
            alert_key = f"{addr}_{token}"

            # Cek perubahan saldo
            if prev and abs(diff) >= 0.01:
                has_change = True

                # Reset alert kalau saldo naik
                if diff > 0 and alert_key in alert_sent:
                    del alert_sent[alert_key]

            # Cek alert saldo habis (Deposit Dev < $50)
            if w["alert_empty"] > 0 and cur_val < w["alert_empty"]:
                if alert_sent.get(alert_key) != "empty":
                    short_name = w["name"].split(" ")[0] + " " + w["name"].split(" ")[1] if len(w["name"].split(" ")) > 1 else w["name"]
                    alerts.append(
                        f"🚨 <b>{short_name} {token} saldo habis!</b>\n"
                        f"Sisa: <b>{format_usd(cur_val)}</b>"
                    )
                    alert_sent[alert_key] = "empty"

            # Cek alert saldo rendah
            elif w["alert_low"] > 0 and cur_val < w["alert_low"]:
                if alert_sent.get(alert_key) != "low":
                    short_name = w["name"].split("(")[0].strip() if "(" in w["name"] else w["name"]
                    alerts.append(
                        f"⚠️ <b>{short_name} {token} low balance!</b>\n"
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
    # Keep max 500 entries
    if len(logs) > 500:
        logs = logs[-500:]
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)


# ============================================================
# MAIN
# ============================================================
def main():
    global last_message_id

    print("=" * 55)
    print("  Celo Dev Wallet Tracker")
    print("=" * 55)
    print()

    if not w3.is_connected():
        print("[!] Gagal connect ke Celo RPC!")
        return

    print(f"[OK] Connected ke Celo")
    print(f"[*] Tracking {len(WALLETS)} wallet(s)")
    print(f"[*] Interval: {CHECK_INTERVAL} detik")
    print()

    # ---- Startup: ambil saldo awal & kirim pesan pertama ----
    print("[*] Mengambil saldo awal...")
    for w in WALLETS:
        last_balances[w["address"]] = get_wallet_balances(w)

    msg = build_main_message(last_balances)
    last_message_id = send_telegram(msg)
    print("[OK] Pesan awal terkirim!")

    # Kirim alert awal kalau ada saldo rendah
    _, _, startup_alerts = check_all_wallets()
    for alert_msg in startup_alerts:
        send_alert(alert_msg)

    # Update last_balances setelah startup
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
                print(f"  [{now}] Balance changed! Updating Telegram...")

                # Hapus pesan lama
                delete_telegram(last_message_id)

                # Kirim pesan baru dengan saldo terbaru
                msg = build_main_message(all_balances)
                last_message_id = send_telegram(msg)

                # Log perubahan
                save_log({
                    "type": "change",
                    "balances": {a: b for a, b in all_balances.items()},
                    "waktu": datetime.now().isoformat(),
                })

                # Update last_balances
                for w in WALLETS:
                    last_balances[w["address"]] = all_balances[w["address"]]

            # Kirim alert (pesan terpisah, gak dihapus)
            for alert_msg in alerts:
                send_alert(alert_msg)
                now = datetime.now().strftime("%H:%M:%S")
                print(f"  [{now}] Alert sent!")

            # Heartbeat tiap ~1 menit
            cycle += 1
            if cycle % (60 // CHECK_INTERVAL) == 0:
                now = datetime.now().strftime("%H:%M:%S")
                print(f"  [{now}] ♥ Running... (cycle #{cycle})")

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n[STOP] Tracker dihentikan.")
        send_telegram("🔴 <b>Tracker Stopped</b>")


if __name__ == "__main__":
    main()
