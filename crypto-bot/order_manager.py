# order_manager.py
import os
from binance.client import Client
from utils.telegram import send_telegram_message
from dotenv import load_dotenv
from utils.binance import has_open_position,get_1m_klines
import pandas as pd
import time



load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
client = Client(API_KEY, API_SECRET)

active_positions = {}  # 심볼별 포지션 정보

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
            #price=round(tp_price, 2),
            timeInForce="GTC",
            reduceOnly=True
        )

        send_telegram_message(f"""🚀 *진입 완료: {symbol} ({side.upper()})*
                                       ├ 수량: `{quantity}`
                                       ├ 진입가(시장): `{round(entry_price, 4)}`
                                       └ """)
            
    except Exception as e:
        send_telegram_message(f"⚠️ 주문 실패: {symbol} {side.upper()} → {e}")

def auto_trade_from_signal(signal):
   
    symbol = signal.get("symbol")
    direction = signal.get("direction")
    price = signal.get("price")
    tp = signal.get("take_profit")
    sl = signal.get("stop_loss")
    
  

    if not symbol or not direction or not price:
        send_telegram_message("⚠️ 진입 실패: signal 정보 불완전")
        return
        
    

    if has_open_position(symbol):
        send_telegram_message(f"⛔ {symbol} 이미 보유 중 → 진입 생략")
        return
        
    

    qty = 200 / price  # $100 진입 기준 수량
    
    set_leverage(symbol, 20)  # 선택적으로 레버리지 설정 추가
    
    place_order(symbol, direction, qty, price, tp)
    
    
    active_positions[symbol] = {
        "direction": direction,
        "entry_price": price,
        "entry_time": datetime.utcnow(),
        "take_profit": tp,
        "stop_loss": sl,
        "qty": qty
    }
    
    
from datetime import datetime

volatile_state = set()  # 과열 발생 후 감시 대상

def monitor_trailing_stop():
    send_telegram_message("🔄 트레일링 스탑 감시 시작")

    while True:
        try:
            positions = client.futures_account()['positions']
            for p in positions:
                symbol = p['symbol']
                amt = float(p['positionAmt'])
                entry_price = float(p['entryPrice'])
                if amt == 0 or entry_price == 0:
                    continue

                direction = "long" if amt > 0 else "short"
                qty = abs(amt)

                # === 1분봉 과열 체크 ===
                df_1m = get_1m_klines(symbol, interval="1m", limit=7)
                df_1m['range_pct'] = (df_1m['high'] - df_1m['low']) / df_1m['low'] * 100
                is_volatile = (df_1m['range_pct'] >= 1).any()

                # === MA7 (1분 기준) 이탈 감시 ===
                df_1m['ma7'] = df_1m['close'].rolling(7).mean()
                last_close_1m = df_1m['close'].iloc[-1]
                ma7_1m = df_1m['ma7'].iloc[-1]

                if is_volatile:
                    volatile_state.add(symbol)

                if symbol in volatile_state:
                    if pd.notna(ma7_1m):
                        should_exit = (
                            direction == 'long' and last_close_1m < ma7_1m or
                            direction == 'short' and last_close_1m > ma7_1m
                        )
                        if should_exit:
                            profit_pct = ((last_close_1m - entry_price) / entry_price * 100) if direction == "long" else ((entry_price - last_close_1m) / entry_price * 100)
                            send_telegram_message(
                                f"🔥 *{symbol} 1분봉 과열+MA7 이탈 청산!*\n"
                                f"   ├ 현재가: `{round(last_close_1m, 4)}`\n"
                                f"   ├ MA7: `{round(ma7_1m, 4)}`\n"
                                f"   ├ 수익률: `{round(profit_pct, 2)}%`\n"
                                f"   └ 트리거: 1분봉 기준"
                            )
                            close_position(symbol, qty, "short" if direction == "long" else "long")
                            volatile_state.remove(symbol)
                        continue  # 1분봉 감시한 경우 3분봉 생략

                # === 기본 3분봉 MA7 이탈 ===
                df_3m = get_1m_klines(symbol, interval="3m", limit=20)
                df_3m['ma7'] = df_3m['close'].rolling(7).mean()
                last_close_3m = df_3m['close'].iloc[-1]
                ma7_3m = df_3m['ma7'].iloc[-1]

                if pd.isna(ma7_3m):
                    continue

                should_exit = (
                    direction == 'long' and last_close_3m < ma7_3m or
                    direction == 'short' and last_close_3m > ma7_3m
                )

                if should_exit:
                    profit_pct = ((last_close_3m - entry_price) / entry_price * 100) if direction == "long" else ((entry_price - last_close_3m) / entry_price * 100)
                    send_telegram_message(
                        f"📉 *{symbol} 3분봉 MA7 이탈 청산!*\n"
                        f"   ├ 현재가: `{round(last_close_3m, 4)}`\n"
                        f"   ├ MA7: `{round(ma7_3m, 4)}`\n"
                        f"   ├ 수익률: `{round(profit_pct, 2)}%`\n"
                        f"   └ 트리거: 3분봉 기준"
                    )
                    close_position(symbol, qty, "short" if direction == "long" else "long")

        except Exception as e:
            send_telegram_message(f"💥 트레일링 감시 중 오류: {e}")

        time.sleep(60)
        
        
def close_position(symbol, qty, reverse_direction):
    try:
        client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_SELL if reverse_direction == "short" else Client.SIDE_BUY,
            type=Client.ORDER_TYPE_MARKET,
            quantity=round_qty(symbol, qty),
            reduceOnly=True
        )
        send_telegram_message(f"💸 포지션 종료 완료: {symbol} {reverse_direction.upper()} {qty}")
    except Exception as e:
        send_telegram_message(f"⚠️ 포지션 종료 실패: {symbol} → {e}")