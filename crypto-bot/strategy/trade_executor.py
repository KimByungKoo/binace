# trade_executor.py
from datetime import datetime, timedelta
from utils.telegram import send_telegram_message
from order_manager import place_order, close_position, round_qty, auto_trade_from_signal
from utils.binance import get_top_symbols, get_1m_klines, client, has_open_position
import time
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from collections import deque
import json
import os

# client = Client("api_key", "api_secret")

# 포지션 상태 저장용 (전역 변수로 선언)
open_trades = {}

# 설정값
CONFIG = {
    "max_daily_loss_pct": 5.0,  # 일일 최대 손실 제한 (%)
    "max_position_size": 100,   # 최대 포지션 크기 (USDT)
    "min_position_size": 20,    # 최소 포지션 크기 (USDT)
    "volatility_window": 20,    # 변동성 계산 기간
    "volume_ma_window": 20,     # 거래량 이동평균 기간
    "min_volume_ratio": 1.5,    # 최소 거래량 비율 (평균 대비)
    "backtest_days": 7,         # 백테스트 기간 (일)
    "max_consecutive_losses": 3,  # 최대 연속 손실 횟수
    "max_open_positions": 5,    # 최대 동시 포지션 수
    "trading_hours": {          # 거래 시간 제한
        "start": "00:00",
        "end": "23:59"
    },
    "high_volatility_hours": [  # 변동성 높은 시간대 (UTC)
        "02:00-04:00",  # 뉴욕 마감 시간
        "14:00-16:00"   # 런던 마감 시간
    ]
}

# 일일 손실 추적
daily_stats = {
    "start_balance": None,
    "current_balance": None,
    "trades": [],
    "last_reset": None,
    "consecutive_losses": 0,    # 연속 손실 카운트
    "total_trades": 0,          # 총 거래 횟수
    "winning_trades": 0,        # 승리 거래 횟수
    "losing_trades": 0,         # 손실 거래 횟수
    "total_profit": 0,          # 총 수익
    "total_loss": 0,            # 총 손실
    "best_trade": None,         # 최고 수익 거래
    "worst_trade": None,        # 최대 손실 거래
    "trading_hours_stats": {}   # 시간대별 통계
}

# 시장 상황 분석
market_analysis = {
    "overall_trend": None,      # 전체 시장 트렌드
    "volatility_index": 0,      # 변동성 지수
    "correlation_groups": {},    # 상관관계 그룹
    "last_update": None
}

def is_trading_allowed() -> bool:
    """
    현재 시간이 거래 가능한 시간인지 확인
    """
    now = datetime.utcnow()
    current_time = now.strftime("%H:%M")
    
    # 기본 거래 시간 체크
    if not (CONFIG["trading_hours"]["start"] <= current_time <= CONFIG["trading_hours"]["end"]):
        return False
    
    # 변동성 높은 시간대 체크
    for period in CONFIG["high_volatility_hours"]:
        start, end = period.split("-")
        if start <= current_time <= end:
            return False
    
    return True

def update_market_analysis():
    """
    시장 상황 분석 업데이트
    """
    global market_analysis
    
    try:
        # 상위 20개 코인 데이터 수집
        symbols = get_top_symbols(20)
        if not symbols:
            return
        
        # 각 코인의 가격 데이터 수집
        price_data = {}
        for symbol in symbols:
            df = get_1m_klines(symbol, interval="1h", limit=24)
            if not df.empty:
                price_data[symbol] = df['close'].pct_change().dropna()
        
        # 전체 시장 트렌드 계산
        market_returns = pd.DataFrame(price_data).mean(axis=1)
        market_analysis["overall_trend"] = "up" if market_returns.mean() > 0 else "down"
        
        # 변동성 지수 계산
        market_analysis["volatility_index"] = market_returns.std() * 100
        
        # 상관관계 분석
        corr_matrix = pd.DataFrame(price_data).corr()
        market_analysis["correlation_groups"] = {}
        
        # 상관계수 0.7 이상인 그룹 찾기
        for symbol in symbols:
            if symbol not in market_analysis["correlation_groups"]:
                group = [s for s in symbols if corr_matrix.loc[symbol, s] > 0.7]
                if len(group) > 1:
                    market_analysis["correlation_groups"][symbol] = group
        
        market_analysis["last_update"] = datetime.utcnow()
        
    except Exception as e:
        send_telegram_message(f"⚠️ 시장 분석 업데이트 실패: {str(e)}")

def generate_performance_report() -> str:
    """
    성과 리포트 생성
    """
    if not daily_stats["trades"]:
        return "거래 내역이 없습니다."
    
    total_trades = len(daily_stats["trades"])
    win_rate = (daily_stats["winning_trades"] / total_trades * 100) if total_trades > 0 else 0
    profit_factor = abs(daily_stats["total_profit"] / daily_stats["total_loss"]) if daily_stats["total_loss"] != 0 else float('inf')
    
    # 시간대별 통계
    hour_stats = {}
    for trade in daily_stats["trades"]:
        hour = trade["timestamp"].hour
        if hour not in hour_stats:
            hour_stats[hour] = {"trades": 0, "profit": 0}
        hour_stats[hour]["trades"] += 1
        hour_stats[hour]["profit"] += trade["pnl"]
    
    best_hour = max(hour_stats.items(), key=lambda x: x[1]["profit"] / x[1]["trades"])[0] if hour_stats else None
    
    report = f"""
📊 *일일 거래 리포트*
├ 총 거래 횟수: `{total_trades}`
├ 승률: `{win_rate:.1f}%`
├ 수익률: `{(daily_stats["total_profit"] + daily_stats["total_loss"]) / daily_stats["start_balance"] * 100:.1f}%`
├ 손익비: `{profit_factor:.2f}`
├ 최고 수익: `{daily_stats["best_trade"]["pnl"]:.2f} USDT` ({daily_stats["best_trade"]["symbol"]})
├ 최대 손실: `{daily_stats["worst_trade"]["pnl"]:.2f} USDT` ({daily_stats["worst_trade"]["symbol"]})
└ 최적 거래 시간: `{best_hour:02d}:00 UTC`
"""
    return report

def save_trade_history():
    """
    거래 내역 저장
    """
    try:
        history_file = "trade_history.json"
        history = []
        
        if os.path.exists(history_file):
            with open(history_file, 'r') as f:
                history = json.load(f)
        
        # 오늘의 거래 내역 추가
        history.append({
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "trades": daily_stats["trades"],
            "summary": {
                "total_trades": len(daily_stats["trades"]),
                "win_rate": (daily_stats["winning_trades"] / len(daily_stats["trades"]) * 100) if daily_stats["trades"] else 0,
                "total_profit": daily_stats["total_profit"],
                "total_loss": daily_stats["total_loss"]
            }
        })
        
        with open(history_file, 'w') as f:
            json.dump(history, f, indent=2)
            
    except Exception as e:
        send_telegram_message(f"⚠️ 거래 내역 저장 실패: {str(e)}")

def calculate_position_size(symbol: str, price: float, volatility: float) -> float:
    """
    변동성에 따른 포지션 크기 계산
    """
    base_size = CONFIG["max_position_size"]
    # 변동성이 높을수록 포지션 크기 감소
    volatility_factor = 1 / (1 + volatility)
    position_size = base_size * volatility_factor
    
    # 최소/최대 제한 적용
    return max(min(position_size, CONFIG["max_position_size"]), CONFIG["min_position_size"])

def calculate_volatility(df: pd.DataFrame) -> float:
    """
    변동성 계산 (ATR 기반)
    """
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    return df['tr'].rolling(CONFIG["volatility_window"]).mean().iloc[-1] / df['close'].iloc[-1]

def check_volume_condition(df: pd.DataFrame) -> bool:
    """
    거래량 조건 체크
    """
    df['volume_ma'] = df['volume'].rolling(CONFIG["volume_ma_window"]).mean()
    current_volume = df['volume'].iloc[-1]
    avg_volume = df['volume_ma'].iloc[-1]
    
    return current_volume > avg_volume * CONFIG["min_volume_ratio"]

def check_daily_loss_limit() -> bool:
    """
    일일 손실 제한 체크
    """
    global daily_stats
    
    now = datetime.utcnow()
    
    # 일일 통계 초기화
    if daily_stats["last_reset"] is None or (now - daily_stats["last_reset"]).days >= 1:
        account = client.futures_account()
        daily_stats["start_balance"] = float(account['totalWalletBalance'])
        daily_stats["current_balance"] = daily_stats["start_balance"]
        daily_stats["trades"] = []
        daily_stats["last_reset"] = now
        return True
    
    # 현재 손실률 계산
    current_loss_pct = (daily_stats["start_balance"] - daily_stats["current_balance"]) / daily_stats["start_balance"] * 100
    
    return current_loss_pct < CONFIG["max_daily_loss_pct"]

def update_daily_stats(trade_result: Dict):
    """
    일일 통계 업데이트
    """
    global daily_stats
    daily_stats["trades"].append(trade_result)
    daily_stats["current_balance"] = float(client.futures_account()['totalWalletBalance'])

def backtest_strategy(symbol: str, days: int = CONFIG["backtest_days"]) -> Dict:
    """
    전략 백테스팅
    """
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=days)
    
    # 과거 데이터 수집
    df = get_1m_klines(symbol, interval="3m", limit=days * 480)  # 3분봉 기준
    
    if df.empty:
        return {"error": "데이터 없음"}
    
    results = {
        "trades": [],
        "win_rate": 0,
        "profit_factor": 0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "total_profit": 0,
        "total_loss": 0
    }
    
    for i in range(len(df) - 120):  # 최소 120봉 필요
        window = df.iloc[i:i+120]
        wave_info = analyze_wave_from_df(window)
        
        if wave_info:
            entry_price = window.iloc[-1]['close']
            direction = "long" if wave_info['direction'] == "up" else "short"
            
            # TP/SL 계산
            tp_ratio = 1.015 if direction == "long" else 0.985
            sl_ratio = 0.985 if direction == "long" else 1.015
            
            tp = entry_price * tp_ratio
            sl = entry_price * sl_ratio
            
            # 이후 가격 움직임 확인
            future_prices = df.iloc[i+120:i+240]['close']
            
            for price in future_prices:
                if (direction == "long" and price >= tp) or (direction == "short" and price <= tp):
                    results["trades"].append({
                        "type": "win",
                        "entry": entry_price,
                        "exit": price,
                        "direction": direction
                    })
                    results["winning_trades"] += 1
                    results["total_profit"] += abs(price - entry_price)
                    break
                elif (direction == "long" and price <= sl) or (direction == "short" and price >= sl):
                    results["trades"].append({
                        "type": "loss",
                        "entry": entry_price,
                        "exit": price,
                        "direction": direction
                    })
                    results["losing_trades"] += 1
                    results["total_loss"] += abs(price - entry_price)
                    break
    
    results["total_trades"] = len(results["trades"])
    if results["total_trades"] > 0:
        results["win_rate"] = results["winning_trades"] / results["total_trades"] * 100
        results["profit_factor"] = results["total_profit"] / results["total_loss"] if results["total_loss"] > 0 else float('inf')
    
    return results

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
    try:
        # 거래 시간 체크
        if not is_trading_allowed():
            send_telegram_message(f"⏰ {symbol} 거래 시간 외 → 진입 생략")
            return

        # 최대 포지션 수 체크
        if len(open_trades) >= CONFIG["max_open_positions"]:
            send_telegram_message(f"⚠️ 최대 포지션 수 도달: {symbol} 진입 생략")
            return

        # 연속 손실 체크
        if daily_stats["consecutive_losses"] >= CONFIG["max_consecutive_losses"]:
            send_telegram_message(f"⚠️ 연속 손실 한도 도달: {symbol} 진입 생략")
            return

        # 일일 손실 제한 체크
        if not check_daily_loss_limit():
            send_telegram_message(f"⚠️ 일일 손실 제한 도달: {symbol} 진입 생략")
            return

        # 이미 포지션이 있는지 한번 더 확인
        if has_open_position(symbol):
            send_telegram_message(f"⛔ {symbol} 이미 보유 중 → 진입 생략")
            return

        # 거래량 조건 체크
        df = get_1m_klines(symbol, interval="3m", limit=CONFIG["volume_ma_window"] + 1)
        if not check_volume_condition(df):
            send_telegram_message(f"⚠️ {symbol} 거래량 부족 → 진입 생략")
            return

        # 변동성 계산 및 포지션 크기 결정
        volatility = calculate_volatility(df)
        position_size = calculate_position_size(symbol, price, volatility)

        mode = determine_trade_mode_from_wave(wave_info)
        direction = "long" if wave_info['direction'] == "up" else "short"

        qty = round_qty(symbol, position_size / price)
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
        
        # 주문 실행 전에 한번 더 포지션 체크
        if not has_open_position(symbol):
            auto_trade_from_signal(signal)
            
            open_trades[symbol] = {
                "entry_time": datetime.utcnow(),
                "entry_price": price,
                "direction": direction,
                "tp": tp,
                "sl": sl,
                "qty": qty,
                "mode": mode,
                "position_size": position_size
            }

            send_telegram_message(f"🚀 진입 완료: {symbol} ({mode.upper()})\n"
                                f"   ├ 방향     : `{direction}`\n"
                                f"   ├ 현재가   : `{round(price, 4)}`\n"
                                f"   ├ TP       : `{round(tp, 4)}`\n"
                                f"   ├ SL       : `{round(sl, 4)}`\n"
                                f"   ├ 수량     : `{round(qty, 4)}`\n"
                                f"   ├ 변동성   : `{round(volatility * 100, 2)}%`\n"
                                f"   └ 모드     : `{mode}`")

    except Exception as e:
        send_telegram_message(f"💥 진입 실패: {symbol} - {str(e)}")

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
            
            # 실제 포지션이 있는지 확인
            if not has_open_position(symbol):
                if symbol in open_trades:
                    del open_trades[symbol]
                continue

            df = get_1m_klines(symbol, interval="1m", limit=1)
            if df.empty:
                continue
                
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
                
                # 거래 결과 기록
                pnl = (last_price - trade['entry_price']) * qty if direction == "long" else (trade['entry_price'] - last_price) * qty
                trade_result = {
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": trade['entry_price'],
                    "exit_price": last_price,
                    "qty": qty,
                    "pnl": pnl,
                    "reason": exit_reason,
                    "timestamp": datetime.utcnow()
                }
                
                # 통계 업데이트
                daily_stats["total_trades"] += 1
                if pnl > 0:
                    daily_stats["winning_trades"] += 1
                    daily_stats["total_profit"] += pnl
                    daily_stats["consecutive_losses"] = 0
                    if daily_stats["best_trade"] is None or pnl > daily_stats["best_trade"]["pnl"]:
                        daily_stats["best_trade"] = trade_result
                else:
                    daily_stats["losing_trades"] += 1
                    daily_stats["total_loss"] += abs(pnl)
                    daily_stats["consecutive_losses"] += 1
                    if daily_stats["worst_trade"] is None or pnl < daily_stats["worst_trade"]["pnl"]:
                        daily_stats["worst_trade"] = trade_result
                
                # 시간대별 통계 업데이트
                hour = trade_result["timestamp"].hour
                if hour not in daily_stats["trading_hours_stats"]:
                    daily_stats["trading_hours_stats"][hour] = {"trades": 0, "profit": 0}
                daily_stats["trading_hours_stats"][hour]["trades"] += 1
                daily_stats["trading_hours_stats"][hour]["profit"] += pnl
                
                update_daily_stats(trade_result)
                
                send_telegram_message(f"{exit_reason}\n"
                                    f"   ├ 종목     : `{symbol}`\n"
                                    f"   ├ 방향     : `{direction}`\n"
                                    f"   ├ 진입가   : `{round(trade['entry_price'], 4)}`\n"
                                    f"   ├ 현재가   : `{round(last_price, 4)}`\n"
                                    f"   ├ 수익금   : `{round(pnl, 2)} USDT`\n"
                                    f"   └ 모드     : `{trade['mode']}`")
                
                # 딕셔너리에서 항목 제거
                if symbol in open_trades:
                    del open_trades[symbol]

        except Exception as e:
            send_telegram_message(f"💥 청산 감시 오류: {symbol} - {str(e)}")
            # 오류 발생 시 해당 심볼 제거
            if symbol in open_trades:
                del open_trades[symbol]

def wave_trade_watcher():
    """
    ✅ 파동 기반 트레이드 감시 루프
    - 시총 상위 심볼 대상으로 주기적으로 파동 분석
    - 진입 조건 만족 시 자동 진입
    """
    send_telegram_message("🌊 파동 기반 진입 감시 시작...")

    refresh_open_trades_from_binance()
    consecutive_errors = 0  # 연속 에러 카운트
    last_report_time = datetime.utcnow()
    last_market_analysis_time = datetime.utcnow()

    while True:
        try:
            # 시장 분석 업데이트 (1시간마다)
            if (datetime.utcnow() - last_market_analysis_time).total_seconds() > 3600:
                update_market_analysis()
                last_market_analysis_time = datetime.utcnow()
            
            # 일일 리포트 생성 (자정에)
            if (datetime.utcnow() - last_report_time).total_seconds() > 86400:
                report = generate_performance_report()
                send_telegram_message(report)
                save_trade_history()
                last_report_time = datetime.utcnow()

            symbols = get_top_symbols(20)  # 시총 상위 20종목
            if not symbols:
                send_telegram_message("⚠️ 심볼 목록을 가져오지 못했습니다.")
                time.sleep(30)
                continue

            for symbol in symbols:
                try:
                    # 백테스트 실행 (선택적)
                    if CONFIG["backtest_days"] > 0:
                        backtest_results = backtest_strategy(symbol)
                        if backtest_results.get("win_rate", 0) < 50:  # 승률 50% 미만이면 스킵
                            continue

                    df = get_1m_klines(symbol, interval="3m", limit=120)  # 3분봉 기준
                    if df.empty or len(df) < 60:
                        continue

                    wave_info = analyze_wave_from_df(df)
                    if not wave_info:
                        continue

                    price = df.iloc[-1]['close']
                    enter_trade_from_wave(symbol, wave_info, price)

                except Exception as e:
                    send_telegram_message(f"⚠️ {symbol} 처리 중 오류: {str(e)}")
                    continue

            consecutive_errors = 0  # 성공 시 에러 카운트 리셋
            time.sleep(60)  # 1분 주기로 갱신

        except Exception as e:
            consecutive_errors += 1
            error_msg = f"💥 파동 감시 오류: {e}"
            if consecutive_errors >= 3:
                error_msg += "\n⚠️ 연속 3회 이상 오류 발생. 5분 대기 후 재시도합니다."
                time.sleep(300)  # 5분 대기
            else:
                time.sleep(30)
            send_telegram_message(error_msg)

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