# trade_executor.py
from datetime import datetime
from utils.telegram import send_telegram_message
from order_manager import place_order, close_position, round_qty,auto_trade_from_signal

from utils.binance import get_top_symbols, get_1m_klines,client,has_open_position
import time
# client = Client("api_key", "api_secret")

# 포지션 상태 저장용 (전역 변수로 선언)
open_trades = {}

def determine_trade_mode_from_wave(wave_info):
    """
    파동 구조 분석 결과에 따라 거래 모드 결정

    Parameters:
        wave_info (dict): {
            "position": int,  # 현재 파동 내 봉 위치 (1~10)
            "direction": "up" | "down" | None,
            "strength": float,  # 파동 강도 (0~1)
            "volatility": float,  # 최근 변동성
            "rsi": float,  # RSI 값 (0~100)
            "bb_touch": "upper" | "lower" | None  # 볼밴 상/하단 터치 여부
        }

    Returns:
        mode (str): "scalp" | "trend" | "revert"
    """
    pos = wave_info.get("position")
    strength = wave_info.get("strength", 0)
    rsi = wave_info.get("rsi", 50)
    bb = wave_info.get("bb_touch")
    direction = wave_info.get("direction")

    if pos is None:
        return "scalp"  # 정보 부족시 보수적 진입

    # 파동 끝 무렵 + RSI 과열/침체
    if pos >= 8 and (rsi > 70 or rsi < 30):
        return "revert"

    # 중간 파동 + 강한 추세
    if 3 <= pos <= 7 and strength > 0.7:
        return "trend"

    # 볼밴 터치 + RSI 과열/침체 → 단타로
    if bb in ("upper", "lower") and (rsi > 65 or rsi < 35):
        return "scalp"

    # 무난한 파동이면 추세 추종 기본
    if direction in ("up", "down") and strength > 0.5:
        return "trend"

    return "scalp"

def enter_trade_from_wave(symbol, wave_info, price):
    mode = determine_trade_mode_from_wave(wave_info)
    direction = "long" if wave_info['direction'] == "up" else "short"

    qty = round_qty(symbol, 100 / price)
    tp_ratio = {
        "scalp": 1.003,
        "trend": 1.015,
        "revert": 1.01
    }
    sl_ratio = {
        "scalp": 0.995,
        "trend": 0.985,
        "revert": 0.99
    }

    tp = price * tp_ratio[mode] if direction == "long" else price * (2 - tp_ratio[mode])
    sl = price * sl_ratio[mode] if direction == "long" else price * (2 - sl_ratio[mode])

    signal = {
                    "symbol": symbol,
                    "direction": direction,
                    "price": price,
                    "take_profit": tp,
                    "stop_loss": sl
                }
    auto_trade_from_signal(signal)

    # place_order(symbol, direction, qty, price, tp,sl)

    open_trades[symbol] = {
        "entry_time": datetime.utcnow(),
        "entry_price": price,
        "direction": direction,
        "tp": tp,
        "sl": sl,
        "qty": qty,
        "mode": mode
    }

    send_telegram_message(f"🚀 진입 완료: {symbol} ({mode.upper()})\n"
                          f"   ├ 방향     : `{direction}`\n"
                          f"   ├ 현재가   : `{round(price, 4)}`\n"
                          f"   ├ TP       : `{round(tp, 4)}`\n"
                          f"   ├ SL       : `{round(sl, 4)}`\n"
                          f"   └ 모드     : `{mode}`")

def refresh_open_trades_from_binance():
    """
    바이낸스 API를 통해 현재 보유 중인 포지션을 기반으로 open_trades 딕셔너리 초기화
    """
    global open_trades
    open_trades.clear()  # 기존 데이터 초기화

    try:
        positions = client.futures_account()['positions']
        for p in positions:
            symbol = p['symbol']
            amt = float(p['positionAmt'])
            if amt == 0:
                continue  # 보유하지 않은 종목은 스킵

            direction = "long" if amt > 0 else "short"
            entry_price = float(p['entryPrice'])
            qty = abs(amt)

            # 복구된 포지션에 대한 TP/SL 설정
            if direction == "long":
                tp = entry_price * 1.015  # 1.5% 익절
                sl = entry_price * 0.985  # 1.5% 손절
            else:
                tp = entry_price * 0.985  # 1.5% 익절
                sl = entry_price * 1.015  # 1.5% 손절

            open_trades[symbol] = {
                "entry_price": entry_price,
                "qty": qty,
                "direction": direction,
                "entry_time": datetime.utcnow(),
                "tp": tp,
                "sl": sl,
                "mode": "restored"  # 복구된 포지션 표시용
            }

        send_telegram_message(f"♻️ *바이낸스 포지션 복구 완료*: {len(open_trades)}개 포지션 감지됨")

    except Exception as e:
        send_telegram_message(f"💥 open_trades 복구 실패: {e}")

def monitor_exit():
    # 딕셔너리의 키를 리스트로 복사하여 순회
    symbols_to_check = list(open_trades.keys())
    for symbol in symbols_to_check:
        try:
            # 심볼이 아직 open_trades에 있는지 확인
            if symbol not in open_trades:
                continue
                
            trade = open_trades[symbol]
            # print("monitor_exit", trade)
            df = get_1m_klines(symbol, interval="1m", limit=1)
            last_price = df['close'].iloc[-1]

            direction = trade['direction']
            tp = trade['tp']
            sl = trade['sl']
            qty = trade['qty']

            # TP/SL이 None인 경우 건너뛰기
            if tp is None or sl is None:
                continue

            exit_reason = None
            if direction == "long":
                if last_price >= tp:
                    exit_reason = "🟢 익절 TP 도달"
                elif last_price <= sl:
                    exit_reason = "🔴 손절 SL 도달"
            else:
                if last_price <= tp:
                    exit_reason = "🟢 익절 TP 도달"
                elif last_price >= sl:
                    exit_reason = "🔴 손절 SL 도달"

            if exit_reason:
                close_position(symbol, qty, "short" if direction == "long" else "long")
                send_telegram_message(f"{exit_reason}\n"
                                      f"   ├ 종목     : `{symbol}`\n"
                                      f"   ├ 방향     : `{direction}`\n"
                                      f"   ├ 진입가   : `{round(trade['entry_price'], 4)}`\n"
                                      f"   ├ 현재가   : `{round(last_price, 4)}`\n"
                                      f"   └ 모드     : `{trade['mode']}`")
                # 딕셔너리에서 항목 제거
                if symbol in open_trades:
                    del open_trades[symbol]

        except Exception as e:
            send_telegram_message(f"💥 청산 감시 오류: {symbol} - {str(e)}")

def monitor_exit_watcher():
    while True:
        monitor_exit()
        time.sleep(2)


def analyze_wave_from_df(df):
    """
    최근 20봉 기준으로 파동 방향과 신뢰도 분석
    - MA20, MA60 이용한 추세
    - 변동성(고저폭) 기반 에너지 분석
    - RSI로 과매수/과매도 제외
    """
    try:
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma60'] = df['close'].rolling(60).mean()
        df['range'] = df['high'] - df['low']
        df['volatility'] = df['range'].rolling(10).mean()

        df['rsi'] = calculate_rsi(df, period=7)

        latest = df.iloc[-1]

        # 조건: 추세 방향
        if latest['ma20'] > latest['ma60']:
            direction = "up"
        elif latest['ma20'] < latest['ma60']:
            direction = "down"
        else:
            return None  # 추세 없음

        # 조건: 충분한 에너지와 정상적인 RSI
        if latest['volatility'] < df['volatility'].mean() * 0.8:
            return None  # 에너지 부족
        if latest['rsi'] > 80 or latest['rsi'] < 20:
            return None  # 과열/과매도

        return {
            "direction": direction,
            "confidence": "high" if latest['volatility'] > df['volatility'].mean() else "medium"
        }

    except Exception as e:
        send_telegram_message(f"⚠️ 파동 분석 오류: {e}")
        return None
    
def calculate_rsi(df, period=7):
    delta = df['close'].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi



def wave_trade_watcher():
    """
    ✅ 파동 기반 트레이드 감시 루프
    - 시총 상위 심볼 대상으로 주기적으로 파동 분석
    - 진입 조건 만족 시 자동 진입
    """
    send_telegram_message("🌊 파동 기반 진입 감시 시작...")

    refresh_open_trades_from_binance()

    while True:
        try:
            symbols = get_top_symbols(20)  # 시총 상위 20종목
            for symbol in symbols:
                df = get_1m_klines(symbol, interval="3m", limit=120)  # 3분봉 기준
                if df.empty or len(df) < 60:
                    continue

                wave_info = analyze_wave_from_df(df)  # ← 너가 정의한 파동 분석 함수
                price = df.iloc[-1]['close']

                if wave_info:  # 파동 조건 만족했을 때만 진입
                    enter_trade_from_wave(symbol, wave_info, price)


            time.sleep(60)  # 1분 주기로 갱신

        except Exception as e:
            send_telegram_message(f"💥 파동 감시 오류: {e}")
            time.sleep(30)