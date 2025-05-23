from utils.binance import get_top_symbols, get_1m_klines
from utils.telegram import send_telegram_message
import time
from config import SPIKE_CONFIG as cfg
from order_manager import auto_trade_from_signal

def check_volume_spike_disparity(symbol):
    issues = []  # 실패 이유 리스트

    try:
        if not symbol:
            issues.append("❌ symbol 값이 없음")
            raise Exception("중단")

        df = get_1m_klines(symbol, interval=cfg["interval"], limit=cfg["limit"])
        if df.empty or 'volume' not in df.columns:
            issues.append("❌ 데이터프레임 비어 있음 or volume 누락")
            raise Exception("중단")

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
        latest_price = latest['close']
        disparity = (latest['close'] / latest['ma']) * 100

        if "disparity" in cfg["checks"]:
            if not (disparity < (100 - cfg["disparity_thresh"]) or disparity > (100 + cfg["disparity_thresh"])):
                issues.append(f"⚖️ 이격도 부족 ({round(disparity, 2)}%)")

        if "ma_order" in cfg["checks"] or "slope" in cfg["checks"]:
            df['ma5'] = df['close'].rolling(5).mean()
            df['ma20'] = df['close'].rolling(20).mean()
            df['ma30'] = df['close'].rolling(30).mean()
            df['ma90'] = df['close'].rolling(90).mean()

            ma5 = df['ma5'].iloc[-1]
            ma20 = df['ma20'].iloc[-1]
            ma30 = df['ma30'].iloc[-1]
            ma90 = df['ma90'].iloc[-1]

            is_long = ma5 > ma20 > ma30 > ma90 if "ma_order" in cfg["checks"] else ma5 > ma20 > ma30
            is_short = ma5 < ma20 < ma30 < ma90 if "ma_order" in cfg["checks"] else ma5 < ma20 < ma30
            direction = "long" if is_long else "short" if is_short else None

            if direction is None:
                issues.append("MA 배열이 정배열/역배열 아님")
        else:
            direction = None

        if "slope" in cfg["checks"]:
            recent_close = df['close'].iloc[-cfg["price_lookback"]]
            price_slope = ((latest['close'] - recent_close) / recent_close) * 100
            if abs(price_slope) < cfg["min_price_slope_pct"]:
                issues.append(f"📈 가격 기울기 부족 ({round(price_slope, 3)}%)")

        if "spike_strength" in cfg["checks"]:
            price_lookback = cfg["price_lookback"]
            lowest_open = df['open'].iloc[-price_lookback:].min()
            highest_close = df['close'].iloc[-price_lookback:].max()
            price_slope = ((highest_close - lowest_open) / lowest_open) * 100
            df['return_pct'] = df['close'].pct_change().abs() * 100
            avg_pct_move = df['return_pct'].rolling(price_lookback).mean().iloc[-1] * 100
            required_slope = avg_pct_move * cfg["volatility_multiplier"]
            if price_slope < required_slope:
                issues.append(f"📉 과열 부족 (가격 스파이크 {round(price_slope, 2)}% < 평균의 {cfg['volatility_multiplier']}배: {round(required_slope, 2)}%)")

        df['return_pct'] = df['close'].pct_change().abs() * 100
        median_disparity = df['return_pct'].median()
        hi = df['close'].iloc[-cfg["price_lookback"]:].max()
        lo = df['open'].iloc[-cfg["price_lookback"]:].min()
        vrange = (hi - lo) / lo * 100
        if vrange > median_disparity*cfg['volatility_multiplier']:
            send_telegram_message(f"📊 {symbol}  {round(vrange,2)}>{round(median_disparity*cfg['volatility_multiplier'], 2)} : 전봉값 > 중간값*3 %")

        if "volatility" in cfg["checks"]:
            if len(df) < cfg["price_lookback"] + 1:
                issues.append("봉 수 부족")
            else:
                current_start = df['open'].iloc[-cfg["price_lookback"]]
                current_ma = df['ma5'].iloc[-cfg["price_lookback"]] if 'ma5' in df else 0
                if direction == "long" and current_start < current_ma:
                    issues.append("롱인데 시작가가 MA5 아래")
                elif direction == "short" and current_start > current_ma:
                    issues.append("숏인데 시작가가 MA5 위")
                if vrange <  median_disparity:
                    issues.append(f"변동폭 부족: {round(vrange,2)}% < {median_disparity}%")

        #print("DEBUG: auto_execute =", cfg.get("auto_execute", True))
        #send_telegram_message(f"💡 auto_execute: *{cfg.get('auto_execute', True)}*")

        if "five_green_ma5" in cfg["checks"]:
            df['ma5'] = df['close'].rolling(5).mean()
            recent_rows = df.iloc[-5:]
            green_count = (recent_rows['close'] > recent_rows['open']).sum()
            above_ma_count = (recent_rows['close'] > recent_rows['ma5']).sum()

            if (green_count == 5 and above_ma_count == 5) or (green_count == 0 and above_ma_count == 0):
                direction = "long" if green_count == 5 else "short"
                send_telegram_message(
                    f"💡 *{symbol}* 5봉 모멘텀 포착\n"
                    f"   ├ 방향: `{direction.upper()}`\n"
                    f"   └ 현재가: `{latest_price}`"
                )
                
                
                send_telegram_message("55555")
                signal = {
                                "symbol": symbol,
                                "direction": direction,
                                "price": latest_price,
                                "take_profit": latest_price * (1.02 if direction == "long" else 0.98),
                                "stop_loss": latest_price * (0.99 if direction == "long" else 1.01)
                            }
                auto_trade_from_signal(signal)
                
             else:
                send_telegram_message(
                    f"💡 *{symbol}* 5봉 모멘텀 조건 미달\n"
                    f"   ├ green_count: `{green_count}`\n"
                    f"   └ above_ma_count: `{above_ma_count}`"
                )

        if not issues:
            return {
                'symbol': symbol,
                'price': latest['close'],
                'ma': latest['ma'],
                'disparity': disparity,
                'volume': latest['volume'],
                'volume_ma': latest['volume_ma'],
                'direction': 'LONG' if disparity < 100 else 'SHORT'
            }, []

        if cfg.get("notify_on_error", True):
            msg = f"⚠️ [{symbol}] 조건 불충족:\n" + "\n".join(issues)
            send_telegram_message(msg)

        return None, []

    except Exception as e:
        if str(e) != "중단" and cfg.get("notify_on_error", True):
            send_telegram_message(f"💥 [{symbol}] 예외 발생: {str(e)}")
        return None, []

# 수동 리포트 호출용
def report_spike_disparity():
    try:
        symbols = get_top_symbols(20)
        msg = "📈 *볼륨 스파이크 + 이격 과열 감지 리스트*\n\n"
        found = False
        
        for symbol in symbols:
            output = check_volume_spike_disparity(symbol)
            if not output:
                continue
            
            result, issues = output
            if result:
                found = True
                if cfg["auto_execute"]:
                    auto_trade_from_signal(result)
                msg += (
                    f"*{symbol}* → `{result['direction'].upper()}`\n"
                    f"   ├ 현재가      : `{round(result.get('price', 0), 4)}`\n"
                    f"   ├ MA90        : `{round(result.get('ma', 0), 4)}`\n"
                    f"   ├ 이격도      : `{round(result.get('disparity', 0), 2)}%`\n"
                    f"   ├ 거래량      : `{round(result.get('volume', 0), 2)}` vs 평균 `{round(result.get('volume_ma', 0), 2)}`\n"
                    f"   ├ 가격 기울기 : `{round(result.get('price_slope', 0), 2)}%`\n"
                    f"   └ 변동폭      : `{round(result.get('volatility', 0), 2)}%`\n\n"
                )
            elif len(issues) == 1:
                found = True
                msg += (
                    f"*{symbol}* ⚠️ 애매한 조건\n"
                    f"   └ `{issues[0]}`\n\n"
                )
        
        if found:
            send_telegram_message(msg)
        #else:
            #send_telegram_message("🔍 조건을 만족하는 종목이 없습니다.")
        #else:
            #send_telegram_message("🙅‍♂️ 예측 조건을 만족하는 종목이 없습니다. (볼륨 + 이격도 기준)")
    except Exception as e:
        send_telegram_message(f"⚠️ 스파이크 예측 리포트 실패: {str(e)}")



def check_disparity(symbol):
    df = get_klines(symbol, interval=cfg["interval"], limit=cfg["ma_window"] + 5)
    if df.empty or 'close' not in df.columns:
        return None

    df['ma'] = df['close'].rolling(cfg["ma_window"]).mean()
    latest_close = df['close'].iloc[-1]
    latest_ma = df['ma'].iloc[-1]

    if pd.isna(latest_ma) or latest_ma == 0:
        return None

    disparity = (latest_close / latest_ma) * 100
    if disparity >= cfg["disparity_threshold"]:
        return {
            "symbol": symbol,
            "close": latest_close,
            "ma": latest_ma,
            "disparity": disparity
        }
    return None
    
# 자동 감시 루프
def spike_watcher_loop():
    send_telegram_message(f"😀 spike_watcher_loop")
    while True:
        report_spike_disparity()
        time.sleep(60)  # 1분 주기