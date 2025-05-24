import time
import pandas as pd
from datetime import datetime
from utils.telegram import send_telegram_message
from utils.binance import get_1m_klines, client,has_open_position
from order_manager import close_position, auto_trade_from_signal
from config import SPIKE_CONFIG as cfg

def get_top_disparity_symbols(n=1):
    try:
        tickers = client.futures_ticker()
        df = pd.DataFrame(tickers)
        df = df[df['symbol'].str.endswith('USDT') & ~df['symbol'].str.contains('DOWN|UP')]

        disparities = []
        for symbol in df['symbol']:
            try:
                candles = get_1m_klines(symbol, interval='1m', limit=30)
                candles['ma7'] = candles['close'].rolling(7).mean()
                latest = candles.iloc[-1]
                ma7 = candles['ma7'].iloc[-1]
                if pd.notna(ma7):
                    disparity = abs(latest['close'] - ma7) / ma7 * 100
                    disparities.append((symbol, latest['close'], ma7, disparity))
            except:
                continue

        sorted_syms = sorted(disparities, key=lambda x: x[3], reverse=True)
        return sorted_syms[:n]
    except Exception as e:
        send_telegram_message(f"🚨 get_top_disparity_symbols 에러: {e}")
        return []


def check_and_enter_hyper_disparity():
    while True:
        try:
            targets = get_top_disparity_symbols()
            for symbol, price, ma7, disparity in targets:
                if has_open_position(symbol):
                    continue

                direction = "long" if price > ma7 else "short"
                tp = price * (1.005 if direction == "long" else 0.995)
                sl = price * (0.995 if direction == "long" else 1.005)

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

        time.sleep(5)
