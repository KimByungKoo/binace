from utils.binance import get_top_symbols, get_1m_klines
from utils.telegram import send_telegram_message
import time
from config import SPIKE_CONFIG as cfg

def check_volume_spike_disparity(symbol):
    issues = []  # 실패 이유 리스트

    try:
        df = get_1m_klines(symbol, interval=cfg["interval"], limit=cfg["limit"])
        if df.empty or 'volume' not in df.columns:
            issues.append("❌ 데이터프레임 비어 있음 or volume 누락")
            raise Exception("중단")  # 더 아래 계산은 무의미하니까

        df['volume_ma'] = df['volume'].rolling(cfg["vol_ma_window"]).mean()
        df['ma'] = df['close'].rolling(cfg["disparity_ma"]).mean()
        df.dropna(inplace=True)

        if len(df) < cfg["lookback"] + cfg["price_lookback"]:
            issues.append("❌ 유효 캔들 부족")

        recent = df.iloc[-cfg["lookback"]:].copy()
        recent_spike = recent[recent['volume'] > recent['volume_ma'] * cfg["spike_multiplier"]]
        if recent_spike.empty:
            issues.append(f"📉 거래량 스파이크 없음 (최근 {cfg['lookback']}봉 기준)")

        latest = df.iloc[-1]
        
        disparity = (latest['close'] / latest['ma']) * 100
        # if not (disparity < (100 - cfg["disparity_thresh"]) or disparity > (100 + cfg["disparity_thresh"])):
            # issues.append(f"⚖️ 이격도 부족 ({round(disparity, 2)}%)")

        # recent_close = df['close'].iloc[-cfg["price_lookback"]]
        # price_slope = ((latest['close'] - recent_close) / recent_close) * 100
        # if abs(price_slope) < cfg["min_price_slope_pct"]:
            # issues.append(f"📈 가격 기울기 부족 ({round(price_slope, 3)}%)")

        #price_lookback = cfg["price_lookback"]
        #lowest_open = df['open'].iloc[-price_lookback:].min()
        #highest_close = df['close'].iloc[-price_lookback:].max()
        
        #price_slope = ((highest_close - lowest_open) / lowest_open) * 100
        
        #if price_slope < cfg["min_price_slope_pct"]:
            #issues.append(f"📉 가격 폭발 부족 (최저시가→최고종가 {round(price_slope, 2)}%)")
            
        price_lookback = cfg["price_lookback"]

        # 가장 낮은 시가, 가장 높은 종가
        lowest_open = df['open'].iloc[-price_lookback:].min()
        highest_close = df['close'].iloc[-price_lookback:].max()
        price_slope = ((highest_close - lowest_open) / lowest_open) * 100
        
        # 최근 평균 변동률 계산
        avg_pct_move = df['close'].pct_change().abs().rolling(price_lookback).mean().iloc[-1] * 100
        required_slope = avg_pct_move * cfg["volatility_multiplier"]
        
        # 조건 비교
        if price_slope < required_slope:
            issues.append(f"📉 과열 부족 (가격 스파이크 {round(price_slope, 2)}% < 평균의 {cfg['volatility_multiplier']}배: {round(required_slope, 2)}%)")
        
        
        # 조건 모두 통과 → 진입 신호 리턴
        if not issues:
            return {
                'symbol': symbol,
                'price': latest['close'],
                'ma': latest['ma'],
                'disparity': disparity,
                'volume': latest['volume'],
                'volume_ma': latest['volume_ma'],
                'direction': 'LONG' if disparity < 100 else 'SHORT'
            }

        # 조건 실패 이유 메시지
        if cfg.get("notify_on_error", True):
            msg = f"⚠️ [{symbol}] 조건 불충족:\n" + "\n".join(issues)
            send_telegram_message(msg)

        return None

    except Exception as e:
        if str(e) != "중단" and cfg.get("notify_on_error", True):
            send_telegram_message(f"💥 [{symbol}] 예외 발생: {str(e)}")
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
            # send_telegram_message("🙅‍♂️ 예측 조건을 만족하는 종목이 없습니다. (볼륨 + 이격도 기준)")
    except Exception as e:
        send_telegram_message(f"⚠️ 스파이크 예측 리포트 실패: {str(e)}")

# 자동 감시 루프
def spike_watcher_loop():
    while True:
        report_spike_disparity()
        time.sleep(60)  # 1분 주기