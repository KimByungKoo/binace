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
    
    
def monitor_trailing_stop():
    send_telegram_message("🔄 MA7 기준 트레일링 스탑 감시 시작 (3분봉 기준)")

    while True:
        try:
            positions = client.futures_account()['positions']
            for p in positions:
                symbol = p['symbol']
                amt = float(p['positionAmt'])
                if amt == 0:
                    continue  # 포지션 없는 건 스킵

                direction = "long" if amt > 0 else "short"
                qty = abs(amt)

                # ✅ 3분봉 기준 20개 봉 (충분한 MA 계산용)
                df = get_klines(symbol, interval="3m", limit=20)
                if df.empty or 'close' not in df.columns:
                    continue

                df['ma7'] = df['close'].rolling(window=7).mean()
                last_close = df['close'].iloc[-1]
                ma7 = df['ma7'].iloc[-1]

                # 예외 처리: MA7이 계산 안된 경우
                if pd.isna(ma7):
                    continue

                if direction == 'long' and last_close < ma7:
                    send_telegram_message(f"📉 *{symbol} 롱 포지션 MA7 하향 이탈* → `{round(last_close,4)} < {round(ma7,4)}` → 청산")
                    close_position(symbol, qty, "short")

                elif direction == 'short' and last_close > ma7:
                    send_telegram_message(f"📈 *{symbol} 숏 포지션 MA7 상향 이탈* → `{round(last_close,4)} > {round(ma7,4)}` → 청산")
                    close_position(symbol, qty, "long")

        except Exception as e:
            send_telegram_message(f"💥 트레일링 감시 중 오류 발생: {e}")

        time.sleep(60)  # 1분마다 체크