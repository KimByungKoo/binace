# realtime_spike_bot.py
import websocket
import threading
import json
import pandas as pd
import time
from collections import deque
from utils.telegram import send_telegram_message
from order_manager import auto_trade_from_signal

# 설정
WATCH_SYMBOLS = ["btcusdt", "ethusdt", "solusdt"]
MAXLEN = 300  # 1분봉 300개 정도의 길이 확보
SPIKE_MULTIPLIER = 2.5
DISPARITY_THRESH = 1.5  # %

symbol_data = {sym: deque(maxlen=MAXLEN) for sym in WATCH_SYMBOLS}

# WebSocket 콜백
# {
#   "e": "trade",              // Event type
#   "E": 123456789,            // Event time
#   "s": "BTCUSDT",            // Symbol
#   "t": 12345,                // Trade ID
#   "p": "0.001",              // Price
#   "q": "100",                // Quantity
#   "X": "MARKET",             // Market type
#   "m": true                  // Is the buyer the market maker?
# }
def on_message(ws, message):

    #print("[RAW]", message)  # 이걸로 구조 먼저 확인
    # message = message.decode('utf-8')  # 바이낸스에서 오는 메시지는 UTF-8로 인코딩되어 있음
    #print("[RAW]", message)
    # 바이낸스에서 오는 메시지는 JSON 형식이므로 파싱
   
    try:
        data = json.loads(message)

        #print("[ㅇㅁㅅㅁ]", data)
        if data.get("e") == "trade":
            symbol = data["s"].lower()
            price = float(data["p"])
            volume = float(data["q"])
            ts = int(data["T"])
            symbol_data[symbol].append({
                "price": price, "volume": volume, "ts": ts
            })
        else:
            print("📭 무시된 메시지 타입:", data.get("e"))

    except Exception as e:
        print("WebSocket 메시지 처리 에러:", e)


def on_open(ws):
    params = [f"{sym}@trade" for sym in WATCH_SYMBOLS]
    payload = {
        "method": "SUBSCRIBE",
        "params": params,
        "id": 1
    }
    ws.send(json.dumps(payload))
    send_telegram_message("✅ WebSocket 구독 시작")


def on_error(ws, error):
    send_telegram_message("WebSocket 에러:", error)


def on_close(ws, *args):
    send_telegram_message("WebSocket 연결 종료")

# 감시 로직

def spike_checker():
    while True:
        for sym in WATCH_SYMBOLS:
            data = list(symbol_data[sym])
            if len(data) < 30:
                continue

            df = pd.DataFrame(data)
            df['minute'] = pd.to_datetime(df['ts'], unit='ms').dt.floor('min')
            grouped = df.groupby('minute').agg({
                'price': 'last',
                'volume': 'sum'
            }).reset_index()

            if len(grouped) < 10:
                continue

            grouped['volume_ma'] = grouped['volume'].rolling(10).mean()
            grouped['ma'] = grouped['price'].rolling(10).mean()
            grouped.dropna(inplace=True)

            latest = grouped.iloc[-1]
            disparity = abs((latest['price'] - latest['ma']) / latest['ma']) * 100

            if latest['volume'] > latest['volume_ma'] * SPIKE_MULTIPLIER and disparity > DISPARITY_THRESH:
                direction = "long" if latest['price'] > latest['ma'] else "short"

                send_telegram_message(
                    f"💥 *{sym.upper()} 스파이크 발생!*"
                    f"   ├ 현재가: `{round(latest['price'], 2)}`"
                    f"   ├ MA: `{round(latest['ma'], 2)}`"
                    f"   ├ 이격도: `{round(disparity, 2)}%`"
                    f"   └ 방향: `{direction.upper()}`"
                )

                signal = {
                    "symbol": sym.upper(),
                    "direction": direction,
                    "price": latest['price'],
                    "take_profit": latest['price'] * (1.02 if direction == "long" else 0.98),
                    "stop_loss": latest['price'] * (0.99 if direction == "long" else 1.01)
                }
                auto_trade_from_signal(signal)

        time.sleep(10)

# 실행
if __name__ == "__main__":
    ws_url = "wss://fstream.binance.com/ws"
    ws = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    threading.Thread(target=spike_checker, daemon=True).start()
    ws.run_forever()
    send_telegram_message("WebSocket 실행 중...")