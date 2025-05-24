import time
import pandas as pd
from datetime import datetime
from utils.telegram import send_telegram_message
from utils.binance import get_1m_klines, client,has_open_position
from order_manager import close_position, auto_trade_from_signal
from config import SPIKE_CONFIG as cfg

def get_top_disparity_symbols(n=1):
    """
    가장 이격도가 큰 심볼 n개를 반환하는 함수 (1분봉 기준 MA7과의 괴리율 기준)

    Returns:
        List of tuples: (symbol, latest_price, ma7, disparity_percent)
    """
    try:
        # 바이낸스 선물 모든 심볼의 현재 데이터 불러오기
        tickers = client.futures_ticker()
        df = pd.DataFrame(tickers)

        # USDT 마켓에 해당하며, 'UP', 'DOWN' 레버리지 토큰은 제외
        df = df[df['symbol'].str.endswith('USDT') & ~df['symbol'].str.contains('DOWN|UP')]

        disparities = []

        # 각 심볼에 대해 이격도 계산
        for symbol in df['symbol']:
            try:
                # 1분봉 캔들 30개 가져오기
                candles = get_1m_klines(symbol, interval='1m', limit=30)

                # 7봉 이동평균 계산
                candles['ma7'] = candles['close'].rolling(7).mean()

                # 가장 최근 종가 및 MA7 불러오기
                latest = candles.iloc[-1]
                ma7 = candles['ma7'].iloc[-1]

                # 유효한 MA7이 있을 때만 진행
                if pd.notna(ma7):
                    # 이격도: (종가 - MA7) / MA7 * 100
                    disparity = abs(latest['close'] - ma7) / ma7 * 100
                    disparities.append((symbol, latest['close'], ma7, disparity))
            except:
                # 개별 심볼 처리 중 오류 무시하고 다음으로 넘어감
                continue

        # 이격도 높은 순으로 정렬 후 상위 n개 반환
        sorted_syms = sorted(disparities, key=lambda x: x[3], reverse=True)
        return sorted_syms[:n]

    except Exception as e:
        # 전체 처리 오류 시 텔레그램 알림
        send_telegram_message(f"🚨 get_top_disparity_symbols 에러: {e}")
        return []


def check_and_enter_hyper_disparity():
    while True:
        try:
            targets = get_top_disparity_symbols()
            for symbol, price, ma7, disparity in targets:
                if has_open_position(symbol):
                    continue

                # 5% 이상 이격 아니면 스킵
                if disparity < 1:
                    continue

                # MA7보다 위에 있으면 short / 아래면 long → 되돌림 노림
                direction = "short" if price > ma7 else "long"

                # 목표가 = 되돌림 방향 / 손절 = 확산 방향
                tp = price * (0.995 if direction == "short" else 1.005)
                sl = price * (1.005 if direction == "short" else 0.995)

                signal = {
                    "symbol": symbol,
                    "direction": direction,
                    "price": price,
                    "take_profit": tp,
                    "stop_loss": sl
                }

                send_telegram_message(
                    f"⚡ *하이퍼 진입 시그널* → {symbol}\n"
                    f"   ├ 방향: `{direction}`\n"
                    f"   ├ 현재가: `{round(price, 4)}`\n"
                    f"   ├ MA7: `{round(ma7, 4)}`\n"
                    f"   ├ 이격: `{round(disparity, 2)}%`\n"
                    f"   └ TP: `{round(tp, 4)}` / SL: `{round(sl, 4)}`"
                )

                auto_trade_from_signal(signal)

        except Exception as e:
            send_telegram_message(f"💥 하이퍼 진입 오류: {e}")

        time.sleep(cfg.get("entry_interval", 60))

def monitor_hyper_disparity_exit():
    send_telegram_message("🔄 하이퍼 스캘핑 MA7 기반 익절/손절 감시 시작")
    while True:
        try:
            positions = client.futures_account()['positions']
            for p in positions:
                symbol = p['symbol']
                amt = float(p['positionAmt'])
                entry = float(p['entryPrice'])
                if amt == 0 or entry == 0:
                    continue

                df = get_1m_klines(symbol, interval='1m', limit=10)
                if df.empty or 'close' not in df.columns:
                    continue
                df['ma7'] = df['close'].rolling(7).mean()
                last = df.iloc[-1]['close']
                ma7 = df['ma7'].iloc[-1]
                direction = "long" if amt > 0 else "short"
                qty = abs(amt)

                should_exit = (
                    direction == 'long' and last < ma7 or
                    direction == 'short' and last > ma7
                )

                if should_exit:
                    pct = ((last - entry) / entry * 100) if direction == 'long' else ((entry - last) / entry * 100)
                    now_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                    send_telegram_message(
                        f"🚪 *하이퍼 MA7 이탈 청산: {symbol}*\n"
                        f"   ├ 현재가: `{round(last, 4)}`\n"
                        f"   ├ MA7: `{round(ma7, 4)}`\n"
                        f"   ├ 수익률: `{round(pct, 2)}%`\n"
                        f"   ├ 방향: `{direction}`\n"
                        f"   └ 시각: `{now_time}`"
                    )
                    close_position(symbol, qty, "short" if direction == 'long' else 'long')

        except Exception as e:
            send_telegram_message(f"💥 하이퍼 청산 오류: {e}")

        time.sleep(2)
