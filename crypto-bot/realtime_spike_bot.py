# realtime_spike_bot.py
import websocket
import threading
import json
import pandas as pd
import time
import os
from collections import deque
from dotenv import load_dotenv
from binance.client import Client

from utils.telegram import send_telegram_message
from order_manager import auto_trade_from_signal
from utils.binance import get_1m_klines  # 반드시 utils에 있어야 함

# === 환경 변수 로딩 (API 키 불러오기) ===
load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
client = Client(API_KEY, API_SECRET)

# === 설정값 ===
MAXLEN = 300
SPIKE_MULTIPLIER = 2.5
DISPARITY_THRESH = 1.5  # 이격도 임계값 (%)

# === 시총 상위 종목 불러오기 ===
def get_top_symbols(n=30):
    try:
        tickers = client.futures_ticker()
        info = client.futures_exchange_info()
        tradable = set()

        for s in info['symbols']:
            if (s['contractType'] == 'PERPETUAL' and
                s['quoteAsset'] == 'USDT' and
                not s['symbol'].endswith('DOWN') and
                s['status'] == 'TRADING'):
                tradable.add(s['symbol'])

        usdt_tickers = [t for t in tickers if t['symbol'] in tradable]
        sorted_by_volume = sorted(usdt_tickers, key=lambda x: float(x['quoteVolume']), reverse=True)
        return [t['symbol'].lower() for t in sorted_by_volume[:n]]

    except Exception as e:
        send_telegram_message(f"❌ 시총 종목 조회 실패: {e}")
        return ["btcusdt", "ethusdt", "solusdt"]  # fallback

# === 실시간 감시용 심볼 및 데이터 구조 초기화 ===
WATCH_SYMBOLS = get_top_symbols()
symbol_data = {sym: deque(maxlen=MAXLEN) for sym in WATCH_SYMBOLS}

# === 과거 1분봉 데이터로 초기 로딩 ===
def preload_data(symbols):
    for sym in symbols:
        try:
            df = get_1m_klines(sym.upper(), interval="1m", limit=MAXLEN)
            # print(f"🔄 {sym} 초기 데이터 로딩 중... ({len(df)}개)")
            for _, row in df.iterrows():
                # print(f"  - {sym} 데이터 추가: {row} ")
                symbol_data[sym].append({
                    "price": row['close'],
                    "volume": row['volume'],
                    "ts": int(pd.to_datetime(row['open']).timestamp() * 1000)
                })
            print(f"✅ {sym} 초기 데이터 로딩 완료 ({len(symbol_data[sym])}개)")
        except Exception as e:
            print(f"❌ {sym} 초기 데이터 로딩 실패: {e}")

preload_data(WATCH_SYMBOLS)

# === WebSocket 콜백 정의 ===
def on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get("e") != "trade":
            return

         
    
        symbol = data["s"].lower()
        price = float(data["p"])
        volume = float(data["q"])
        ts = int(data["T"])
        if symbol in symbol_data:
            symbol_data[symbol].append({"price": price, "volume": volume, "ts": ts})
        
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
    send_telegram_message(f"✅ 실시간 스파이크 감시 시작 ({len(WATCH_SYMBOLS)} 종목)")

def on_error(ws, error):
    send_telegram_message(f"WebSocket 에러 발생: {error}")

def on_close(ws, *args):
    send_telegram_message("🔌 WebSocket 연결 종료")

# === 스파이크 감지 로직 ===
def spike_checker():
    while True:
        for sym in WATCH_SYMBOLS:
            data = list(symbol_data[sym])
            print(f"🔄 {sym} 데이터 길이: {len(data)}")
            if len(data) < 30:
                continue

            # print(f"🔄 {sym} 데이터 처리 중... ({len(data)}개)")
            df = pd.DataFrame(data)
            df['minute'] = pd.to_datetime(df['ts'], unit='ms').dt.floor('min')
            grouped = df.groupby('minute').agg({'price': 'last', 'volume': 'sum'}).reset_index()

            print(f"🔄 {sym} 그룹화 완료: {len(grouped)}개")
            if len(grouped) < 10:
                continue

            print(f"🔄 {sym} 이동평균 계산 중...")

            grouped['volume_ma'] = grouped['volume'].rolling(10).mean()
            grouped['ma'] = grouped['price'].rolling(10).mean()
            grouped.dropna(inplace=True)
            print(f"🔄 {sym} 이동평균 계산 완료")
    
            latest = grouped.iloc[-1]
            disparity = abs((latest['price'] - latest['ma']) / latest['ma']) * 100
            print(f"🔄 {sym} 최신 데이터: {latest['price']}, MA: {latest['ma']}, 이격도: {disparity:.2f}%")

            if latest['volume'] > latest['volume_ma'] * SPIKE_MULTIPLIER and disparity > DISPARITY_THRESH:
                direction = "long" if latest['price'] > latest['ma'] else "short"

                send_telegram_message(
                    f"💥 *{sym.upper()} 스파이크 발생!*\n"
                    f"   ├ 현재가: `{round(latest['price'], 2)}`\n"
                    f"   ├ MA: `{round(latest['ma'], 2)}`\n"
                    f"   ├ 이격도: `{round(disparity, 2)}%`\n"
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

# === 실행 ===
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
