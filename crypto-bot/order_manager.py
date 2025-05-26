# order_manager.py
import os
from binance.client import Client
from utils.telegram import send_telegram_message
from dotenv import load_dotenv
from utils.binance import has_open_position,get_1m_klines
import pandas as pd
import time
import math
from datetime import datetime, timedelta

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
        print(f"주문 실패: {symbol} {side.upper()} → {e}")
        # send_telegram_message(f"⚠️ 주문 실패: {symbol} {side.upper()} → {e}")

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
    
    set_leverage(symbol, 30)  # 선택적으로 레버리지 설정 추가
    
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
    send_telegram_message("🔄 트레일링 스탑 감시 시작 (1분 과열 우선 + 3분 MA7 기본 + 동적 익절 조건)")

    volatile_state = set()

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

                # === 1분봉 과열 감지 ===
                df_1m = get_1m_klines(symbol, interval="1m", limit=30)
                if df_1m.empty or 'high' not in df_1m.columns or 'low' not in df_1m.columns:
                    continue

                df_1m['range_pct'] = (df_1m['high'] - df_1m['low']) / df_1m['low'] * 100
                is_volatile = (df_1m['range_pct'] >= 1).any()
                if is_volatile:
                    volatile_state.add(symbol)

                df_1m['ma7'] = df_1m['close'].rolling(7).mean()
                df_1m['ma20'] = df_1m['close'].rolling(20).mean()

                # 1분 과열 → 전봉 종가
                last_close = df_1m['close'].iloc[-2]
                ma7 = df_1m['ma7'].iloc[-2]
                ma20 = df_1m['ma20'].iloc[-2]

                if symbol in volatile_state:
                    if pd.notna(ma7):
                        should_exit = (
                            direction == 'long' and last_close < ma7 or
                            direction == 'short' and last_close > ma7
                        )

                        send_telegram_message(
                             f"🔍 *{symbol} 포지션 체크 (1분봉 기준)*\n"
                             f"   ├ 방향     : `{direction.upper()}`\n"
                             f"   ├ 현재가   : `{round(last_close, 4)}`\n"
                             f"   ├ MA7      : `{round(ma7, 4)}`\n"
                             f"   ├ 과열 감지: `✅`\n"
                             f"   └ 감시 기준: `1분봉`"
                         )

                        if should_exit:
                            profit_pct = ((last_close - entry_price) / entry_price * 100) if direction == "long" else ((entry_price - last_close) / entry_price * 100)
                            now_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                            send_telegram_message(
                                f"🔥 *{symbol} 1분봉 과열+MA7 이탈 청산!*\n"
                                f"   ├ 현재가 : `{round(last_close, 4)}`\n"
                                f"   ├ MA7    : `{round(ma7, 4)}`\n"
                                f"   ├ 진입가 : `{round(entry_price, 4)}`\n"
                                f"   ├ 수익률 : `{round(profit_pct, 2)}%`\n"
                                f"   └ 시각   : `{now_time}`"
                            )
                            close_position(symbol, qty, "short" if direction == "long" else "long")
                            volatile_state.remove(symbol)
                        continue

                # === 동적 익절 조건 평가 (1분봉 기준)
                d1 = abs(ma7 - ma20)
                d2 = abs(last_close - ma7)

                if pd.notna(ma7) and pd.notna(ma20)and (
                                (direction == "long" and last_close > entry_price) or
                                (direction == "short" and last_close < entry_price)
                                ):
                    # 익절 조건: MA7과 MA20의 거리와 현재가의 거리 비교
                    
                    
                    # 익절 조건 판단 전에 필터링
                    if d1 / ma7 * 100 > 1:
                        
                        
                        if d2 > d1:
                            exit_price = last_close
                            reason = "📈 확장이격 감지 → 현재가 익절"
                        elif d2 < d1:
                            exit_price = ma7
                            reason = "🔄 정상추세 유지 → MA7 익절"
                        else:
                            exit_price = ma20
                            reason = "⚖️ 불확실 → MA20 익절"
    
                        profit_pct = ((exit_price - entry_price) / entry_price * 100) if direction == "long" else ((entry_price - exit_price) / entry_price * 100)
    
                        send_telegram_message(
                            f"🎯 *익절 조건 감지: {symbol}*\n"
                            f"   ├ 방향     : `{direction.upper()}`\n"
                            f"   ├ 현재가   : `{round(last_close, 4)}`\n"
                            f"   ├ MA7      : `{round(ma7, 4)}`\n"
                            f"   ├ MA20     : `{round(ma20, 4)}`\n"
                            f"   ├ D1       : `{round(d1, 4)}` / D2: `{round(d2, 4)}`\n"
                            f"   ├ 익절가   : `{round(exit_price, 4)}`\n"
                            f"   ├ 수익률   : `{round(profit_pct, 2)}%`\n"
                            f"   └ 사유     : {reason}"
                        )
                        close_position(symbol, qty, "short" if direction == "long" else "long")
                        continue

                # === 기본 3분봉 MA7 감시 ===
                df_3m = get_1m_klines(symbol, interval="3m", limit=20)
                if df_3m.empty or 'close' not in df_3m.columns:
                    continue

                df_3m['ma7'] = df_3m['close'].rolling(7).mean()
                # 3분 감시도 전봉 기준
                last_close_3m = df_3m['close'].iloc[-2]
                ma7_3m = df_3m['ma7'].iloc[-2]

                if pd.isna(ma7_3m):
                    continue

                should_exit = (
                    direction == 'long' and last_close_3m < ma7_3m or
                    direction == 'short' and last_close_3m > ma7_3m
                )

                # send_telegram_message(
                #     f"🔍 *{symbol} 포지션 체크 (3분봉 기준)*\n"
                #     f"   ├ 방향     : `{direction.upper()}`\n"
                #     f"   ├ 현재가   : `{round(last_close_3m, 4)}`\n"
                #     f"   ├ MA7      : `{round(ma7_3m, 4)}`\n"
                #     f"   └ 감시 기준: `3분봉`"
                # )

                if should_exit:
                    profit_pct = ((last_close_3m - entry_price) / entry_price * 100) if direction == "long" else ((entry_price - last_close_3m) / entry_price * 100)
                    now_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                    send_telegram_message(
                        f"📉 *{symbol} 3분봉 MA7 이탈 청산!*\n"
                        f"   ├ 현재가 : `{round(last_close_3m, 4)}`\n"
                        f"   ├ MA7    : `{round(ma7_3m, 4)}`\n"
                        f"   ├ 진입가 : `{round(entry_price, 4)}`\n"
                        f"   ├ 수익률 : `{round(profit_pct, 2)}%`\n"
                        f"   └ 시각   : `{now_time}`"
                    )
                    close_position(symbol, qty, "short" if direction == "long" else "long")

        except Exception as e:
            send_telegram_message(f"💥 트레일링 감시 중 오류: {e}")

        time.sleep(6)


  

def monitor_ma7_touch_exit():
    send_telegram_message("📉 MA7 터치 청산 감시 시작 (진입봉은 무시)")

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

                df = get_1m_klines(symbol, interval="1m", limit=20)
                if df.empty or 'close' not in df.columns:
                    continue

                df['ma7'] = df['close'].rolling(7).mean()
                last_close = df['close'].iloc[-1]
                ma7 = df['ma7'].iloc[-1]
                last_time = df['timestamp'].iloc[-1]  # 이게 현재 봉 시작 시각

                # 진입 시각보다 현재 봉이 지나갔는지 확인
                entry_time = datetime.utcfromtimestamp(int(p['updateTime']) / 1000)  # futures_account()['positions']의 updateTime 사용
                if entry_time.replace(second=0, microsecond=0) >= last_time.replace(second=0, microsecond=0):
                    continue  # 진입봉이면 청산 무시

                if pd.isna(ma7):
                    continue

                should_exit = (
                    direction == "long" and last_close <= ma7 or
                    direction == "short" and last_close >= ma7
                )

                if should_exit:
                    now_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                    profit_pct = ((last_close - entry_price) / entry_price * 100) if direction == "long" else ((entry_price - last_close) / entry_price * 100)

                    send_telegram_message(
                        f"🚨 *{symbol} MA7 터치 청산 (1분봉)*\n"
                        f"   ├ 현재가   : `{round(last_close, 4)}`\n"
                        f"   ├ MA7      : `{round(ma7, 4)}`\n"
                        f"   ├ 진입가   : `{round(entry_price, 4)}`\n"
                        f"   ├ 수익률   : `{round(profit_pct, 2)}%`\n"
                        f"   └ 시각     : `{now_time}`"
                    )
                    close_position(symbol, qty, "short" if direction == "long" else "long")

        except Exception as e:
            send_telegram_message(f"💥 MA7 터치 청산 오류: {e}")

        time.sleep(5)

from datetime import datetime, timedelta

from datetime import datetime, timedelta

def monitor_fixed_profit_loss_exit():
    send_telegram_message("🎯 수익/손실 퍼센트 기준 실시간 청산 감시 시작")

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

                # 진입 직후 1분은 제외
                entry_time = datetime.utcfromtimestamp(p['updateTime'] / 1000)
                if datetime.utcnow() - entry_time < timedelta(minutes=1):
                    continue

                df = get_1m_klines(symbol, interval="1m", limit=2)
                if df.empty or 'close' not in df.columns or len(df) < 2:
                    continue

                last_price = df['close'].iloc[-1]
                prev_high = df['high'].iloc[-2]
                prev_low = df['low'].iloc[-2]

                pnl = (last_price - entry_price) * qty if direction == "long" else (entry_price - last_price) * qty
                pos_value = entry_price * qty
                pnl_pct = (pnl / pos_value) * 100
                now_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

                should_exit = False
                reason = ""

                if pnl_pct >= cfg["min_profit_pct"]:
                    should_exit = True
                    reason = f"🟢 *익절 청산 ({round(pnl_pct,2)}%)*"

                elif pnl_pct <= -cfg["max_loss_pct"]:
                    should_exit = True
                    reason = f"🔴 *손절 청산 ({round(pnl_pct,2)}%)*"

                elif direction == "long" and last_price < prev_low:
                    should_exit = True
                    reason = f"📉 진입봉 최저가 이탈 (롱)"

                elif direction == "short" and last_price > prev_high:
                    should_exit = True
                    reason = f"📈 진입봉 최고가 돌파 (숏)"

                if should_exit:
                    send_telegram_message(
                        f"{reason}\n"
                        f"   ├ 종목     : `{symbol}`\n"
                        f"   ├ 방향     : `{direction.upper()}`\n"
                        f"   ├ 현재가   : `{round(last_price, 4)}`\n"
                        f"   ├ 진입가   : `{round(entry_price, 4)}`\n"
                        f"   ├ 수익금   : `${round(pnl, 2)}` ({round(pnl_pct, 2)}%)\n"
                        f"   └ 시각     : `{now_time}`"
                    )
                    close_position(symbol, qty, "short" if direction == "long" else "long")

        except Exception as e:
            send_telegram_message(f"💥 청산 감시 오류: {e}")

        time.sleep(2)

def close_position(symbol, quantity, side):
    try:
        # 남은 잔량까지 모두 정리 (precision mismatch 대비)
        info = client.futures_exchange_info()
        for s in info['symbols']:
            if s['symbol'] == symbol:
                for f in s['filters']:
                    if f['filterType'] == 'LOT_SIZE':
                        step_size = float(f['stepSize'])
                        precision = int(round(-1 * math.log(step_size, 10)))
                        quantity = round(quantity, precision)
                        break

        # 시장가 청산
        client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_BUY if side == "long" else Client.SIDE_SELL,
            type=Client.ORDER_TYPE_MARKET,
            quantity=quantity,
            reduceOnly=True
        )
        send_telegram_message(f"✅ {symbol} {side.upper()} 포지션 청산 완료 (수량: {quantity})")

    except Exception as e:
        send_telegram_message(f"❌ {symbol} 청산 실패: {e}")