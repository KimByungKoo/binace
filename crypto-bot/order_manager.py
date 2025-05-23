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
            price=round(tp_price, 2),
            timeInForce="GTC",
            reduceOnly=True
        )

        send_telegram_message(f"""🚀 *진입 완료: {symbol} ({side.upper()})*
                                       ├ 수량: `{quantity}`
                                       ├ 진입가(시장): `{round(entry_price, 4)}`
                                       └ 익절가(TP): `{round(tp_price, 4)}`""")
            
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

def monitor_trailing_stop():
    send_telegram_message("🔄 MA7 기준 트레일링 스탑 감시 시작 (3분봉 기준)")

    while True:
        try:
            positions = client.futures_account()['positions']
            for p in positions:
                #send_telegram_message(f" {p['symbol'] }🔄 {float(p['positionAmt']) }. {float(p['entryPrice']) }111(3분봉 기준)")
                symbol = p['symbol']
                amt = float(p['positionAmt'])
                entry_price = float(p['entryPrice'])
                if amt != 0 :
                    
                #if entry_price == 0:
                    #continue
                
                
                    #send_telegram_message(f" {p['symbol'] }🔄 222(3분봉 기준)")
    
                    direction = "long" if amt > 0 else "short"
                    qty = abs(amt)
    
                    df = get_1m_klines(symbol, interval="3m", limit=20)
                    #send_telegram_message(f" {p['symbol'] }🔄 333(3분봉 기준)")
                    if df.empty or 'close' not in df.columns:
                        continue
                        
                    #send_telegram_message(f" {p['symbol'] }🔄 444(3분봉 기준)")
    
                    df['ma7'] = df['close'].rolling(window=7).mean()
                    last_close = float(df['close'].iloc[-1])
                    ma7 = df['ma7'].iloc[-1]
                    now_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    
                    if pd.isna(ma7):
                        continue
                    #send_telegram_message(f" {p['symbol'] }🔄 555(3분봉 기준)")
    
                    profit_pct = ((last_close - entry_price) / entry_price * 100) if direction == "long" else ((entry_price - last_close) / entry_price * 100)
    
                    should_exit = (
                        direction == 'long' and last_close < ma7 or
                        direction == 'short' and last_close > ma7
                    )
                    send_telegram_message(f" {p['symbol'] }🔄 {direction }.last_close {direction } ma7 {direction }")
    
                    if should_exit:
                        msg = (
                            f"📉 *{symbol} {direction.upper()} MA7 이탈 감지!*\n"
                            f"   ├ 현재가 : `{round(last_close, 4)}`\n"
                            f"   ├ MA7    : `{round(ma7, 4)}`\n"
                            f"   ├ 진입가 : `{round(entry_price, 4)}`\n"
                            f"   ├ 수익률 : `{round(profit_pct, 2)}%`\n"
                            f"   └ 시각   : `{now_time}`"
                        )
                        send_telegram_message(msg)
    
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