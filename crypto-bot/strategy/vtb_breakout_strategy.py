# vtb_breakout_strategy.py

import pandas as pd
import numpy as np
from datetime import datetime
from utils.telegram import send_telegram_message
from utils.binance import get_1m_klines, has_open_position
from order_manager import auto_trade_from_signal, place_order, set_leverage

# === CONFIG ===
CONFIG = {
    "adx_thresh": 25,
    "rsi_min": 60,
    "rsi_max": 70,
    "vol_multiplier": 2.0,
    "bollinger_length": 20,
    "bollinger_stddev": 2,
    "max_positions": 3,
    "risk_reward_ratio": 2.2,
    "leverage": 10,
    "capital_per_trade": 100
}

from ta.trend import ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands

active_positions = {}

def vtb_signal(symbol):
    try:
        df = get_1m_klines(symbol,interval='15m',limit=100)
        if df.empty:
            return

        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)

        # 지표 계산
        adx = ADXIndicator(df['high'], df['low'], df['close'], window=14)
        rsi = RSIIndicator(df['close'], window=14)
        bb = BollingerBands(df['close'], window=CONFIG['bollinger_length'], window_dev=CONFIG['bollinger_stddev'])

        df['ADX'] = adx.adx()
        df['RSI'] = rsi.rsi()
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_mid'] = bb.bollinger_mavg()

        df['ma7'] = df['close'].rolling(7).mean()
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma60'] = df['close'].rolling(60).mean()
        df['volume_ma'] = df['volume'].rolling(20).mean()

        latest = df.iloc[-1]
        recent_3 = df.iloc[-3:]

        # 조건 체크
        bb_breakout = all(recent_3['close'] > recent_3['bb_upper'])
        if not bb_breakout:
            return

        if latest['ADX'] < CONFIG['adx_thresh']:
            return

        if not (CONFIG['rsi_min'] <= latest['RSI'] <= CONFIG['rsi_max']):
            return

        if latest['volume'] < latest['volume_ma'] * CONFIG['vol_multiplier']:
            return

        if not (latest['ma7'] > latest['ma20'] > latest['ma60']):
            return

        # 포지션 중복 방지
        if has_open_position(symbol) or len(active_positions) >= CONFIG['max_positions']:
            return

        entry = latest['close']
        risk = entry - df['low'].iloc[-2]  # 직전봉 저가 기준
        tp = entry + risk * CONFIG['risk_reward_ratio']
        sl = entry - risk

        qty = CONFIG['capital_per_trade'] / entry

        set_leverage(symbol, CONFIG['leverage'])
        place_order(symbol, "long", qty, entry, tp, sl)

        msg = (
            f"📈 *VTB 진입 시그널: {symbol}* "
            f"   ├ 볼밴 3봉 상단 돌파: ✅\n"
            f"   ├ ADX: {round(latest['ADX'], 2)}\n"
            f"   ├ RSI: {round(latest['RSI'], 2)}\n"
            f"   ├ 거래량: {int(latest['volume'])} vs MA: {int(latest['volume_ma'])}\n"
            f"   ├ MA정배열: ✅\n"
            f"   ├ 진입가: {round(entry, 4)} / TP: {round(tp, 4)} / SL: {round(sl, 4)}\n"
            f"   └ 전략: Volatility + Trend Breakout"
        )
        send_telegram_message(msg)

        active_positions[symbol] = {
            "entry": entry,
            "tp": tp,
            "sl": sl,
            "qty": qty,
            "time": datetime.utcnow()
        }

    except Exception as e:
        send_telegram_message(f"💥 {symbol} 시그널 처리 중 오류: {str(e)}")


# 호출 예시:
# for sym in get_top_symbols():
#     vtb_signal(sym)

def report_spike():
    try:
        symbols = get_top_symbols(50)
        #send_telegram_message(f"✅ 가져온 심볼: {symbols}")

        if not symbols:
            send_telegram_message("❌ 심볼 리스트 비어있음 → 루프 진입 안 함")
            return
        
        
        
        #send_telegram_message(f"✅ 가져온 심볼: {1}")
        for symbol in symbols:
            vtb_signal(symbol)

           
            #send_telegram_message(msg)
    
    except Exception as e:
        send_telegram_message(f"⚠️ 스파이크 예측 리포트 실패: {str(e)}")




# 자동 감시 루프
def spike_watcher_loop():
    
    send_telegram_message(f"😀 spike_loop")
    while True:
        report_spike()
        #report_spike_disparity()
        #report_top_1m_disparities()
        time.sleep(10)  # 1분 주기