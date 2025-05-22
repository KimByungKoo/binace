from utils.binance import get_top_symbols, get_1m_klines
from utils.telegram import send_telegram_message
import time
from config import SPIKE_CONFIG as cfg

def check_volume_spike_disparity(symbol):
    try:
        df = get_1m_klines(symbol, interval=cfg["interval"], limit=cfg["limit"])
        if df.empty or 'volume' not in df.columns:
            raise ValueError("❌ 데이터프레임이 비어 있거나 volume 컬럼 없음")

        df['volume_ma'] = df['volume'].rolling(cfg["vol_ma_window"]).mean()
        df['ma'] = df['close'].rolling(cfg["disparity_ma"]).mean()
        df.dropna(inplace=True)

        if len(df) < cfg["lookback"] + 1:
            raise ValueError("❌ 유효한 데이터 부족 (이격도 및 볼륨 MA 계산 실패)")

        recent = df.iloc[-cfg["lookback"]:].copy()
        recent_spike = recent[recent['volume'] > recent['volume_ma'] * cfg["spike_multiplier"]]

        if recent_spike.empty:
            if cfg.get("notify_on_spike_fail", False):
                send_telegram_message(f"ℹ️ [{symbol}] 최근 {cfg['lookback']}봉 거래량 스파이크 없음")
            return None

        latest = df.iloc[-1]
        disparity = (latest['close'] / latest['ma']) * 100

        if not (disparity < (100 - cfg["disparity_thresh"]) or disparity > (100 + cfg["disparity_thresh"])):
            if cfg.get("notify_on_disparity_fail", False):
                send_telegram_message(
                    f"⚖️ [{symbol}] 이격도 조건 불충족\n"
                    f"현재 이격도: `{round(disparity, 2)}%` | 기준: ±{cfg['disparity_thresh']}%"
                )
            return None

        return {
            'symbol': symbol,
            'price': latest['close'],
            'ma': latest['ma'],
            'disparity': disparity,
            'volume': latest['volume'],
            'volume_ma': latest['volume_ma'],
            'direction': 'LONG' if disparity < 100 else 'SHORT'
        }

    except Exception as e:
        msg = f"⚠️ [{symbol}] 스파이크 분석 실패:\n{str(e)}"
        print(msg)
        if cfg.get("notify_on_error", True):
            send_telegram_message(msg)
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