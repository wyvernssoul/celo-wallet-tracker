"""
Celo Dev Wallet Tracker
========================
Track saldo USDT & USDC developer di jaringan Celo.
Kirim notifikasi ke Telegram.

3 Wallet:
  1. Dev Eropa   — USDC + USDT, alert < $150
  2. Dev Amerika — USDC only, alert < $150
  3. Deposit Dev — USDC + USDT, alert < $500, notif habis < $50

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
CHAT_ID = "8719727830"

# ============================================================
# CELO RPC & TOKEN CONTRACTS
# ============================================================
CELO_RPC = "https://forno.celo.org"

# USDT di Celo
USDT_ADDR = Web3.to_checksum_address("0x48065fbBE25f71C9282ddf5e1cD6D6A887483D5e")
# USDC di Celo
USDC_ADDR = Web3.to_checksum_address("0xcebA9300f2b948710d2653dD7B07f33A8B32118C")

# ERC20 ABI minimal
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
        "alert_low": 150,       # Alert kalau saldo < $150
        "alert_empty": 0,       # Gak pakai alert habis
    },
    {
        "name": "Dev Amerika 🇺🇸",
        "address": "0x74667d9eDD871150cE38EBC26355758ba31F44B5",
        "tokens": ["USDC"],     # Cuma USDC
        "alert_low": 150,
        "alert_empty": 0,
    },
    {
        "name": "Deposit Dev 🏦",
        "address": "0xCb205D7ca9840393f43941dDEAc6a7bF8deD4c5a",
        "tokens": ["USDC", "USDT"],
        "alert_low": 500,       # Alert kalau < $500
        "alert_empty": 50,      # Notif "saldo habis" kalau < $50
    },
]

# Interval cek (detik)
CHECK_INTERVAL = 3

# ============================================================
# GLOBALS
# ============================================================
w3 = Web3(Web3.HTTPProvider(CELO_RPC))
last_balances = {}      # {address: {"USDC": x, "USDT": y}}
alert_sent = {}         # {address_token: "low"/"empty"} biar gak spam
LOG_FILE = "balance_log.json"


# ============================================================
# FUNCTIONS
# ============================================================
def get_balance(wallet_addr, token_addr):
    """Ambil saldo token dari wallet."""
    try:
        contract = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
        raw = contract.functions.balanceOf(
            Web3.to_checksum_address(wallet_addr)
        ).call()
        decimals = contract.functions.decimals().call()
        return round(raw / (10 ** decimals), 4)
    except Exception as e:
        print(f"  [!] Error: {e}")
        return None


def get_wallet_balances(wallet_cfg):
    """Ambil semua saldo token dari 1 wallet."""
    result = {}
    addr = wallet_cfg["address"]
    for token in wallet_cfg["tokens"]:
        if token == "USDC":
            result["USDC"] = get_balance(addr, USDC_ADDR)
        elif token == "USDT":
            result["USDT"] = get_balance(addr, USDT_ADDR)
    return result


def send_telegram(message):
    """Kirim pesan ke Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        if resp.status_code != 200:
            print(f"  [!] Telegram error: {resp.text}")
    except Exception as e:
        print(f"  [!] Telegram failed: {e}")


def short_addr(addr):
    return f"{addr[:6]}...{addr[-4:]}"


def format_usd(val):
    if val is None:
        return "N/A"
    return f"${val:,.2f}"


def send_startup_report():
    """Kirim laporan saldo awal saat bot pertama kali jalan."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    msg = f"🟢 <b>Tracker Started</b>\n"
    msg += f"⏰ {now}\n"
    msg += f"{'─' * 30}\n\n"

    for w in WALLETS:
        balances = get_wallet_balances(w)
        last_balances[w["address"]] = balances

        msg += f"<b>{w['name']}</b>\n"
        msg += f"📍 <code>{w['address']}</code>\n"

        for token in w["tokens"]:
            val = balances.get(token, 0) or 0
            msg += f"  💵 {token}: <b>{format_usd(val)}</b>\n"

        # Total
        total = sum(balances.get(t, 0) or 0 for t in w["tokens"])
        msg += f"  📊 Total: <b>{format_usd(total)}</b>\n\n"

    send_telegram(msg)
    print("[OK] Startup report sent to Telegram!")


def check_wallet(wallet_cfg):
    """Cek 1 wallet, bandingkan, kirim notif kalau perlu."""
    addr = wallet_cfg["address"]
    name = wallet_cfg["name"]
    alert_low = wallet_cfg["alert_low"]
    alert_empty = wallet_cfg["alert_empty"]
    now = datetime.now().strftime("%H:%M:%S")

    # Ambil saldo sekarang
    current = get_wallet_balances(wallet_cfg)
    prev = last_balances.get(addr, {})

    # Kalau belum ada data sebelumnya, simpan aja
    if not prev:
        last_balances[addr] = current
        return

    changes = []
    alerts = []

    for token in wallet_cfg["tokens"]:
        cur_val = current.get(token, 0) or 0
        prev_val = prev.get(token, 0) or 0
        diff = cur_val - prev_val
        alert_key = f"{addr}_{token}"

        # ---- CEK PERUBAHAN SALDO ----
        if abs(diff) >= 0.01:
            direction = "📈 Deposit" if diff > 0 else "📉 Turun"
            sign = "+" if diff > 0 else ""
            changes.append({
                "token": token,
                "prev": prev_val,
                "now": cur_val,
                "diff": diff,
                "direction": direction,
                "sign": sign,
            })

            # Reset alert kalau saldo naik lagi
            if diff > 0 and alert_key in alert_sent:
                del alert_sent[alert_key]

        # ---- CEK ALERT SALDO RENDAH ----
        if alert_empty > 0 and cur_val < alert_empty:
            # SALDO HAMPIR HABIS
            if alert_sent.get(alert_key) != "empty":
                alerts.append({
                    "type": "empty",
                    "token": token,
                    "balance": cur_val,
                })
                alert_sent[alert_key] = "empty"

        elif alert_low > 0 and cur_val < alert_low:
            # SALDO RENDAH
            if alert_sent.get(alert_key) != "low":
                alerts.append({
                    "type": "low",
                    "token": token,
                    "balance": cur_val,
                    "limit": alert_low,
                })
                alert_sent[alert_key] = "low"

    # ---- KIRIM NOTIF PERUBAHAN ----
    if changes:
        msg = f"🔔 <b>Balance Changed!</b>\n"
        msg += f"<b>{name}</b>\n"
        msg += f"📍 <code>{addr}</code>\n\n"

        for c in changes:
            msg += (
                f"{c['direction']}\n"
                f"  {c['token']}: {format_usd(c['prev'])} → <b>{format_usd(c['now'])}</b> "
                f"({c['sign']}{format_usd(abs(c['diff']))})\n\n"
            )

        # Tampilkan semua saldo saat ini
        msg += f"📊 <b>Saldo saat ini:</b>\n"
        for token in wallet_cfg["tokens"]:
            val = current.get(token, 0) or 0
            msg += f"  💵 {token}: <b>{format_usd(val)}</b>\n"

        msg += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        send_telegram(msg)

        # Print di terminal
        print(f"  [{now}] {name} | CHANGED!")
        for c in changes:
            print(f"    {c['direction']} {c['token']}: {format_usd(c['prev'])} → {format_usd(c['now'])}")

        # Log
        save_log({
            "wallet": name,
            "address": addr,
            "changes": [{"token": c["token"], "from": c["prev"], "to": c["now"], "diff": c["diff"]} for c in changes],
            "waktu": datetime.now().isoformat(),
        })

    # ---- KIRIM ALERT ----
    for a in alerts:
        if a["type"] == "empty":
            msg = (
                f"🚨🚨🚨 <b>SALDO HAMPIR HABIS!</b> 🚨🚨🚨\n\n"
                f"<b>{name}</b>\n"
                f"📍 <code>{addr}</code>\n\n"
                f"💵 {a['token']}: <b>{format_usd(a['balance'])}</b>\n\n"
                f"⚠️ Saldo {a['token']} kurang dari ${alert_empty}!\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        else:
            msg = (
                f"⚠️ <b>PERINGATAN: Saldo Rendah!</b>\n\n"
                f"<b>{name}</b>\n"
                f"📍 <code>{addr}</code>\n\n"
                f"💵 {a['token']}: <b>{format_usd(a['balance'])}</b>\n\n"
                f"📉 Saldo {a['token']} di bawah ${a['limit']}!\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        send_telegram(msg)
        print(f"  [{now}] {name} | ALERT: {a['type']} {a['token']} = {format_usd(a['balance'])}")

    # Update last balance
    last_balances[addr] = current


def save_log(entry):
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []
    logs.append(entry)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)


# ============================================================
# MAIN
# ============================================================
def main():
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

    for w in WALLETS:
        tokens = " + ".join(w["tokens"])
        print(f"  {w['name']}")
        print(f"    📍 {w['address']}")
        print(f"    💵 {tokens}")
        if w["alert_low"]:
            print(f"    ⚠️  Alert < ${w['alert_low']}")
        if w["alert_empty"]:
            print(f"    🚨 Habis < ${w['alert_empty']}")
        print()

    # Kirim laporan saldo awal
    print("[*] Mengambil saldo awal...")
    send_startup_report()

    print()
    print("[*] Monitoring... (Ctrl+C untuk stop)")
    print()

    cycle = 0
    try:
        while True:
            for wallet_cfg in WALLETS:
                try:
                    check_wallet(wallet_cfg)
                except Exception as e:
                    print(f"  [!] Error {wallet_cfg['name']}: {e}")

            # Print heartbeat tiap ~1 menit biar tau masih jalan
            cycle += 1
            if cycle % (60 // CHECK_INTERVAL) == 0:
                now = datetime.now().strftime("%H:%M:%S")
                print(f"  [{now}] ♥ Still running... (cycle #{cycle})")

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n[STOP] Tracker dihentikan.")
        send_telegram("🔴 <b>Tracker Stopped</b>")


if __name__ == "__main__":
    main()
