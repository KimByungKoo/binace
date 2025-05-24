import time
import pandas as pd
from datetime import datetime
from utils.telegram import send_telegram_message

from utils.binance import get_1m_klines, client, has_open_position, get_top_symbols
from order_manager import close_position, auto_trade_from_signal


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

                # MA7보다 위에 있으면 short / 아래면 long → 되돌림 노림
                direction = "short" if price > ma7 else "long"


                send_telegram_message(
                    f"⚡ *하이퍼 진입 시그널 체크* → {symbol}\n"
                    f"   ├ 방향: `{direction}`\n"
                    f"   ├ 현재가: `{round(price, 4)}`\n"
                    f"   ├ MA7: `{round(ma7, 4)}`\n"
                    f"   ├ 이격: `{round(disparity, 2)}%`\n"
                    
                )

                # 5% 이상 이격 아니면 스킵
                if disparity < 1:
                    continue

                

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

        time.sleep( 2)

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


def get_5m_change(symbol):
    try:
        df = get_1m_klines(symbol, interval="1m", limit=6)
        if df.empty or len(df) < 6:
            return None
        start_price = df['open'].iloc[-6]
        end_price = df['close'].iloc[-1]
        change_pct = ((end_price - start_price) / start_price) * 100
        return {
            "symbol": symbol,
            "change_pct": round(change_pct, 3),
            "price": end_price
        }
    except Exception as e:
        print(f"{symbol} 에러: {e}")
        return None

def report_top_5m_changers(n=15):
    send_telegram_message("🔄 report_top_5m_changers 시작")
    while True:
        try:
            symbols = get_top_symbols(100)
            changes = []

            for sym in symbols:
                result = get_5m_change(sym)
                if result:
                    changes.append(result)

            sorted_changes = sorted(changes, key=lambda x: abs(x['change_pct']), reverse=True)
            top = sorted_changes[:n]

            msg = "📈 *1분봉 기준 최근 5봉 변화율 Top5*\n\n"
            for i, item in enumerate(top, 1):
                dir_emoji = "🔺" if item["change_pct"] > 0 else "🔻"
                msg += f"{i}. *{item['symbol']}* {dir_emoji}\n"
                msg += f"   ├ 현재가 : `{round(item['price'], 4)}`\n"
                msg += f"   └ 5봉 변화율 : `{item['change_pct']}%`\n\n"

            send_telegram_message(msg)

        except Exception as e:
            send_telegram_message(f"💥 report_top_5m_changers 오류: {e}")

        time.sleep(6)


def count_consecutive_green(df):
    count = 0
    for i in range(1, len(df)):
        if df['close'].iloc[-i] > df['open'].iloc[-i]:
            count += 1
        else:
            break
    return count

def get_active_symbols(n=100):
    tickers = client.futures_ticker()
    info = client.futures_exchange_info()

    active_set = set()
    for s in info['symbols']:
        if (
            s['contractType'] == 'PERPETUAL'
            and s['quoteAsset'] == 'USDT'
            and not s['symbol'].endswith('DOWN')
            and not s['symbol'].endswith('UP')
            and s['status'] == 'TRADING'
        ):
            active_set.add(s['symbol'])

    sorted_by_volume = sorted(
        [t for t in tickers if t['symbol'] in active_set],
        key=lambda x: float(x['quoteVolume']),
        reverse=True
    )

    return [t['symbol'] for t in sorted_by_volume[:n]]

def get_top5_consecutive_green(threshold=0.5):
    send_telegram_message("🔄 report_top_5m_changers 시작")
    while True:
            try:
      
                symbols = get_active_symbols(100)
                results = []

                for symbol in symbols:
                    try:
                        df = get_1m_klines(symbol, interval="1m", limit=15)
                        df['color'] = df['close'] > df['open']
                        df['body'] = abs(df['close'] - df['open'])

                        # 현재 봉과 같은 색의 연속 봉 수 계산
                        direction = df['color'].iloc[-1]
                        count = 1
                        for i in range(len(df) - 2, -1, -1):
                            if df['color'].iloc[i] == direction:
                                count += 1
                            else:
                                break

                        if count < 3:
                            continue

                        # 변화율 체크
                        start_price = df['open'].iloc[-count]
                        end_price = df['close'].iloc[-1]
                        change_pct = abs((end_price - start_price) / start_price * 100)
                        if change_pct < threshold:
                            continue

                        # 이전 연속 봉의 평균 몸통 대비 현재 봉 크기 확인
                        prev_bodies = df['body'].iloc[-count:-1]
                        avg_body = prev_bodies.mean()
                        curr_body = df['body'].iloc[-1]
                        if curr_body < avg_body * 1.5:
                            continue

                        results.append((symbol, count, round(change_pct, 2)))

                        # === 자동 주문 ===

                        if count <5:
                            direction_str = "long" if direction else "short"
                        else :
                            direction_str = "short" if direction else "long"
                        price = end_price
                        tp = price * (1.01 if direction_str == "long" else 0.99)
                        sl = price * (0.99 if direction_str == "long" else 1.01)
                        qty = 100 / price

                        signal = {
                            "symbol": symbol,
                            "direction": direction_str,
                            "price": price,
                            "take_profit": tp,
                            "stop_loss": sl
                        }

                        send_telegram_message(
                            f"🚀 *{symbol} 자동 진입 시그널*\n"
                            f"   ├ 연속봉 수: `{count}`\n"
                            f"   ├ 변화율: `{change_pct}%`\n"
                            f"   ├ 현재가: `{round(price, 4)}`\n"
                            f"   ├ 방향: `{direction_str}`\n"
                            f"   └ 주문: `진행 중...`"
                        )

                        auto_trade_from_signal(signal)

                    except Exception as e:
                        send_telegram_message(f"💥 {symbol} 처리 실패: {e}")

                if results:
                    sorted_results = sorted(results, key=lambda x: (-x[1], -x[2]))
                    msg = "📊 *연속봉 + 변화율 + 폭발봉 TOP5*\n\n"
                    for symbol, count, change in sorted_results[:5]:
                        msg += f"*{symbol}* → `{count}연속봉`, 변화율: `{change}%`\n"
                    send_telegram_message(msg)
                else:
                    print("😑 조건에 맞는 종목이 없습니다.")
            except Exception as e:
                send_telegram_message(f"💥 report_top_5m_changers 오류: {e}")

            time.sleep(6)