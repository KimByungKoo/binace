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
import psutil
import threading
import websocket
from binance.client import Client

# client = Client("api_key", "api_secret")

# 포지션 상태 저장용 (전역 변수로 선언)
open_trades = {}

# 전역 변수로 웹소켓 연결 관리
price_sockets = {}
ws = None

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
    "debug": {                  # 디버깅 설정
        "enabled": True,        # 디버깅 모드 활성화
        "log_level": "INFO",    # 로그 레벨 (DEBUG, INFO, WARNING, ERROR)
        "show_trade_details": True,  # 거래 상세 정보 표시
        "show_websocket_messages": True,  # 웹소켓 메시지 표시
        "show_position_updates": True,  # 포지션 업데이트 표시
    },
    "trading_hours": {          # 거래 시간 제한
        "start": "00:00",
        "end": "23:59"
    },
    "high_volatility_hours": [  # 변동성 높은 시간대 (UTC)
        "02:00-04:00",  # 뉴욕 마감 시간
        "14:00-16:00"   # 런던 마감 시간
    ],
    # 스마트 포지션 관리 설정
    "trailing_stop": {
        "enabled": True,
        "activation_pct": 0.5,  # TP의 50% 도달 시 트레일링 스탑 활성화
        "distance_pct": 0.2     # 현재가와의 거리 (%)
    },
    "partial_tp": {
        "enabled": True,
        "levels": [
            {"pct": 0.3, "tp_pct": 0.5},  # 30% 포지션, TP 0.5%
            {"pct": 0.3, "tp_pct": 0.8},  # 30% 포지션, TP 0.8%
            {"pct": 0.4, "tp_pct": 1.2}   # 40% 포지션, TP 1.2%
        ]
    },
    # 시장 상황 기반 전략 설정
    "market_conditions": {
        "high_volatility": {
            "tp_multiplier": 1.2,  # TP 거리 증가
            "sl_multiplier": 1.2,  # SL 거리 증가
            "position_size_multiplier": 0.8  # 포지션 크기 감소
        },
        "low_volatility": {
            "tp_multiplier": 0.8,  # TP 거리 감소
            "sl_multiplier": 0.8,  # SL 거리 감소
            "position_size_multiplier": 1.2  # 포지션 크기 증가
        }
    },
    # 시스템 모니터링 설정
    "monitoring": {
        "check_interval": 300,  # 5분마다 체크
        "max_cpu_usage": 80,    # 최대 CPU 사용률 (%)
        "max_memory_usage": 80, # 최대 메모리 사용률 (%)
        "min_balance": 100      # 최소 잔고 (USDT)
    },
    "risk_management": {
        "max_drawdown": 3.0,        # 최대 허용 드로다운 (%)
        "profit_taking": {
            "enabled": True,
            "levels": [
                {"pct": 0.5, "tp_pct": 0.3},  # 50% 포지션, TP 0.3%
                {"pct": 0.3, "tp_pct": 0.5},  # 30% 포지션, TP 0.5%
                {"pct": 0.2, "tp_pct": 1.0}   # 20% 포지션, TP 1.0%
            ]
        },
        "dynamic_sl": {
            "enabled": True,
            "atr_multiplier": 2.0,   # ATR 기반 SL 거리
            "min_distance": 0.3      # 최소 SL 거리 (%)
        },
        "correlation_limit": 0.7,    # 상관관계 제한
        "max_sector_exposure": 30.0  # 섹터별 최대 노출도 (%)
    },
    "market_maker": {
        "enabled": True,
        "spread_pct": 0.1,        # 스프레드 설정 (%)
        "grid_levels": 5,         # 그리드 레벨 수
        "grid_distance": 0.2,     # 그리드 간격 (%)
        "position_size": 20,      # 기본 포지션 크기 (USDT)
        "max_positions": 3,       # 최대 동시 포지션 수
        "profit_threshold": 0.3,  # 익절 기준 (%)
        "loss_threshold": 0.2     # 손절 기준 (%)
    },
    "advanced_strategies": {
        "momentum_trading": {
            "enabled": True,
            "rsi_period": 14,
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            "volume_threshold": 2.0,  # 평균 거래량 대비
            "profit_target": 0.5,     # 목표 수익률 (%)
            "stop_loss": 0.3          # 손절 기준 (%)
        },
        "breakout_trading": {
            "enabled": True,
            "breakout_period": 20,    # 돌파 확인 기간
            "volume_confirmation": 1.5,  # 거래량 확인 비율
            "profit_target": 1.0,     # 목표 수익률 (%)
            "stop_loss": 0.5          # 손절 기준 (%)
        },
        "arbitrage": {
            "enabled": True,
            "min_profit_pct": 0.2,    # 최소 수익률 (%)
            "max_position_time": 300,  # 최대 포지션 유지 시간 (초)
            "correlation_threshold": 0.8  # 상관관계 임계값
        }
    }
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
    "trading_hours_stats": {},  # 시간대별 통계
    "partial_tp_hits": 0,       # 부분 익절 성공 횟수
    "trailing_stop_hits": 0     # 트레일링 스탑 성공 횟수
}

# 시장 상황 분석
market_analysis = {
    "overall_trend": None,      # 전체 시장 트렌드
    "volatility_index": 0,      # 변동성 지수
    "correlation_groups": {},    # 상관관계 그룹
    "last_update": None,
    "volume_profile": {},       # 거래량 프로파일
    "trend_strength": 0,        # 추세 강도 (0-100)
    "market_phase": None        # 시장 단계 (accumulation/distribution/trending)
}

def debug_message(message: str, level: str = "INFO"):
    """
    디버깅 메시지 출력
    """
    if not CONFIG["debug"]["enabled"]:
        return
        
    log_levels = {
        "DEBUG": 0,
        "INFO": 1,
        "WARNING": 2,
        "ERROR": 3
    }
    
    current_level = log_levels.get(CONFIG["debug"]["log_level"], 1)
    message_level = log_levels.get(level, 1)
    
    if message_level >= current_level:
        send_telegram_message(f"🔍 [{level}] {message}")

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

def initialize_trade_history():
    """
    기존 거래 데이터와 현재 보유 포지션을 초기화
    """
    try:
        history_file = "trade_history.json"
        
        # 현재 보유 포지션 정보 가져오기
        positions = client.futures_position_information()
        current_positions = []
        
        for position in positions:
            if float(position['positionAmt']) != 0:
                position_info = {
                    "symbol": position['symbol'],
                    "direction": "long" if float(position['positionAmt']) > 0 else "short",
                    "entry_price": float(position['entryPrice']),
                    "current_price": float(position['markPrice']),
                    "quantity": abs(float(position['positionAmt'])),
                    "unrealized_pnl": float(position['unRealizedProfit'])
                }
                
                # leverage 정보가 있는 경우에만 추가
                if 'leverage' in position:
                    position_info["leverage"] = float(position['leverage'])
                    
                current_positions.append(position_info)
        
        # 오늘 날짜의 거래 내역 생성
        today_data = {
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "trades": [],
            "current_positions": current_positions,
            "summary": {
                "total_trades": 0,
                "win_rate": 0,
                "total_profit": 0,
                "total_loss": 0,
                "open_positions": len(current_positions)
            }
        }
        
        # 파일이 없으면 생성하고 초기화
        if not os.path.exists(history_file):
            with open(history_file, 'w') as f:
                json.dump([today_data], f, indent=2)
            debug_message("거래 내역 파일 생성 및 초기화 완료", "INFO")
        else:
            # 기존 데이터 읽기
            with open(history_file, 'r') as f:
                history = json.load(f)
            
            # 오늘 날짜의 데이터가 있는지 확인
            today = datetime.utcnow().strftime("%Y-%m-%d")
            today_exists = False
            
            for entry in history:
                if entry["date"] == today:
                    # 오늘 데이터 업데이트
                    entry["current_positions"] = current_positions
                    entry["summary"]["open_positions"] = len(current_positions)
                    today_exists = True
                    break
            
            # 오늘 데이터가 없으면 추가
            if not today_exists:
                history.append(today_data)
            
            # 파일 저장
            with open(history_file, 'w') as f:
                json.dump(history, f, indent=2)
            
            debug_message("거래 내역 업데이트 완료", "INFO")
        
        if current_positions:
            debug_message(f"현재 보유 포지션 {len(current_positions)}개 추가됨", "INFO")
            
    except Exception as e:
        debug_message(f"거래 내역 초기화 실패: {str(e)}", "ERROR")

def save_trade_history():
    """
    거래 내역 저장
    """
    try:
        history_file = "trade_history.json"
        
        # 파일이 없으면 초기화
        if not os.path.exists(history_file):
            initialize_trade_history()
            return
        
        # 기존 데이터 읽기
        with open(history_file, 'r') as f:
            history = json.load(f)
        
        # 오늘 날짜 찾기
        today = datetime.utcnow().strftime("%Y-%m-%d")
        today_entry = None
        
        for entry in history:
            if entry["date"] == today:
                today_entry = entry
                break
        
        # 오늘 데이터가 없으면 새로 생성
        if not today_entry:
            today_entry = {
                "date": today,
                "trades": [],
                "current_positions": [],
                "summary": {
                    "total_trades": 0,
                    "win_rate": 0,
                    "total_profit": 0,
                    "total_loss": 0,
                    "open_positions": 0
                }
            }
            history.append(today_entry)
        
        # 거래 내역 업데이트
        today_entry["trades"] = daily_stats["trades"]
        today_entry["summary"] = {
            "total_trades": len(daily_stats["trades"]),
            "win_rate": (daily_stats["winning_trades"] / len(daily_stats["trades"]) * 100) if daily_stats["trades"] else 0,
            "total_profit": daily_stats["total_profit"],
            "total_loss": daily_stats["total_loss"],
            "open_positions": len(open_trades)
        }
        
        # 현재 포지션 정보 업데이트
        current_positions = []
        for symbol, trade in open_trades.items():
            current_positions.append({
                "symbol": symbol,
                "direction": trade["direction"],
                "entry_price": trade["entry_price"],
                "current_price": trade.get("current_price", trade["entry_price"]),
                "quantity": trade["qty"],
                "mode": trade["mode"]
            })
        today_entry["current_positions"] = current_positions
        
        # 파일 저장
        with open(history_file, 'w') as f:
            json.dump(history, f, indent=2)
            
        debug_message("거래 내역 저장 완료", "INFO")
            
    except Exception as e:
        debug_message(f"거래 내역 저장 실패: {str(e)}", "ERROR")

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

def check_system_health() -> bool:
    """
    시스템 상태 체크
    """
    try:
        cpu_usage = psutil.cpu_percent()
        memory_usage = psutil.virtual_memory().percent
        
        if cpu_usage > CONFIG["monitoring"]["max_cpu_usage"]:
            send_telegram_message(f"⚠️ CPU 사용률 높음: {cpu_usage}%")
            return False
            
        if memory_usage > CONFIG["monitoring"]["max_memory_usage"]:
            send_telegram_message(f"⚠️ 메모리 사용률 높음: {memory_usage}%")
            return False
            
        # 잔고 체크
        balance = float(client.futures_account()['totalWalletBalance'])
        if balance < CONFIG["monitoring"]["min_balance"]:
            send_telegram_message(f"⚠️ 잔고 부족: {balance} USDT")
            return False
            
        return True
        
    except Exception as e:
        send_telegram_message(f"💥 시스템 상태 체크 실패: {str(e)}")
        return False

def update_trailing_stop(symbol: str, current_price: float):
    """
    트레일링 스탑 업데이트
    """
    if symbol not in open_trades:
        return
        
    trade = open_trades[symbol]
    if not CONFIG["trailing_stop"]["enabled"]:
        return
        
    direction = trade["direction"]
    entry_price = trade["entry_price"]
    tp = trade["tp"]
    
    # TP 도달 비율 계산
    if direction == "long":
        tp_distance = tp - entry_price
        current_distance = current_price - entry_price
        if current_distance >= tp_distance * CONFIG["trailing_stop"]["activation_pct"]:
            new_sl = current_price * (1 - CONFIG["trailing_stop"]["distance_pct"] / 100)
            if new_sl > trade["sl"]:
                trade["sl"] = new_sl
                send_telegram_message(f"🔄 트레일링 스탑 업데이트: {symbol}\n"
                                    f"   ├ 새로운 SL: `{round(new_sl, 4)}`\n"
                                    f"   └ 현재가: `{round(current_price, 4)}`")
    else:
        tp_distance = entry_price - tp
        current_distance = entry_price - current_price
        if current_distance >= tp_distance * CONFIG["trailing_stop"]["activation_pct"]:
            new_sl = current_price * (1 + CONFIG["trailing_stop"]["distance_pct"] / 100)
            if new_sl < trade["sl"]:
                trade["sl"] = new_sl
                send_telegram_message(f"🔄 트레일링 스탑 업데이트: {symbol}\n"
                                    f"   ├ 새로운 SL: `{round(new_sl, 4)}`\n"
                                    f"   └ 현재가: `{round(current_price, 4)}`")

def check_partial_tp(symbol: str, current_price: float):
    """
    부분 익절 체크
    """
    if symbol not in open_trades or not CONFIG["partial_tp"]["enabled"]:
        return
        
    trade = open_trades[symbol]
    if "partial_tp_executed" in trade:
        return
        
    direction = trade["direction"]
    entry_price = trade["entry_price"]
    total_qty = trade["qty"]
    
    for level in CONFIG["partial_tp"]["levels"]:
        if level["pct"] in trade.get("partial_tp_levels", []):
            continue
            
        tp_price = entry_price * (1 + level["tp_pct"] / 100) if direction == "long" else entry_price * (1 - level["tp_pct"] / 100)
        
        if (direction == "long" and current_price >= tp_price) or (direction == "short" and current_price <= tp_price):
            partial_qty = total_qty * level["pct"]
            close_position(symbol, partial_qty, "short" if direction == "long" else "long")
            
            if "partial_tp_levels" not in trade:
                trade["partial_tp_levels"] = []
            trade["partial_tp_levels"].append(level["pct"])
            
            daily_stats["partial_tp_hits"] += 1
            
            send_telegram_message(f"🎯 부분 익절 실행: {symbol}\n"
                                f"   ├ 수량: `{round(partial_qty, 4)}`\n"
                                f"   ├ 목표가: `{round(tp_price, 4)}`\n"
                                f"   └ 현재가: `{round(current_price, 4)}`")

def analyze_market_phase(df: pd.DataFrame) -> str:
    """
    시장 단계 분석
    """
    # 볼린저 밴드
    df['bb_middle'] = df['close'].rolling(20).mean()
    df['bb_std'] = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_middle'] + 2 * df['bb_std']
    df['bb_lower'] = df['bb_middle'] - 2 * df['bb_std']
    
    # RSI
    df['rsi'] = calculate_rsi(df)
    
    # 거래량 프로파일
    df['volume_ma'] = df['volume'].rolling(20).mean()
    
    latest = df.iloc[-1]
    
    # 추세 강도 계산
    price_trend = (latest['close'] - df['close'].iloc[-20]) / df['close'].iloc[-20] * 100
    volume_trend = (latest['volume'] - df['volume'].iloc[-20]) / df['volume'].iloc[-20] * 100
    
    trend_strength = abs(price_trend) * (1 + volume_trend / 100)
    market_analysis["trend_strength"] = min(trend_strength, 100)
    
    # 시장 단계 판단
    if latest['close'] > latest['bb_upper']:
        return "trending"
    elif latest['close'] < latest['bb_lower']:
        return "trending"
    elif latest['rsi'] > 70 or latest['rsi'] < 30:
        return "distribution"
    else:
        return "accumulation"

def adjust_strategy_parameters(symbol: str, df: pd.DataFrame) -> Dict:
    """
    시장 상황에 따른 전략 파라미터 조정
    """
    volatility = calculate_volatility(df)
    market_phase = analyze_market_phase(df)
    
    # 기본 파라미터
    params = {
        "tp_multiplier": 1.0,
        "sl_multiplier": 1.0,
        "position_size_multiplier": 1.0
    }
    
    # 변동성 기반 조정
    if volatility > 0.02:  # 높은 변동성
        params.update(CONFIG["market_conditions"]["high_volatility"])
    elif volatility < 0.01:  # 낮은 변동성
        params.update(CONFIG["market_conditions"]["low_volatility"])
    
    # 시장 단계 기반 추가 조정
    if market_phase == "trending":
        params["tp_multiplier"] *= 1.2
        params["sl_multiplier"] *= 1.2
    elif market_phase == "accumulation":
        params["position_size_multiplier"] *= 0.8
    
    return params

def check_risk_limits(symbol: str, direction: str, position_size: float) -> bool:
    """
    리스크 제한 체크
    """
    try:
        # 드로다운 체크
        current_drawdown = (daily_stats["start_balance"] - daily_stats["current_balance"]) / daily_stats["start_balance"] * 100
        if current_drawdown > CONFIG["risk_management"]["max_drawdown"]:
            send_telegram_message(f"⚠️ 드로다운 제한 도달: {round(current_drawdown, 2)}%")
            return False

        # 상관관계 체크
        if len(open_trades) > 0:
            df = get_1m_klines(symbol, interval="1h", limit=24)
            for existing_symbol in open_trades:
                if existing_symbol == symbol:
                    continue
                existing_df = get_1m_klines(existing_symbol, interval="1h", limit=24)
                if not df.empty and not existing_df.empty:
                    correlation = df['close'].corr(existing_df['close'])
                    if abs(correlation) > CONFIG["risk_management"]["correlation_limit"]:
                        send_telegram_message(f"⚠️ 높은 상관관계 감지: {symbol} - {existing_symbol} ({round(correlation, 2)})")
                        return False

        # 섹터 노출도 체크
        sector_exposure = calculate_sector_exposure(symbol, position_size)
        if sector_exposure > CONFIG["risk_management"]["max_sector_exposure"]:
            send_telegram_message(f"⚠️ 섹터 노출도 제한: {round(sector_exposure, 2)}%")
            return False

        return True

    except Exception as e:
        send_telegram_message(f"💥 리스크 체크 오류: {str(e)}")
        return False

def calculate_sector_exposure(symbol: str, new_position_size: float) -> float:
    """
    섹터별 노출도 계산
    """
    try:
        # 현재 포지션의 섹터별 노출도 계산
        sector_exposures = {}
        total_exposure = 0

        # 기존 포지션의 섹터 노출도
        for sym, trade in open_trades.items():
            sector = get_coin_sector(sym)
            if sector not in sector_exposures:
                sector_exposures[sector] = 0
            sector_exposures[sector] += trade['position_size']
            total_exposure += trade['position_size']

        # 새로운 포지션 추가
        new_sector = get_coin_sector(symbol)
        if new_sector not in sector_exposures:
            sector_exposures[new_sector] = 0
        sector_exposures[new_sector] += new_position_size
        total_exposure += new_position_size

        # 섹터별 노출도 비율 계산
        if total_exposure > 0:
            return (sector_exposures[new_sector] / total_exposure) * 100
        return 0

    except Exception as e:
        send_telegram_message(f"💥 섹터 노출도 계산 오류: {str(e)}")
        return 0

def get_coin_sector(symbol: str) -> str:
    """
    코인의 섹터 분류
    """
    # 실제 구현에서는 더 정교한 분류가 필요
    if symbol.endswith('BTC'):
        return 'BTC'
    elif symbol.endswith('ETH'):
        return 'ETH'
    elif symbol.endswith('USDT'):
        return 'USDT'
    return 'OTHER'

def calculate_dynamic_sl(df: pd.DataFrame, direction: str) -> float:
    """
    동적 스탑로스 계산
    """
    try:
        if not CONFIG["risk_management"]["dynamic_sl"]["enabled"]:
            return None

        # ATR 계산
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        atr = df['tr'].rolling(14).mean().iloc[-1]
        current_price = df['close'].iloc[-1]

        # ATR 기반 SL 거리
        sl_distance = atr * CONFIG["risk_management"]["dynamic_sl"]["atr_multiplier"]
        min_distance = current_price * CONFIG["risk_management"]["dynamic_sl"]["min_distance"] / 100

        # 최종 SL 거리 결정
        sl_distance = max(sl_distance, min_distance)

        if direction == "long":
            return current_price - sl_distance
        else:
            return current_price + sl_distance

    except Exception as e:
        send_telegram_message(f"💥 동적 SL 계산 오류: {str(e)}")
        return None

def process_trade_exit(symbol: str, trade: dict, exit_price: float, reason: str):
    """
    거래 청산 처리
    """
    try:
        debug_message(f"청산 처리 시작: {symbol}", "DEBUG")
        
        # 수익금 계산 수정
        if trade['direction'] == "long":
            pnl = (exit_price - trade['entry_price']) * trade['qty']
            pnl_pct = (exit_price - trade['entry_price']) / trade['entry_price'] * 100
        else:
            pnl = (trade['entry_price'] - exit_price) * trade['qty']
            pnl_pct = (trade['entry_price'] - exit_price) / trade['entry_price'] * 100
        
        # 거래 결과 기록
        trade_result = {
            "symbol": symbol,
            "direction": trade['direction'],
            "entry_price": trade['entry_price'],
            "exit_price": exit_price,
            "qty": trade['qty'],
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "reason": reason,
            "timestamp": datetime.utcnow(),
            "strategy_params": trade.get("strategy_params", {})
        }
        
        debug_message(f"거래 결과: {symbol} - PnL: {pnl:.2f} USDT ({pnl_pct:.2f}%)", "INFO")
        
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
        
        debug_message(f"통계 업데이트 완료: {symbol}", "DEBUG")
        
        # 시간대별 통계 업데이트
        hour = trade_result["timestamp"].hour
        if hour not in daily_stats["trading_hours_stats"]:
            daily_stats["trading_hours_stats"][hour] = {"trades": 0, "profit": 0}
        daily_stats["trading_hours_stats"][hour]["trades"] += 1
        daily_stats["trading_hours_stats"][hour]["profit"] += pnl
        
        update_daily_stats(trade_result)
        
        if CONFIG["debug"]["show_trade_details"]:
            send_telegram_message(f"{reason}\n"
                              f"   ├ 종목     : `{symbol}`\n"
                              f"   ├ 방향     : `{trade['direction']}`\n"
                              f"   ├ 진입가   : `{trade['entry_price']:.4f}`\n"
                              f"   ├ 청산가   : `{exit_price:.4f}`\n"
                              f"   ├ 수량     : `{trade['qty']:.4f}`\n"
                              f"   ├ 수익금   : `{pnl:.2f} USDT`\n"
                              f"   ├ 수익률   : `{pnl_pct:.2f}%`\n"
                              f"   └ 모드     : `{trade['mode']}`")
        
        # 포지션 제거
        if symbol in open_trades:
            del open_trades[symbol]
            debug_message(f"포지션 제거 완료: {symbol}", "DEBUG")
            
        # 웹소켓 구독 해제
        if symbol in price_sockets:
            if ws is not None:
                payload = {
                    "method": "UNSUBSCRIBE",
                    "params": [f"{symbol.lower()}@trade"],
                    "id": 1
                }
                ws.send(json.dumps(payload))
            del price_sockets[symbol]
            debug_message(f"웹소켓 구독 해제 완료: {symbol}", "DEBUG")
            
    except Exception as e:
        debug_message(f"거래 청산 처리 오류: {str(e)}", "ERROR")

def on_message(ws, message):
    """
    웹소켓 메시지 처리
    """
    try:
        data = json.loads(message)
        if data.get("e") != "trade":
            return

        symbol = data["s"].upper()
        if symbol in open_trades:
            current_price = float(data["p"])
            open_trades[symbol]['current_price'] = current_price
            
            debug_message(f"가격 업데이트: {symbol} = {current_price}", "DEBUG")
            
            # TP/SL 체크
            trade = open_trades[symbol]
            direction = trade['direction']
            tp = trade['tp']
            sl = trade['sl']
            
            debug_message(f"TP/SL 체크: {symbol} - TP: {tp}, SL: {sl}, 현재가: {current_price}", "DEBUG")
            
            if tp is None or sl is None:
                debug_message(f"TP/SL 없음: {symbol}", "WARNING")
                return
                
            exit_reason = None
            if direction == "long":
                if current_price >= tp:
                    exit_reason = "🟢 익절 TP 도달"
                elif current_price <= sl:
                    exit_reason = "🔴 손절 SL 도달"
            else:  # short
                if current_price <= tp:
                    exit_reason = "🟢 익절 TP 도달"
                elif current_price >= sl:
                    exit_reason = "🔴 손절 SL 도달"
                    
            if exit_reason:
                try:
                    debug_message(f"청산 조건 도달: {symbol} - {exit_reason}", "INFO")
                    
                    # 포지션 방향 확인
                    position = client.futures_position_information(symbol=symbol)[0]
                    position_amt = float(position['positionAmt'])
                    
                    debug_message(f"포지션 확인: {symbol} - 수량: {position_amt}", "DEBUG")
                    
                    if position_amt != 0:  # 포지션이 실제로 존재하는 경우에만 청산
                        # 청산 방향 결정
                        close_direction = "short" if direction == "long" else "long"
                        
                        debug_message(f"청산 시도: {symbol} - 방향: {close_direction}, 수량: {trade['qty']}", "INFO")
                        
                        # 청산 실행
                        close_position(symbol, trade['qty'], close_direction)
                        debug_message(f"청산 주문 실행 완료: {symbol}", "INFO")
                        
                        # 청산 처리
                        process_trade_exit(symbol, trade, current_price, exit_reason)
                    else:
                        debug_message(f"포지션 없음: {symbol} - 이미 청산됨", "WARNING")
                        if symbol in open_trades:
                            del open_trades[symbol]
                except Exception as e:
                    debug_message(f"청산 실행 오류: {symbol} - {str(e)}", "ERROR")
                
    except Exception as e:
        debug_message(f"웹소켓 메시지 처리 오류: {str(e)}", "ERROR")

def on_error(ws, error):
    send_telegram_message(f"💥 웹소켓 에러: {error}")

def on_close(ws, close_status_code, close_msg):
    send_telegram_message(f"🔌 웹소켓 연결 종료 (코드: {close_status_code}, 메시지: {close_msg})")

def on_open(ws):
    """
    웹소켓 연결 시작 시 호출
    """
    try:
        # 현재 포지션에 대한 웹소켓 연결
        params = [f"{symbol.lower()}@trade" for symbol in open_trades.keys()]
        if params:
            payload = {
                "method": "SUBSCRIBE",
                "params": params,
                "id": 1
            }
            ws.send(json.dumps(payload))
            send_telegram_message(f"🔌 웹소켓 연결 시작됨 (구독 심볼: {', '.join(params)})")
            
            # price_sockets 업데이트
            for symbol in open_trades.keys():
                price_sockets[symbol] = True
        else:
            send_telegram_message("🔌 웹소켓 연결 시작됨 (구독 심볼 없음)")
    except Exception as e:
        send_telegram_message(f"💥 웹소켓 연결 실패: {str(e)}")

def start_websocket_connections():
    """
    웹소켓 연결 시작
    """
    global ws
    try:
        ws_url = "wss://fstream.binance.com/ws"
        send_telegram_message(f"🔌 웹소켓 연결 시도 중... (URL: {ws_url})")
        
        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        
        # 웹소켓 연결을 별도의 스레드에서 실행
        ws_thread = threading.Thread(target=ws.run_forever)
        ws_thread.daemon = True  # 메인 스레드가 종료되면 함께 종료되도록 설정
        ws_thread.start()
        
        # 연결이 시작될 때까지 잠시 대기
        time.sleep(1)
        
    except Exception as e:
        send_telegram_message(f"💥 웹소켓 연결 실패: {str(e)}")

def enter_trade_from_wave(symbol, wave_info, price):
    try:
        # 시스템 상태 체크
        if not check_system_health():
            return
        # 거래 시간 체크
        if not is_trading_allowed():
            return
        # 최대 포지션 수 체크
        if len(open_trades) >= CONFIG["max_open_positions"]:
            return
        # 연속 손실 체크
        if daily_stats["consecutive_losses"] >= CONFIG["max_consecutive_losses"]:
            return
        # 일일 손실 제한 체크
        if not check_daily_loss_limit():
            return
        # 이미 포지션이 있는지 한번 더 확인
        if has_open_position(symbol):
            return
        # 거래량 조건 체크
        df = get_1m_klines(symbol, interval="3m", limit=CONFIG["volume_ma_window"] + 1)
        if not check_volume_condition(df):
            return
        # 변동성 계산 및 포지션 크기 결정
        volatility = calculate_volatility(df)
        position_size = calculate_position_size(symbol, price, volatility)
        # 전략 파라미터 조정
        strategy_params = adjust_strategy_parameters(symbol, df)
        position_size *= strategy_params["position_size_multiplier"]
        mode = determine_trade_mode_from_wave(wave_info)
        direction = "long" if wave_info['direction'] == "up" else "short"
        qty = round_qty(symbol, position_size / price)
        tp_ratio = {"scalp": 1.003, "trend": 1.015, "revert": 1.01}
        sl_ratio = {"scalp": 0.995, "trend": 0.985, "revert": 0.99}
        # TP/SL 거리 조정
        tp = price * tp_ratio[mode] * strategy_params["tp_multiplier"] if direction == "long" else price * (2 - tp_ratio[mode] * strategy_params["tp_multiplier"])
        sl = price * sl_ratio[mode] * strategy_params["sl_multiplier"] if direction == "long" else price * (2 - sl_ratio[mode] * strategy_params["sl_multiplier"])
        signal = {
            "symbol": symbol,
            "direction": direction,
            "price": price,
            "take_profit": tp,
            "stop_loss": sl
        }
        # 리스크 제한 체크
        if not check_risk_limits(symbol, direction, position_size):
            return
        # 동적 SL 계산
        dynamic_sl = calculate_dynamic_sl(df, direction)
        if dynamic_sl:
            sl = dynamic_sl
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
            "position_size": position_size,
            "strategy_params": strategy_params,
            "partial_tp_levels": [],
            "current_price": price
        }
        send_telegram_message(f"🚀 진입 완료: {symbol} ({mode.upper()})\n"
                              f"   ├ 방향     : `{direction}`\n"
                              f"   ├ 현재가   : `{round(price, 4)}`\n"
                              f"   ├ TP       : `{round(tp, 4)}`\n"
                              f"   ├ SL       : `{round(sl, 4)}`\n"
                              f"   ├ 수량     : `{round(qty, 4)}`\n"
                              f"   ├ 변동성   : `{round(volatility * 100, 2)}%`\n"
                              f"   ├ 시장단계 : `{analyze_market_phase(df)}`\n"
                              f"   └ 모드     : `{mode}`")
        # 웹소켓 연결 추가
        if symbol not in price_sockets and ws is not None:
            params = [f"{symbol.lower()}@trade"]
            payload = {
                "method": "SUBSCRIBE",
                "params": params,
                "id": 1
            }
            ws.send(json.dumps(payload))
            price_sockets[symbol] = True
            send_telegram_message(f"🔌 {symbol} 웹소켓 구독 추가됨")
    except Exception as e:
        send_telegram_message(f"💥 진입 실패: {symbol} - {str(e)}")

def initialize_trade_history():
    """
    기존 거래 데이터와 현재 보유 포지션을 초기화
    """
    try:
        history_file = "trade_history.json"
        
        # 현재 보유 포지션 정보 가져오기
        positions = client.futures_position_information()
        current_positions = []
        
        for position in positions:
            if float(position['positionAmt']) != 0:
                position_info = {
                    "symbol": position['symbol'],
                    "direction": "long" if float(position['positionAmt']) > 0 else "short",
                    "entry_price": float(position['entryPrice']),
                    "current_price": float(position['markPrice']),
                    "quantity": abs(float(position['positionAmt'])),
                    "unrealized_pnl": float(position['unRealizedProfit'])
                }
                
                # leverage 정보가 있는 경우에만 추가
                if 'leverage' in position:
                    position_info["leverage"] = float(position['leverage'])
                    
                current_positions.append(position_info)
        
        # 오늘 날짜의 거래 내역 생성
        today_data = {
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "trades": [],
            "current_positions": current_positions,
            "summary": {
                "total_trades": 0,
                "win_rate": 0,
                "total_profit": 0,
                "total_loss": 0,
                "open_positions": len(current_positions)
            }
        }
        
        # 파일이 없으면 생성하고 초기화
        if not os.path.exists(history_file):
            with open(history_file, 'w') as f:
                json.dump([today_data], f, indent=2)
            debug_message("거래 내역 파일 생성 및 초기화 완료", "INFO")
        else:
            # 기존 데이터 읽기
            with open(history_file, 'r') as f:
                history = json.load(f)
            
            # 오늘 날짜의 데이터가 있는지 확인
            today = datetime.utcnow().strftime("%Y-%m-%d")
            today_exists = False
            
            for entry in history:
                if entry["date"] == today:
                    # 오늘 데이터 업데이트
                    entry["current_positions"] = current_positions
                    entry["summary"]["open_positions"] = len(current_positions)
                    today_exists = True
                    break
            
            # 오늘 데이터가 없으면 추가
            if not today_exists:
                history.append(today_data)
            
            # 파일 저장
            with open(history_file, 'w') as f:
                json.dump(history, f, indent=2)
            
            debug_message("거래 내역 업데이트 완료", "INFO")
        
        if current_positions:
            debug_message(f"현재 보유 포지션 {len(current_positions)}개 추가됨", "INFO")
            
    except Exception as e:
        debug_message(f"거래 내역 초기화 실패: {str(e)}", "ERROR")

def wave_trade_watcher():
    """
    파동 기반 트레이드 감시 루프
    """
    send_telegram_message("🌊 파동 기반 진입 감시 시작...")
    
    # 거래 내역 초기화
    initialize_trade_history()
    
    # 기존 포지션 확인 및 웹소켓 구독
    try:
        positions = client.futures_position_information()
        for position in positions:
            symbol = position['symbol']
            if float(position['positionAmt']) != 0:  # 포지션이 있는 경우
                if symbol not in open_trades:
                    # 포지션 정보 저장
                    entry_price = float(position['entryPrice'])
                    current_price = float(position['markPrice'])
                    direction = 'long' if float(position['positionAmt']) > 0 else 'short'
                    qty = abs(float(position['positionAmt']))
                    
                    # 수익률 계산
                    pnl_pct = ((current_price - entry_price) / entry_price * 100) if direction == 'long' else ((entry_price - current_price) / entry_price * 100)
                    
                    # 모드 결정 (수익률 기반)
                    if abs(pnl_pct) < 0.3:
                        mode = 'scalp'
                    elif abs(pnl_pct) < 1.0:
                        mode = 'trend'
                    else:
                        mode = 'revert'
                    
                    # TP/SL 계산
                    if direction == 'long':
                        tp = entry_price * 1.015  # 1.5% 익절
                        sl = entry_price * 0.985  # 1.5% 손절
                    else:
                        tp = entry_price * 0.985  # 1.5% 익절
                        sl = entry_price * 1.015  # 1.5% 손절

                    open_trades[symbol] = {
                        'entry_price': entry_price,
                        'direction': direction,
                        'qty': qty,
                        'tp': tp,
                        'sl': sl,
                        'mode': mode,
                        'current_price': current_price
                    }
                    
                    debug_message(f"기존 포지션 발견: {symbol}\n"
                                f"   ├ 방향     : `{direction}`\n"
                                f"   ├ 진입가   : `{round(entry_price, 4)}`\n"
                                f"   ├ 현재가   : `{round(current_price, 4)}`\n"
                                f"   ├ 수익률   : `{round(pnl_pct, 2)}%`\n"
                                f"   ├ TP       : `{round(tp, 4)}`\n"
                                f"   ├ SL       : `{round(sl, 4)}`\n"
                                f"   └ 모드     : `{mode}`", "INFO")
    except Exception as e:
        debug_message(f"기존 포지션 확인 실패: {str(e)}", "ERROR")
    
    # 웹소켓 연결 시작
    start_websocket_connections()
    
    # 웹소켓 연결이 시작될 때까지 잠시 대기
    time.sleep(2)
    
    # 초기 상태 리포트
    account = client.futures_account()
    balance = float(account['totalWalletBalance'])
    daily_stats["start_balance"] = balance
    daily_stats["current_balance"] = balance
    daily_stats["last_reset"] = datetime.utcnow()
    
    initial_report = f"""
🤖 *봇 초기화 완료*
├ 계좌 잔고: `{round(balance, 2)} USDT`
├ 최대 포지션: `{CONFIG['max_open_positions']}개`
├ 최대 손실: `{CONFIG['max_daily_loss_pct']}%`
├ 거래 시간: `{CONFIG['trading_hours']['start']} ~ {CONFIG['trading_hours']['end']} UTC`
└ 시스템 상태: 정상
"""
    send_telegram_message(initial_report)

    consecutive_errors = 0  # 연속 에러 카운트
    last_report_time = datetime.utcnow()
    last_market_analysis_time = datetime.utcnow()
    last_health_check_time = datetime.utcnow()
    last_status_time = datetime.utcnow()  # 상태 메시지 시간 추적

    while True:
        try:
            # 시스템 상태 체크 (5분마다)
            if (datetime.utcnow() - last_health_check_time).total_seconds() > CONFIG["monitoring"]["check_interval"]:
                if not check_system_health():
                    time.sleep(300)  # 5분 대기
                    continue
                last_health_check_time = datetime.utcnow()

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

            # 상태 메시지 (10분마다)
            if (datetime.utcnow() - last_status_time).total_seconds() > 600:
                status_msg = f"🤖 봇 상태 업데이트\n"
                status_msg += f"├ 현재 포지션: {len(open_trades)}개\n"
                if open_trades:
                    status_msg += "├ 보유 중인 포지션:\n"
                    for symbol, trade in open_trades.items():
                        pnl = ((trade['current_price'] - trade['entry_price']) / trade['entry_price'] * 100) if trade['direction'] == "long" else ((trade['entry_price'] - trade['current_price']) / trade['entry_price'] * 100)
                        status_msg += f"│  ├ {symbol}: {trade['direction']} ({round(pnl, 2)}%)\n"
                status_msg += f"├ 일일 거래: {daily_stats['total_trades']}회\n"
                status_msg += f"├ 승률: {round(daily_stats['winning_trades'] / daily_stats['total_trades'] * 100 if daily_stats['total_trades'] > 0 else 0, 1)}%\n"
                status_msg += f"└ 연속 손실: {daily_stats['consecutive_losses']}회"
                send_telegram_message(status_msg)
                last_status_time = datetime.utcnow()

            # 웹소켓 연결 상태 확인 및 재연결
            if ws is None:
                send_telegram_message("⚠️ 웹소켓 연결이 끊어졌습니다. 재연결을 시도합니다...")
                start_websocket_connections()

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

                    # 기존 파동 분석
                    wave_info = analyze_wave_from_df(df)
                    
                    # 추가 전략 실행
                    if wave_info:
                        # 모멘텀 전략
                        if execute_momentum_strategy(symbol, df):
                            enter_trade_from_wave(symbol, wave_info, df['close'].iloc[-1])
                            
                        # 돌파 전략
                        if execute_breakout_strategy(symbol, df):
                            enter_trade_from_wave(symbol, wave_info, df['close'].iloc[-1])
                            
                        # 차익거래 전략
                        if execute_arbitrage_strategy(symbol):
                            enter_trade_from_wave(symbol, wave_info, df['close'].iloc[-1])

                except Exception as e:
                    send_telegram_message(f"⚠️ {symbol} 처리 중 오류: {str(e)}")
                    continue

            # 마켓 메이커 전략 실행
            if CONFIG["market_maker"]["enabled"]:
                for symbol in symbols:
                    if len(open_trades) < CONFIG["market_maker"]["max_positions"]:
                        execute_market_maker_strategy(symbol)

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

def execute_market_maker_strategy(symbol: str):
    """
    마켓 메이커 전략 실행
    """
    try:
        if not CONFIG["market_maker"]["enabled"]:
            return

        # 현재가 조회
            df = get_1m_klines(symbol, interval="1m", limit=1)
        if df.empty:
            return

        current_price = df['close'].iloc[-1]
        
        # 그리드 레벨 계산
        grid_levels = CONFIG["market_maker"]["grid_levels"]
        grid_distance = CONFIG["market_maker"]["grid_distance"]
        
        # 매수/매도 주문 생성
        for i in range(grid_levels):
            # 매수 주문
            buy_price = current_price * (1 - (i + 1) * grid_distance / 100)
            buy_qty = round_qty(symbol, CONFIG["market_maker"]["position_size"] / buy_price)
            
            # 매도 주문
            sell_price = current_price * (1 + (i + 1) * grid_distance / 100)
            sell_qty = round_qty(symbol, CONFIG["market_maker"]["position_size"] / sell_price)
            
            # 주문 실행
            place_order(symbol, "buy", buy_qty, buy_price)
            place_order(symbol, "sell", sell_qty, sell_price)
            
        send_telegram_message(f"🔄 마켓 메이커 전략 실행: {symbol}\n"
                            f"   ├ 현재가: `{round(current_price, 4)}`\n"
                            f"   ├ 그리드 레벨: `{grid_levels}`\n"
                            f"   └ 그리드 간격: `{grid_distance}%`")

    except Exception as e:
        send_telegram_message(f"💥 마켓 메이커 전략 오류: {str(e)}")

def calculate_grid_profit(symbol: str, entry_price: float, current_price: float, direction: str) -> float:
    """
    그리드 전략 수익 계산
    """
    try:
            if direction == "long":
                return (current_price - entry_price) / entry_price * 100
            else:
                return (entry_price - current_price) / entry_price * 100
    except Exception as e:
        return 0

def check_grid_exit(symbol: str, trade: dict) -> bool:
    """
    그리드 전략 청산 조건 체크
    """
    try:
        current_price = trade['current_price']
        entry_price = trade['entry_price']
        direction = trade['direction']
        
        profit_pct = calculate_grid_profit(symbol, entry_price, current_price, direction)
        
        # 익절/손절 조건 체크
        if profit_pct >= CONFIG["market_maker"]["profit_threshold"]:
            return True
        elif profit_pct <= -CONFIG["market_maker"]["loss_threshold"]:
            return True
            
        return False
        
    except Exception as e:
        return False

def analyze_wave_from_df(df):
    """
    최근 20봉 기준으로 파동 방향과 신뢰도 분석
    - MA20, MA60 이용한 추세
    - 변동성(고저폭) 기반 에너지 분석
    - RSI로 과매수/과매도 제외
    """
    try:
        # DataFrame 복사본 생성
        df = df.copy()
        
        # 기술적 지표 계산
        df.loc[:, 'ma20'] = df['close'].rolling(20).mean()
        df.loc[:, 'ma60'] = df['close'].rolling(60).mean()
        df.loc[:, 'range'] = df['high'] - df['low']
        df.loc[:, 'volatility'] = df['range'].rolling(10).mean()
        df.loc[:, 'rsi'] = calculate_rsi(df, period=7)

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

def execute_momentum_strategy(symbol: str, df: pd.DataFrame) -> bool:
    """
    모멘텀 트레이딩 전략 실행
    """
    try:
        if not CONFIG["advanced_strategies"]["momentum_trading"]["enabled"]:
            return False

        # RSI 계산
        df['rsi'] = calculate_rsi(df, CONFIG["advanced_strategies"]["momentum_trading"]["rsi_period"])
        
        # 거래량 확인
        df['volume_ma'] = df['volume'].rolling(20).mean()
        volume_ratio = df['volume'].iloc[-1] / df['volume_ma'].iloc[-1]
        
        # 매수/매도 신호 확인
        if df['rsi'].iloc[-1] < CONFIG["advanced_strategies"]["momentum_trading"]["rsi_oversold"] and \
           volume_ratio > CONFIG["advanced_strategies"]["momentum_trading"]["volume_threshold"]:
            return True
        elif df['rsi'].iloc[-1] > CONFIG["advanced_strategies"]["momentum_trading"]["rsi_overbought"] and \
             volume_ratio > CONFIG["advanced_strategies"]["momentum_trading"]["volume_threshold"]:
            return True
            
        return False

    except Exception as e:
        send_telegram_message(f"💥 모멘텀 전략 오류: {str(e)}")
        return False

def execute_breakout_strategy(symbol: str, df: pd.DataFrame) -> bool:
    """
    돌파 트레이딩 전략 실행
    """
    try:
        if not CONFIG["advanced_strategies"]["breakout_trading"]["enabled"]:
            return False

        # 고점/저점 계산
        period = CONFIG["advanced_strategies"]["breakout_trading"]["breakout_period"]
        df['high_max'] = df['high'].rolling(period).max()
        df['low_min'] = df['low'].rolling(period).min()
        
        # 거래량 확인
        volume_ratio = df['volume'].iloc[-1] / df['volume'].rolling(20).mean().iloc[-1]
        
        # 상향/하향 돌파 확인
        if df['close'].iloc[-1] > df['high_max'].iloc[-2] and \
           volume_ratio > CONFIG["advanced_strategies"]["breakout_trading"]["volume_confirmation"]:
            return True
        elif df['close'].iloc[-1] < df['low_min'].iloc[-2] and \
             volume_ratio > CONFIG["advanced_strategies"]["breakout_trading"]["volume_confirmation"]:
            return True
            
        return False

    except Exception as e:
        send_telegram_message(f"💥 돌파 전략 오류: {str(e)}")
        return False

def execute_arbitrage_strategy(symbol: str) -> bool:
    """
    차익거래 전략 실행
    """
    try:
        if not CONFIG["advanced_strategies"]["arbitrage"]["enabled"]:
            return False

        # 관련 코인들의 가격 데이터 수집
        related_symbols = get_correlated_symbols(symbol)
        if not related_symbols:
            return False

        # 가격 차이 계산
        price_diffs = []
        for related_symbol in related_symbols:
            df = get_1m_klines(related_symbol, interval="1m", limit=1)
            if not df.empty:
                price_diff = abs(df['close'].iloc[-1] - get_1m_klines(symbol, interval="1m", limit=1)['close'].iloc[-1])
                price_diffs.append(price_diff)

        # 차익 기회 확인
        if price_diffs and max(price_diffs) > CONFIG["advanced_strategies"]["arbitrage"]["min_profit_pct"]:
            return True

        return False

    except Exception as e:
        send_telegram_message(f"💥 차익거래 전략 오류: {str(e)}")
        return False

def get_correlated_symbols(symbol: str) -> List[str]:
    """
    상관관계가 높은 심볼 목록 반환
    """
    try:
        symbols = get_top_symbols(20)
        correlated = []
        
        df1 = get_1m_klines(symbol, interval="1h", limit=24)
        if df1.empty:
            return correlated
            
        for sym in symbols:
            if sym == symbol:
                continue
                
            df2 = get_1m_klines(sym, interval="1h", limit=24)
            if not df2.empty:
                correlation = df1['close'].corr(df2['close'])
                if abs(correlation) > CONFIG["advanced_strategies"]["arbitrage"]["correlation_threshold"]:
                    correlated.append(sym)
                    
        return correlated

    except Exception as e:
        return []

def periodic_safety_check():
    """
    10분마다 웹소켓, 포지션 동기화, 시스템 리소스, 예외상황을 점검하는 루프
    """
    while True:
        try:
            # 1. 웹소켓 연결 상태 점검
            if ws is None or not ws.sock or not ws.sock.connected:
                send_telegram_message("⚠️ [점검] 웹소켓 연결이 끊어져 있습니다. 재연결 시도합니다.")
                start_websocket_connections()
                time.sleep(5)  # 재연결 대기

            # 2. 실계좌 포지션과 open_trades 동기화
            positions = client.futures_position_information()
            real_symbols = set()
            for position in positions:
                symbol = position['symbol']
                if float(position['positionAmt']) != 0:
                    real_symbols.add(symbol)
                    if symbol not in open_trades:
                        send_telegram_message(f"⚠️ [점검] 실계좌에만 존재하는 포지션 발견: {symbol}. open_trades에 추가합니다.")
                        entry_price = float(position['entryPrice'])
                        current_price = float(position['markPrice'])
                        direction = 'long' if float(position['positionAmt']) > 0 else 'short'
                        qty = abs(float(position['positionAmt']))
                        if direction == 'long':
                            tp = entry_price * 1.015
                            sl = entry_price * 0.985
                        else:
                            tp = entry_price * 0.985
                            sl = entry_price * 1.015
                        open_trades[symbol] = {
                            'entry_price': entry_price,
                            'direction': direction,
                            'qty': qty,
                            'tp': tp,
                            'sl': sl,
                            'mode': 'sync',
                            'current_price': current_price
                        }
            for symbol in list(open_trades.keys()):
                if symbol not in real_symbols:
                    send_telegram_message(f"⚠️ [점검] open_trades에만 존재하는 포지션 발견: {symbol}. 제거합니다.")
                    del open_trades[symbol]

            # 3. 시스템 리소스 점검
            cpu_usage = psutil.cpu_percent()
            memory_usage = psutil.virtual_memory().percent
            if cpu_usage > CONFIG["monitoring"]["max_cpu_usage"]:
                send_telegram_message(f"⚠️ [점검] CPU 사용률 높음: {cpu_usage}%")
            if memory_usage > CONFIG["monitoring"]["max_memory_usage"]:
                send_telegram_message(f"⚠️ [점검] 메모리 사용률 높음: {memory_usage}%")

            # 4. 예외 상황 로깅 (예: 최근 청산 실패 등)
            # 필요시 예외 상황을 기록하는 전역 리스트/큐를 만들어서 여기서 알림

        except Exception as e:
            send_telegram_message(f"💥 [점검] 주기적 점검 루프 오류: {str(e)}")
        time.sleep(600)  # 10분마다 반복

# 파일 맨 아래에 메인 실행부 추가
if __name__ == '__main__':
    safety_thread = threading.Thread(target=periodic_safety_check)
    safety_thread.daemon = True
    safety_thread.start()