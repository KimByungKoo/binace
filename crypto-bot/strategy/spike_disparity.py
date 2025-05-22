from utils.binance import get_top_symbols, get_1m_klines
from utils.telegram import send_telegram_message
import time
from config import SPIKE_CONFIG

# 유연한 스파이크 + 이격도 예측 함수
def check_volume_spike_disparity(symbol, cfg=SPIKE_CONFIG):
    try:
        df = get_1m_klines(symbol, interval=cfg["interval"], limit=cfg["limit"])
        df['volume_ma'] = df['volume'].rolling(cfg["vol_ma_window"]).mean()
        df['ma'] = df['close'].rolling(cfg["disparity_ma"]).mean()
        df.dropna(inplace=True)

        recent = df.iloc[-cfg["lookback"]:].copy()
        recent_spike = recent[recent['volume'] > recent['volume_ma'] * cfg["spike_multiplier"]]

        if recent_spike.empty:
            return None

        latest = df.iloc[-1]
        disparity = (latest['close'] / latest['ma']) * 100

        if disparity < (100 - cfg["disparity_thresh"]) or disparity > (100 + cfg["disparity_thresh"]):
            return {
                'symbol': symbol,
                'price': latest['close'],
                'ma': latest['ma'],
                'disparity': disparity,
                'volume': latest['volume'],
                'volume_ma': latest['volume_ma'],
                'direction': 'LONG' if disparity < 100 else 'SHORT'
            }
        return None
    except Exception as e:
        print(f"[{symbol}] 스파이크 이격도 분석 오류:", e)
        return None

# 수동 리포트 호출용
def report_spike_disparity():
    try:
        symbols = get_top_symbols(20)
        msg = "📈 *볼륨 스파이크 + 이격도 과다 예측 리포트*\n\n"
        found = False

        for symbol in symbols:
            data = check_volume_spike_disparity(symbol)
            if data:
                found = True
                msg += f"*{symbol}* `{data['direction']}`\n"
                msg += f"   ├ 현재가: `{round(data['price'], 4)}`\n"
                msg += f"   ├ MA90: `{round(data['ma'], 4)}`\n"
                msg += f"   ├ 이격도: `{round(data['disparity'], 2)}%`\n"
                msg += f"   ├ 볼륨: `{round(data['volume'], 2)}` vs 평균: `{round(data['volume_ma'], 2)}`\n\n"

        if found:
            send_telegram_message(msg)
        else:
            send_telegram_message("🙅‍♂️ 예측 조건을 만족하는 종목이 없습니다. (볼륨 + 이격도 기준)")
    except Exception as e:
        send_telegram_message(f"⚠️ 스파이크 예측 리포트 실패: {str(e)}")

# 자동 감시 루프
def spike_watcher_loop():
    while True:
        report_spike_disparity()
        time.sleep(60)  # 1분 주기