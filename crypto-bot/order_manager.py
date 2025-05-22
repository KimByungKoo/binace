# order_manager.py
import os
from binance.client import Client
from utils.telegram import send_telegram_message
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
client = Client(API_KEY, API_SECRET)

def set_leverage(symbol, leverage):
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
    except Exception as e:
        send_telegram_message(f"⚠️ 레버리지 설정 실패: {symbol} → {e}")

def round_qty(symbol, raw_qty):
    info = client.futures_exchange_info()
    for s in info['symbols']:
        if s['symbol'] == symbol:
            for f in s['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    step_size = float(f['stepSize'])
                    return round((raw_qty // step_size) * step_size, 8)
    return round(raw_qty, 3)  # fallback

def place_order(symbol, side, quantity, entry_price, tp_price):
    try:

        quantity = round_qty(symbol, quantity)

        client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_BUY if side == "long" else Client.SIDE_SELL,
            type=Client.ORDER_TYPE_MARKET,
            quantity=quantity
        )

        client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_SELL if side == "long" else Client.SIDE_BUY,
            type=Client.ORDER_TYPE_LIMIT,
            quantity=quantity,
            price=round(tp_price, 2),
            timeInForce="GTC",
            reduceOnly=True
        )

        send_telegram_message(
            f"🚀 *진입 완료: {symbol} ({side.upper()})*"
            f"   ├ 수량: `{quantity}`"
            f"   ├ 진입가(시장): `{round(entry_price, 4)}`"
            f"   └ 익절가(TP): `{round(tp_price, 4)}`"
        )

    except Exception as e:
        send_telegram_message(f"⚠️ 주문 실패: {symbol} {side.upper()} → {e}")

def auto_trade_from_signal(signal):
    symbol = signal["symbol"]
    direction = signal["direction"]
    entry_price = signal["price"]
    tp_price = signal["take_profit"]
    sl_price = signal["stop_loss"]

    diff = abs(entry_price - sl_price)
    loss_pct = diff / entry_price
    leverage = int(1 / (loss_pct + 0.005))

    set_leverage(symbol, leverage)

    margin_usdt = 10
    qty = round(margin_usdt * leverage / entry_price, 3)

    place_order(symbol, direction, qty, entry_price, tp_price)