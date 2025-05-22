# position_monitor.py
import time
from binance.client import Client
import os
from dotenv import load_dotenv
from utils.telegram import send_telegram_message

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
client = Client(API_KEY, API_SECRET)

def get_active_positions():
    try:
        positions = client.futures_account()['positions']
        result = []
        for pos in positions:
            entry = float(pos['entryPrice'])
            qty = float(pos['positionAmt'])
            if qty != 0:
                symbol = pos['symbol']
                side = 'LONG' if qty > 0 else 'SHORT'
                current_price = float(client.futures_mark_price(symbol=symbol)['markPrice'])
                pnl = float(pos['unRealizedProfit'])
                result.append({
                    'symbol': symbol,
                    'side': side,
                    'entry': entry,
                    'qty': qty,
                    'current': current_price,
                    'pnl': pnl
                })
        return result
    except Exception as e:
        print("포지션 조회 실패:", e)
        return []

def broadcast_position_status():
    positions = get_active_positions()
    if not positions:
        send_telegram_message("💤 현재 보유 중인 포지션이 없습니다.")
        return

    msg = "📊 *현재 포지션 현황*
"
    for p in positions:
        msg += (
            f"*{p['symbol']}* `{p['side']}`
"
            f"   ├ 진입가: `{round(p['entry'], 4)}`
"
            f"   ├ 현재가: `{round(p['current'], 4)}`
"
            f"   └ 손익: `{round(p['pnl'], 2)} USDT`

"
        )
    send_telegram_message(msg)

if __name__ == "__main__":
    while True:
        broadcast_position_status()
        time.sleep(300)  # 5분마다
