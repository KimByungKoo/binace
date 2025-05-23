# order_manager.py
import os
from binance.client import Client
from utils.telegram import send_telegram_message
from dotenv import load_dotenv
from utils.binance import has_open_position

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
        
    

    qty = 100 / price  # $100 진입 기준 수량
    
    set_leverage(symbol, 10)  # 선택적으로 레버리지 설정 추가
    send_telegram_message("aasa")
    place_order(symbol, direction, qty, price, tp)
    send_telegram_message("bbb")
    
    active_positions[symbol] = {
        "direction": direction,
        "entry_price": price,
        "entry_time": datetime.utcnow(),
        "take_profit": tp,
        "stop_loss": sl,
        "qty": qty
    }
    
    
def monitor_trailing_stop():
    while True:
        
        for symbol, pos in list(active_positions.items()):
            try:
                df = get_klines(symbol, interval="3m", limit=3)
                send_telegram_message(f"👀감시중 📉 {df.empty}")
                if df.empty:
                    continue
                    
                send_telegram_message(f"👀감시중 📉 {symbol}")
                last_close = float(df['close'].iloc[-1])
                ma_line = df['close'].rolling(3).mean().iloc[-1]
                
                if pos['direction'] == 'long' and last_close < ma_line:
                    send_telegram_message(f"📉 {symbol} 롱 이탈: {last_close} < MA({round(ma_line,2)}) → 청산")
                    close_position(symbol, pos['qty'], "short")
                    active_positions.pop(symbol)

                elif pos['direction'] == 'short' and last_close > ma_line:
                    send_telegram_message(f"📈 {symbol} 숏 이탈: {last_close} > MA({round(ma_line,2)}) → 청산")
                    close_position(symbol, pos['qty'], "long")
                    active_positions.pop(symbol)

            except Exception as e:
                send_telegram_message(f"❌ {symbol} 감시 에러: {e}")
        time.sleep(60)