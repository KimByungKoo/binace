from utils.binance import get_top_symbols, get_1m_klines,client
from utils.telegram import send_telegram_message
import time
from config import SPIKE_CONFIG as cfg
from order_manager import auto_trade_from_signal

import pandas as pd



def check_volume_spike_disparity(symbol):
    issues = [] 

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

        
        if "five_green_ma5" in cfg["checks"]:
            df['ma5'] = df['close'].rolling(5).mean()
            df['ma20'] = df['close'].rolling(20).mean()
            df['ma30'] = df['close'].rolling(30).mean()

            # recent_rows = df.iloc[-5:]
            recent_rows = df.iloc[-6:-1]  # <-- 1봉 전까지 5개 봉
            green_count = (recent_rows['close'] > recent_rows['open']).sum()
            above_ma_count = (recent_rows['close'] > recent_rows['ma5']).sum()

            # 각 봉의 고저 변동률 계산
            volatilities = ((recent_rows['high'] - recent_rows['low']) / recent_rows['low']) * 100
            volatility_exceeds = (volatilities >= 1).sum()

            # 정배열 / 역배열 확인
            is_bullish_alignment = df['ma5'].iloc[-1] > df['ma20'].iloc[-1] > df['ma30'].iloc[-1]
            is_bearish_alignment = df['ma5'].iloc[-1] < df['ma20'].iloc[-1] < df['ma30'].iloc[-1]

            # 진입 조건
            if ((green_count == 5 and above_ma_count == 5 and is_bullish_alignment) or
                (green_count == 0 and above_ma_count == 0 and is_bearish_alignment)) and volatility_exceeds == 0:

                direction = "long" if green_count == 5 else "short"
                send_telegram_message(
                    f"💡 *{symbol}* 5봉 모멘텀 + 정배열 포착\n"
                    f"   ├ 방향: `{direction.upper()}`\n"
                    f"   └ 현재가: `{latest_price}`"
                )

                signal = {
                    "symbol": symbol,
                    "direction": direction,
                    "price": latest_price,
                    "take_profit": latest_price * (1.02 if direction == "long" else 0.98),
                    "stop_loss": latest_price * (0.99 if direction == "long" else 1.01)
                }
                auto_trade_from_signal(signal)

            else:
                reason = []
                if green_count != 5 and green_count != 0:
                    reason.append(f"green_count: {green_count}")
                if above_ma_count != 5 and above_ma_count != 0:
                    reason.append(f"above_ma_count: {above_ma_count}")
                if volatility_exceeds > 0:
                    reason.append(f"과열봉 수: {volatility_exceeds}")
                if green_count == 5 and not is_bullish_alignment:
                    reason.append("정배열 아님")
                if green_count == 0 and not is_bearish_alignment:
                    reason.append("역배열 아님")

                send_telegram_message(
                    f"💡 *{symbol}* 5봉 모멘텀 조건 미달\n" +
                    "\n".join([f"   ├ {r}" for r in reason])
                )


        if "close_above_ma7" in cfg["checks"]:
            df['ma7'] = df['close'].rolling(7).mean()
            if pd.isna(df['ma7'].iloc[-1]):
                issues.append("MA7 계산 불가")
            elif latest_price < df['ma7'].iloc[-1]:
                issues.append("❌ 현재가가 MA7 아래")

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


def get_top_disparity_symbols(n=5):
    symbols = get_top_symbols()  # 유동성 좋은 종목 중에서만
    results = []

    for symbol in symbols:
        try:
            df = get_1m_klines(symbol, interval="1m", limit=20)
            if df.empty or 'close' not in df.columns:
                continue

            df['ma7'] = df['close'].rolling(7).mean()
            last_close = df['close'].iloc[-2]  # 전봉 기준
            ma7 = df['ma7'].iloc[-2]

            if pd.isna(ma7) or ma7 == 0:
                continue

            disparity = abs((last_close - ma7) / ma7) * 100
            results.append({
                "symbol": symbol,
                "close": last_close,
                "ma7": ma7,
                "disparity": disparity
            })
        except Exception as e:
            continue

    sorted_list = sorted(results, key=lambda x: x['disparity'], reverse=True)
    return sorted_list[:n]


def report_top_1m_disparities():
    top_disparities = get_top_disparity_symbols(5)

    if not top_disparities:
        send_telegram_message("⚠️ 1분봉 이격도 TOP5 분석 실패 or 데이터 부족")
        return

    msg = "📊 *1분봉 MA7 이격도 TOP5*\n\n"
    for item in top_disparities:
        msg += (
            f"*{item['symbol']}*\n"
            f"   ├ 현재가: `{round(item['close'], 4)}`\n"
            f"   ├ MA7   : `{round(item['ma7'], 4)}`\n"
            f"   └ 이격도: `{round(item['disparity'], 2)}%`\n\n"
        )

    send_telegram_message(msg)

# 수동 리포트 호출용
def report_spike_disparity():
    try:
        symbols = get_top_symbols(cfg["top_n"])
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



def get_15m_ma90_disparity_symbols():
    """
    15분봉 기준 MA90 대비 이격도 102% 초과 or 98% 미만 종목 필터링
    Returns: list of (symbol, price, ma90, disparity_pct)
    """
    try:
        tickers = client.futures_ticker()
        symbols = [t['symbol'] for t in tickers if t['symbol'].endswith("USDT") and "DOWN" not in t['symbol'] and "UP" not in t['symbol']]

        result = []
        for symbol in symbols:
            try:
                df = get_1m_klines(symbol, interval="15m", limit=100)
                df['ma90'] = df['close'].rolling(90).mean()
                ma90 = df['ma90'].iloc[-1]
                price = df['close'].iloc[-1]

                if pd.isna(ma90) or ma90 == 0:
                    continue

                disparity = (price / ma90) * 100

                if disparity > 102 or disparity < 98:
                    result.append((symbol, round(price, 4), round(ma90, 4), round(disparity, 2)))
            except Exception as e:
                print(f"❌ {symbol} 처리 실패: {e}")
                continue

        return result

    except Exception as e:
        send_telegram_message(f"💥 15분봉 MA90 이격도 분석 실패: {e}")
        return []

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
    
    
# ta 라이브러리는 Wilder 방식이 반영돼 있음
import pandas_ta as ta



def calculate_rsi(df, period=7):
    delta = df['close'].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi

def check_reverse_spike_condition(symbol, test_mode=True):
    """
    과매수/과매도 상황을 역추세로 판단하여 매매 신호 생성 및 자동 매수 수행.

    조건:
    - 거래량 스파이크 (volume > volume_ma * N배)
    - 시가가 MA7 대비 cfg["disparity_thresh"] 이상 이격
    - 양봉(open < close) + 시가 MA7 위 or
      음봉(open > close) + 시가 MA7 아래
    - MA7 > MA20 > MA30 > MA60 (정배열) → 매도
      MA7 < MA20 < MA30 < MA60 (역배열) → 매수

    자동 매수 실행 시:
    - 익절 1.5%
    - 손절 1.0%
    """
    issues = []

    try:
        #send_telegram_message(f"check_reverse_spike_condition{symbol}")
        df = get_1m_klines(symbol, interval=cfg["interval"], limit=cfg["ma_window"] + 1)
        if df.empty or 'volume' not in df.columns:
            issues.append("❌ 데이터 비어있음 또는 거래량 없음")
            raise Exception("중단")

        # 이동평균선 계산
        df['ma7'] = df['close'].rolling(7).mean()
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma30'] = df['close'].rolling(30).mean()
        df['ma60'] = df['close'].rolling(60).mean()
        df['volume_ma'] = df['volume'].rolling(cfg["vol_ma_window"]).mean()
        # 거래량 기준선 계산
        df['volume_ema'] = df['volume'].ewm(span=cfg["vol_ma_window"]).mean()
        df['volume_std'] = df['volume'].rolling(cfg["vol_ma_window"]).std()

        df.dropna(inplace=True)

        latest = df.iloc[-1]
        
        price = latest['close']
        open_price = latest['open']
        ma7 = latest['ma7']
        
        ma20 = latest['ma20']
        ma30 = latest['ma30']
        ma60 = latest['ma60']

        
        # 거래량 스파이크
        volume = latest['volume']
        volume_ma = latest['volume_ma']
        required_volume = volume_ma * cfg["spike_multiplier"]
        
        # print(f"DEBUG: {symbol} 최근 데이터: {latest}")
        
        
        
        ema = latest['volume_ema']
        
        std = latest['volume_std']
        
        threshold = ema + std * cfg["spike_std_multiplier"]
        
        # print(f"DEBUG: {symbol} 거래량 기준선: {threshold}, 현재 거래량: {latest['volume']}")
        # print(f"DEBUG: {symbol} 거래량 기준선: {latest['volume']} < {threshold}")
        if latest['volume'] < threshold:
            
            issues.append(
                f"❌ 거래량 스파이크 아님\n"
                f"   ├ 현재 거래량   : `{round(latest['volume'], 2)}`\n"
                f"   ├ 기준치       : `{round(threshold, 2)}` (EMA+STD)"
            )
        """
        else:
            print(f"😇😇😇😌😌: {symbol} 거래량 스파이크 감지됨")
            send_telegram_message(
                f"✅ 거래량 스파이크 감지\n"
                f"   ├ {symbol} \n"
                f"   ├ 현재 거래량   : `{round(latest['volume'], 2)}`\n"
                f"   ├ EMA 기준선   : `{round(ema, 2)}`\n"
                f"   ├ STD x {cfg['spike_std_multiplier']} : `{round(std * cfg['spike_std_multiplier'], 2)}`\n"
                f"   └ 기준치       : `{round(threshold, 2)}`"
            )
        """
        # RSI 추가 계산
        
        df['rsi'] = ta.rsi(df['close'], length=cfg["rsi_period"])
        #df['rsi'] = calculate_rsi(df, period=cfg["rsi_period"])

        # 최신 RSI 가져오기
        latest_rsi = df['rsi'].iloc[-1]

        msg = (
            f"📊 *{symbol} RSI 상태 보고*\n"
            f"   ├ RSI: `{round(latest_rsi, 2)}`\n"
            f"   ├ 기준: `기간 {cfg['rsi_period']} / 임계치 {cfg['rsi_threshold']}`\n"
        )
        print(f"DEBUG: {symbol} RSI: {latest_rsi}, 기준: {cfg['rsi_threshold']}")

        
        if(latest_rsi< cfg["rsi_threshold"]+5 or latest_rsi> 100-cfg["rsi_threshold"]-5):
            test = f"   {symbol} 📉 *RSI 근처 감지* → `{round(latest_rsi, 2)} `"
            send_telegram_message(test)
            
        
        if latest_rsi < cfg["rsi_threshold"]:
            msg += f"   └ 📉 *과매도 감지* → `{round(latest_rsi, 2)} < {cfg['rsi_threshold']}`"
            send_telegram_message(msg)
            signal = {
                "symbol": symbol,
                "direction": 'long',
                "price": price,
            
              
                "volume": round(latest['volume'], 2),
                "volume_ma": round(latest['volume_ma'], 2),
                "pass": True
            }
            auto_trade_from_signal(signal)
        elif latest_rsi > (100 - cfg["rsi_threshold"]):
            msg += f"   └ 📈 *과매수 감지* → `{round(latest_rsi, 2)} > {100 - cfg['rsi_threshold']}`"
            send_telegram_message(msg)
            signal = {
                "symbol": symbol,
                "direction": 'short',
                "price": price,
            
               
                "volume": round(latest['volume'], 2),
                "volume_ma": round(latest['volume_ma'], 2),
                "pass": True
            }
            auto_trade_from_signal(signal)
        



        
        #if volume < required_volume:
            #issues.append(
                #f"❌ 거래량 스파이크 아님 "
                #f"(현재: {round(volume, 2)}, 기준: {round(required_volume, 2)} / MA: {round(volume_ma, 2)} x {cfg['spike_multiplier']})"
            #)
        # MA7 이격 조건
        disparity = abs(open_price - ma7) / ma7 * 100
        if disparity < cfg["min_disparity_pct"]:
            issues.append(f"❌ MA7 이격률 부족 ({round(disparity, 2)}%)")

        # 캔들 색상
        candle = "green" if price > open_price else "red"
        if candle == "green" and open_price < ma7:
            issues.append("❌ 양봉인데 MA7 아래 시가")
        elif candle == "red" and open_price > ma7:
            issues.append("❌ 음봉인데 MA7 위 시가")

        # MA 배열
        if open_price > ma7:
            if ma7 > ma20 > ma30 > ma60:
                direction = "short"  # 과매수니까 숏
            else:
                issues.append("❌ 시가 > MA7인데 정배열 아님")
                direction = None
        elif open_price < ma7:
            if ma7 < ma20 < ma30 < ma60:
                direction = "long"  # 과매도니까 롱
            else:
                issues.append("❌ 시가 < MA7인데 역배열 아님")
                direction = None
        else:
            issues.append("❌ 시가와 MA7이 동일 — 애매한 상태")
            direction = None
    
    

        # 조건 통과
        if not issues and direction:
            #if has_open_position(symbol):
                #if test_mode:
                    #send_telegram_message(f"⛔ {symbol} 이미 포지션 보유 중 → 스킵")
                #return None, []

            tp = price * (1.015 if direction == "long" else 0.985)
            sl = price * (0.99 if direction == "long" else 1.01)

            signal = {
                "symbol": symbol,
                "direction": direction,
                "price": price,
                "take_profit": tp,
                "stop_loss": sl,
                "disparity": round(disparity, 2),
                "volume": round(latest['volume'], 2),
                "volume_ma": round(latest['volume_ma'], 2),
                "pass": True
            }

            msg = (
                f"✅ *{symbol} 역스파이크 진입 조건 충족*\n"
                f"   ├ 방향: `{direction.upper()}`\n"
                f"   ├ 현재가: `{round(price, 4)}`\n"
                f"   ├ 이격률: `{round(disparity, 2)}%`\n"
                f"   ├ 거래량: `{round(latest['volume'], 2)}` vs MA: `{round(latest['volume_ma'], 2)}`\n"
                # f"   └ MA배열: {'정배열' if ma_bullish else '역배열'}"
            )
            #send_telegram_message(msg)

            #auto_trade_from_signal(signal)
            return signal, []

        # 실패한 경우
        #if test_mode and issues:
            #msg = f"⚠️ [{symbol}] 역스파이크 조건 미충족:\n" + "\n".join([f"   ├ {i}" for i in issues])
            #send_telegram_message(msg)

        return None, issues if issues else []

    except Exception as e:
        send_telegram_message(f"💥387 [{symbol}] 예외 발생: {e}")
        return None, []
        
        
def report_spike():
    try:
        symbols = get_top_symbols(cfg["top_n"])
        #send_telegram_message(f"✅ 가져온 심볼: {symbols}")

        if not symbols:
            send_telegram_message("❌ 심볼 리스트 비어있음 → 루프 진입 안 함")
            return
        msg = "📈 *볼륨 스파이크 + 이격 과열 감지 리스트*\n\n"
        found = False
        
        
        #send_telegram_message(f"✅ 가져온 심볼: {1}")
        for symbol in symbols:
            result, issues = check_reverse_spike_condition(symbol,False)

            if result is None and not issues:
                send_telegram_message(f"⛔ {symbol} → 결과 없음 (result=None, issues=None)")
            # elif result is None:
            #     if len(issues) < 6:
            #         send_telegram_message(f"⚠️ {symbol} → 조건 미충족:\n" + "\n".join([f"   ├ {i}" for i in issues]))
            #else:
                #send_telegram_message(f"✅ {symbol} 조건 만족")
        
            #result, issues = output
        
            #if issues:
                #msg = f"⚠️ [{symbol}] 조건 미달:\n" + "\n".join([f"   ├ {i}" for i in issues])
                #send_telegram_message(msg)
                #continue
        
            if result and result.get("pass"):
                send_telegram_message(
                    f"🔁 *{result['symbol']} 역추세 진입 조건 충족*\n"
                    f"   ├ 방향    : `{result['direction'].upper()}`\n"
                    f"   ├ 현재가  : `{result['price']}`\n"
                    f"   ├ 이격도  : `{result['disparity']}%`\n"
                    f"   ├ 볼륨    : `{result['volume']}` / MA: `{result['volume_ma']}`\n"
                    f"   └ 전략    : `이격 + 스파이크 반대매매`"
                )
    
        bb_hits = get_bb_continuous_touch(symbols)
    
        if bb_hits:
            msg = "🔍 *BB 상/하단 연속 터치 종목 (1분봉)*\n"
            for x in bb_hits:
                msg += f"   ├ {x['symbol']} → `{x['type'].upper()}` {x['streak']}봉 연속\n"
            send_telegram_message(msg)
    
    except Exception as e:
        send_telegram_message(f"⚠️ 스파이크 예측 리포트 실패: {str(e)}")

def get_bb_continuous_touch(symbols, interval="3m", lookback=20, bb_period=66, bb_std=2):
    results = []

    for symbol in symbols:
        try:
            df = get_1m_klines(symbol, interval=interval, limit=bb_period + lookback)
            if df.empty or len(df) < bb_period + lookback:
                continue

            df['ma'] = df['close'].rolling(bb_period).mean()
            df['std'] = df['close'].rolling(bb_period).std()
            df['upper'] = df['ma'] + bb_std * df['std']
            df['lower'] = df['ma'] - bb_std * df['std']

            # 최근 10봉 (현재 포함)
            last_n = df.iloc[-10:]
            upper_flags = (last_n['close'] >= last_n['upper']).tolist()
            lower_flags = (last_n['close'] <= last_n['lower']).tolist()

            def count_consecutive(touches):
                count = 0
                for touched in reversed(touches):  # 현재봉부터 거꾸로
                    if touched:
                        count += 1
                    else:
                        break
                return count

            up_count = count_consecutive(upper_flags)
            low_count = count_consecutive(lower_flags)

            if up_count >= 3:
                results.append({"symbol": symbol, "type": "upper", "streak": up_count})
            elif low_count >= 3:
                results.append({"symbol": symbol, "type": "lower", "streak": low_count})

        except Exception as e:
            send_telegram_message(f"⚠️ {symbol} BB 연속 감시 실패: {e}")

    # 상단 유지 먼저, 연속 개수 오름차순 정렬
    return sorted(results, key=lambda x: (x['type'] != 'upper', x['streak']))

# 자동 감시 루프
def spike_watcher_loop():
    send_telegram_message(f"😀 spike_watcher_loop")
    while True:
        report_spike()
        #report_spike_disparity()
        #report_top_1m_disparities()
        time.sleep(10)  # 1분 주기