import time
import pandas as pd
import json
from collections import deque, defaultdict
from datetime import datetime
from binance import ThreadedWebsocketManager
from utils.telegram import send_telegram_message
from config import SPIKE_CONFIG as cfg
from order_manager import auto_trade_from_signal, has_open_position

# 가격 캐싱을 위한 deque: 심볼별로 7개의 가격 저장
price_cache = defaultdict(lambda: deque(maxlen=7))

# 마지막 진입 시간 저장: 1분 쿨다운 관리
last_entry_time = {}

# 하이퍼 이격 진입 조건 체크 및 진입 처리 함수
def handle_price_update(symbol, price):
    now = time.time()

    # 가격 갱신
    price_cache[symbol].append(price)

    # 캐시에 데이터 부족하면 패스
    if len(price_cache[symbol]) < 7:
        return

    # 이동평균(MA7) 계산
    ma7 = sum(price_cache[symbol]) / 7
    disparity = abs(price - ma7) / ma7 * 100

    # 이격이 5% 이상일 때만 진입 고려
    if disparity < 1:
        return

    # 1분 내 진입한 종목이면 패스 (쿨다운 중)
    if symbol in last_entry_time and now - last_entry_time[symbol] < 60:
        return

    # 이미 포지션 보유 중이면 패스
    if has_open_position(symbol):
        return

    # 방향 설정: MA보다 낮으면 롱 / 높으면 숏 (반대매매 전략)
    direction = "long" if price < ma7 else "short"

    # 목표가 및 손절가 설정 (소폭 수익/손절)
    tp = price * (1.005 if direction == "long" else 0.995)
    sl = price * (0.995 if direction == "long" else 1.005)

    # 텔레그램 알림
    send_telegram_message(
        f"⚡ *하이퍼 진입 시그널* → {symbol}\n"
        f"   ├ 방향: `{direction}`\n"
        f"   ├ 현재가: `{round(price, 4)}`\n"
        f"   ├ MA7: `{round(ma7, 4)}`\n"
        f"   ├ 이격: `{round(disparity, 2)}%`\n"
        f"   └ TP: `{round(tp, 4)}` / SL: `{round(sl, 4)}`"
    )

    # 진입 처리
    signal = {
        "symbol": symbol,
        "direction": direction,
        "price": price,
        "take_profit": tp,
        "stop_loss": sl
    }
    auto_trade_from_signal(signal)
    last_entry_time[symbol] = now

# WebSocket 메시지 핸들러 (trade 이벤트 수신)
def on_message(msg):
    try:
        if msg.get("e") != "trade":
            return

        symbol = msg["s"]
        price = float(msg["p"])
        handle_price_update(symbol, price)

    except Exception as e:
        send_telegram_message(f"💥 WebSocket 에러: {e}")

# WebSocket 시작 함수
def start_hyper_disparity_ws():
    send_telegram_message("🚀 하이퍼 이격 실시간 감시 시작!")

    from utils.binance import get_top_symbols
    symbols = get_top_symbols(30)

    twm = ThreadedWebsocketManager(api_key=cfg["BINANCE_API_KEY"], api_secret=cfg["BINANCE_API_SECRET"])
    twm.start()

    for symbol in symbols:
        twm.start_symbol_ticker_socket(callback=on_message, symbol=symbol.lower())

    while True:
        time.sleep(1)

if __name__ == "__main__":
    start_hyper_disparity_ws()
