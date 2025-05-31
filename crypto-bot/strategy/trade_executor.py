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
import ssl

# client = Client("api_key", "api_secret")

# 포지션 상태 저장용 (전역 변수로 선언)
open_trades = {}

# 전역 변수로 웹소켓 연결 관리
price_sockets = {}
ws = None
ws_lock = threading.Lock()  # 웹소켓 스레드 안전성을 위한 락 추가
ws_connected = False  # 웹소켓 연결 상태 추적
ws_reconnect_delay = 5  # 재연결 대기 시간 (초)
ws_max_reconnect_attempts = 5  # 최대 재연결 시도 횟수
ws_reconnect_attempts = 0  # 현재 재연결 시도 횟수
last_api_request = {}  # API 요청 시간 추적
api_request_delay = 0.1  # API 요청 간 최소 대기 시간 (초)

# 전역 변수로 주문 상태 추적
market_maker_orders = {}

# 거래 내역 데이터 저장용 전역 변수
trade_history_data = {}

# 설정값
CONFIG = {
    "max_daily_loss_pct": 5.0,  # 일일 최대 손실 제한 (%)
    "max_position_size": 500,   # 최대 포지션 크기 (USDT)
    "min_position_size": 100,    # 최소 포지션 크기 (USDT)
    "leverage": 20,             # 기본 레버리지 설정
    "volatility_window": 20,    # 변동성 계산 기간
    "volume_ma_window": 20,     # 거래량 이동평균 기간
    "min_volume_ratio": 1.5,    # 최소 거래량 비율 (평균 대비)
    "backtest_days": 7,         # 백테스트 기간 (일)
    "max_consecutive_losses": 3,  # 최대 연속 손실 횟수
    "max_open_positions": 10,    # 최대 동시 포지션 수
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

# 전역 변수로 캐시 추가
symbol_info_cache = {}
last_symbol_info_update = {}
last_top_symbols_update = None
top_symbols_cache = None

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
    try:
        # 기본 포지션 크기 (CONFIG의 min_position_size 사용)
        base_size = CONFIG["min_position_size"]
        
        # 변동성이 NaN이거나 유효하지 않은 경우 기본값 사용
        if pd.isna(volatility) or not isinstance(volatility, (int, float)):
            volatility = 0.0
            
        # 변동성이 높을수록 포지션 크기 감소 (안전한 계산)
        volatility_factor = 1 / (1 + max(0, min(volatility, 1.0)))  # 0~1 사이로 제한
        position_size = base_size * volatility_factor
        
        # 최소/최대 제한 적용 (CONFIG 값 사용)
        position_size = max(min(position_size, CONFIG["max_position_size"]), CONFIG["min_position_size"])
        
        # 심볼 정보 가져오기
        symbol_info = client.futures_exchange_info()
        symbol_info = next((s for s in symbol_info['symbols'] if s['symbol'] == symbol), None)
        
        if symbol_info:
            # LOT_SIZE 필터 찾기
            lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            if lot_size_filter:
                min_qty = float(lot_size_filter['minQty'])
                step_size = float(lot_size_filter['stepSize'])
                
                # 최소 주문 수량 계산
                min_order_qty = min_qty
                
                # 최소 주문 가치 계산 (CONFIG의 min_position_size 사용)
                min_order_value = CONFIG["min_position_size"]
                min_qty_by_value = min_order_value / price
                
                # 두 기준 중 큰 값 선택
                min_qty = max(min_order_qty, min_qty_by_value)
                
                # step size에 맞게 반올림
                position_size = round(position_size / step_size) * step_size
                
                # 최소 수량보다 작으면 최소 수량으로 설정
                if position_size < min_qty:
                    position_size = min_qty
                
                debug_message(f"주문 수량 계산: {symbol}\n"
                            f"   ├ 기본 수량: {base_size}\n"
                            f"   ├ 최소 수량: {min_qty}\n"
                            f"   ├ 최종 수량: {position_size}\n"
                            f"   └ 가격: {price}", "INFO")
        
        return position_size
        
    except Exception as e:
        debug_message(f"포지션 크기 계산 실패: {str(e)}", "ERROR")
        return CONFIG["min_position_size"]  # 에러 발생 시 최소 포지션 크기 반환

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

def process_trade_exit(symbol: str, exit_price: float, exit_reason: str):
    """
    포지션 종료 처리
    """
    try:
        if symbol not in open_trades:
            debug_message(f"포지션 종료 실패: {symbol} - 열린 포지션 없음", "ERROR")
            return

        trade = open_trades[symbol]
        entry_price = trade['entry_price']
        qty = trade['qty']
        direction = trade['direction']
        
        # 포지션 정보 가져오기
        try:
            position_info = client.futures_position_information(symbol=symbol)
            if not position_info:
                debug_message(f"포지션 정보 조회 실패: {symbol}", "ERROR")
                return
                
            position = position_info[0]
            position_amt = float(position['positionAmt'])
            
            # 실제 포지션 수량이 0이면 이미 청산된 것으로 간주
            if position_amt == 0:
                debug_message(f"포지션 이미 청산됨: {symbol}", "INFO")
                if symbol in open_trades:
                    del open_trades[symbol]
                return
                
            # 포지션 크기 계산
            position_size = abs(position_amt) * entry_price
            
            # 포지션 청산 시도
            try:
                # 청산 주문 실행
                close_position(symbol, abs(position_amt), "short" if direction == "long" else "long")
                debug_message(f"포지션 청산 주문 실행: {symbol}", "INFO")
                
                # 모든 미체결 주문 취소
                try:
                    open_orders = client.futures_get_open_orders(symbol=symbol)
                    if open_orders:
                        for order in open_orders:
                            try:
                                client.futures_cancel_order(symbol=symbol, orderId=order['orderId'])
                                debug_message(f"미체결 주문 취소: {symbol} - {order['orderId']}", "INFO")
                            except Exception as e:
                                debug_message(f"주문 취소 실패: {symbol} - {order['orderId']} - {str(e)}", "ERROR")
                except Exception as e:
                    debug_message(f"미체결 주문 조회 실패: {symbol} - {str(e)}", "ERROR")
                
            except Exception as e:
                debug_message(f"포지션 청산 주문 실패: {symbol} - {str(e)}", "ERROR")
                return
            
        except Exception as e:
            debug_message(f"포지션 정보 조회 실패: {symbol} - {str(e)}", "ERROR")
            # 기본값으로 계산
            position_size = qty * entry_price
        
        # 수익금 계산
        if direction == "long":
            pnl = (exit_price - entry_price) * position_size
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        else:  # short
            pnl = (entry_price - exit_price) * position_size
            pnl_pct = ((entry_price - exit_price) / entry_price) * 100
            
        # 수수료 계산 (0.04% = 0.0004)
        fee = position_size * exit_price * 0.0004
        net_pnl = pnl - fee
        
        # 이모지 설정
        if exit_reason == 'TP':
            reason_emoji = '🎯'
        else:  # SL
            reason_emoji = '🛑'
            
        if net_pnl > 0:
            pnl_emoji = '💰'
        else:
            pnl_emoji = '💸'
            
        # 포지션 정보
        position_info = f"{direction.upper()} {position_size:.4f} @ {entry_price:.4f}"
        
        # 메시지 전송
        message = (
            f"{reason_emoji} 포지션 종료: `{symbol}`\n"
            f"   ├ 포지션: `{position_info}`\n"
            f"   ├ 종료가: `{exit_price:.4f}`\n"
            f"   ├ 수익금: {pnl_emoji} `{net_pnl:.2f} USDT`\n"
            f"   └ 수익률: {pnl_emoji} `{pnl_pct:.2f}%`"
        )
        send_telegram_message(message)
        
        # 거래 내역 저장
        trade_history = {
            'symbol': symbol,
            'position_type': direction.upper(),
            'entry_price': entry_price,
            'exit_price': exit_price,
            'position_size': position_size,
            'pnl': net_pnl,
            'pnl_pct': pnl_pct,
            'exit_reason': exit_reason,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # 오늘 날짜의 거래 내역에 추가
        today = datetime.now().strftime('%Y-%m-%d')
        if today not in trade_history_data:
            trade_history_data[today] = {
                'trades': [],
                'summary': {
                    'total_trades': 0,
                    'win_rate': 0,
                    'total_profit': 0,
                    'total_loss': 0,
                    'open_positions': []
                }
            }
            
        trade_history_data[today]['trades'].append(trade_history)
        
        # 요약 정보 업데이트
        summary = trade_history_data[today]['summary']
        summary['total_trades'] += 1
        
        if net_pnl > 0:
            summary['total_profit'] += net_pnl
            daily_stats["winning_trades"] += 1
            daily_stats["consecutive_losses"] = 0  # 연속 손실 카운트 리셋
        else:
            summary['total_loss'] += abs(net_pnl)
            daily_stats["losing_trades"] += 1
            daily_stats["consecutive_losses"] += 1
            
        # 승률 계산
        winning_trades = len([t for t in trade_history_data[today]['trades'] if t['pnl'] > 0])
        summary['win_rate'] = (winning_trades / summary['total_trades']) * 100
        
        # 거래 내역 저장
        save_trade_history()
        
        # 열린 포지션에서 제거
        if symbol in open_trades:
            del open_trades[symbol]
            
        # market_maker_orders에서도 제거
        if symbol in market_maker_orders:
            del market_maker_orders[symbol]
        
        debug_message(f"포지션 종료 완료: {symbol} - {exit_reason}", "INFO")
        
    except Exception as e:
        debug_message(f"포지션 종료 처리 실패: {symbol} - {str(e)}", "ERROR")

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
            
            # 실제 포지션 정보 업데이트
            for position in positions:
                symbol = position['symbol']
                position_amt = float(position['positionAmt'])
                if position_amt != 0:
                    real_symbols.add(symbol)
                    if symbol not in open_trades:
                        send_telegram_message(f"⚠️ [점검] 실계좌에만 존재하는 포지션 발견: {symbol}. open_trades에 추가합니다.")
                        entry_price = float(position['entryPrice'])
                        current_price = float(position['markPrice'])
                        direction = 'long' if position_amt > 0 else 'short'
                        qty = abs(position_amt)
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
                    else:
                        # 기존 포지션 정보 업데이트
                        open_trades[symbol]['current_price'] = float(position['markPrice'])
                        open_trades[symbol]['qty'] = abs(position_amt)

            # 3. 미체결 주문 정리
            try:
                all_open_orders = client.futures_get_open_orders()
                order_count = len(all_open_orders)
                if order_count > CONFIG["max_open_positions"] * 2:  # 최대 포지션 수의 2배를 초과하는 경우
                    send_telegram_message(f"⚠️ [점검] 미체결 주문이 너무 많습니다 ({order_count}개). 정리합니다.")
                    for order in all_open_orders:
                        try:
                            client.futures_cancel_order(symbol=order['symbol'], orderId=order['orderId'])
                        except Exception as e:
                            continue
            except Exception as e:
                send_telegram_message(f"⚠️ [점검] 미체결 주문 정리 실패: {str(e)}")

            # 4. open_trades 정리
            for symbol in list(open_trades.keys()):
                if symbol not in real_symbols:
                    send_telegram_message(f"⚠️ [점검] open_trades에만 존재하는 포지션 발견: {symbol}. 제거합니다.")
                    del open_trades[symbol]

            # 5. market_maker_orders 정리
            current_time = datetime.now()
            for symbol in list(market_maker_orders.keys()):
                if (current_time - market_maker_orders[symbol]).total_seconds() > 1800:  # 30분 이상 지난 주문
                    del market_maker_orders[symbol]

            # 6. 거래 이력 저장
            save_trade_history()

            # 7. 시스템 리소스 점검
            cpu_usage = psutil.cpu_percent()
            memory_usage = psutil.virtual_memory().percent
            if cpu_usage > CONFIG["monitoring"]["max_cpu_usage"]:
                send_telegram_message(f"⚠️ [점검] CPU 사용률 높음: {cpu_usage}%")
            if memory_usage > CONFIG["monitoring"]["max_memory_usage"]:
                send_telegram_message(f"⚠️ [점검] 메모리 사용률 높음: {memory_usage}%")

            # 8. 상태 리포트
            status_msg = f"""
🤖 [점검] 시스템 상태
├ 현재 포지션: {len(open_trades)}개
├ 미체결 주문: {order_count}개
├ 활성 그리드: {len(market_maker_orders)}개
└ 시스템 리소스: CPU {cpu_usage}%, 메모리 {memory_usage}%
"""
            send_telegram_message(status_msg)

        except Exception as e:
            send_telegram_message(f"💥 [점검] 주기적 점검 루프 오류: {str(e)}")
        time.sleep(600)  # 10분마다 반복

def start_websocket_thread():
    """
    웹소켓 연결을 위한 별도 스레드 시작
    """
    websocket_thread = threading.Thread(target=start_websocket_connections, daemon=True)
    websocket_thread.start()
    return websocket_thread

def wave_trade_watcher():
    """
    파동 기반 트레이드 감시 루프
    """
    send_telegram_message("🌊 파동 기반 진입 감시 시작...")

    # 거래 내역 초기화
    initialize_trade_history()
    
    # 웹소켓 연결을 별도 스레드로 시작
    websocket_thread = start_websocket_thread()
    
    # 웹소켓 연결이 시작될 때까지 잠시 대기
    time.sleep(2)
    
    # 초기 상태 리포트
    try:
        account = rate_limited_api_call(client.futures_account)
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
    except Exception as e:
        debug_message(f"초기 상태 리포트 생성 실패: {str(e)}", "ERROR")
    
    # 포지션 모니터링 스레드 시작
    monitor_thread = threading.Thread(target=monitor_positions, daemon=True)
    monitor_thread.start()
    
    # 웹소켓 모니터링 스레드 시작
    websocket_monitor_thread = threading.Thread(target=monitor_websocket_connection, daemon=True)
    websocket_monitor_thread.start()
    
    consecutive_errors = 0
    last_report_time = datetime.utcnow()
    last_market_analysis_time = datetime.utcnow()
    last_health_check_time = datetime.utcnow()
    last_status_time = datetime.utcnow()
    last_position_sync_time = datetime.utcnow()

    while True:
        try:
            # 시스템 상태 체크 (5분마다)
            if (datetime.utcnow() - last_health_check_time).total_seconds() > CONFIG["monitoring"]["check_interval"]:
                if not check_system_health():
                    time.sleep(300)
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

            # 포지션 동기화 (5분마다)
            if (datetime.utcnow() - last_position_sync_time).total_seconds() > 300:
                try:
                    positions = rate_limited_api_call(client.futures_position_information)
                    real_symbols = set()
                    
                    for position in positions:
                        symbol = position['symbol']
                        position_amt = float(position['positionAmt'])
                        if position_amt != 0:
                            real_symbols.add(symbol)
                            if symbol not in open_trades:
                                entry_price = float(position['entryPrice'])
                                current_price = float(position['markPrice'])
                                direction = 'long' if position_amt > 0 else 'short'
                                qty = abs(position_amt)
                                
                                # TP/SL 계산
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
                    
                    # 존재하지 않는 포지션 제거
                    for symbol in list(open_trades.keys()):
                        if symbol not in real_symbols:
                            del open_trades[symbol]
                    
                    last_position_sync_time = datetime.utcnow()
                    
                except Exception as e:
                    debug_message(f"포지션 동기화 실패: {str(e)}", "ERROR")
                    time.sleep(60)

            # 거래 신호 확인
            symbols = get_top_symbols(20)
            if not symbols:
                time.sleep(30)
                continue

            for symbol in symbols:
                try:
                    if symbol in open_trades:
                        continue

                    df = get_1m_klines(symbol, interval="3m", limit=120)
                    if df.empty or len(df) < 60:
                        continue

                    wave_info = analyze_wave_from_df(df)
                    if wave_info:
                        if execute_momentum_strategy(symbol, df) or \
                           execute_breakout_strategy(symbol, df) or \
                           execute_arbitrage_strategy(symbol):
                            enter_trade_from_wave(symbol, wave_info, df['close'].iloc[-1])

                except Exception as e:
                    debug_message(f"{symbol} 처리 중 오류: {str(e)}", "ERROR")
                    continue

            # 마켓 메이커 전략 실행
            if CONFIG["market_maker"]["enabled"]:
                for symbol in symbols:
                    if len(open_trades) < CONFIG["market_maker"]["max_positions"]:
                        execute_market_maker_strategy(symbol)

            consecutive_errors = 0
            time.sleep(60)

        except Exception as e:
            consecutive_errors += 1
            error_msg = f"💥 파동 감시 오류: {e}"
            if consecutive_errors >= 3:
                error_msg += "\n⚠️ 연속 3회 이상 오류 발생. 5분 대기 후 재시도합니다."
                time.sleep(300)
            else:
                time.sleep(30)
            send_telegram_message(error_msg)

def start_websocket_connections():
    global ws, ws_connected
    try:
        # 기존 연결 종료
        if ws is not None:
            try:
                ws.close()
            except:
                pass
            ws = None
        
        ws_connected = False
        #debug_message("웹소켓 연결 시작...", "INFO")
        
        # 웹소켓 연결 설정
        ws = websocket.WebSocketApp(
            "wss://fstream.binance.com/ws",
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )
        
        # 연결 옵션 설정
        ws.run_forever(
            ping_interval=20,
            ping_timeout=10,
            skip_utf8_validation=True,
            sslopt={"cert_reqs": ssl.CERT_NONE}
        )
        
    except Exception as e:
        #debug_message(f"웹소켓 연결 실패: {str(e)}", "ERROR")
        ws_connected = False
        time.sleep(ws_reconnect_delay)
        # 재귀 호출 제거
        return False
    return True

def is_websocket_connected():
    """
    웹소켓 연결 상태 확인
    """
    global ws, ws_connected
    try:
        if ws is None:
            return False
        if not hasattr(ws, 'sock'):
            return False
        if ws.sock is None:
            return False
        return ws.sock.connected and ws_connected
    except:
        return False

def on_error(ws, error):
    """
    웹소켓 에러 처리
    """
    global ws_connected
    #debug_message(f"웹소켓 에러: {str(error)}", "ERROR")
    ws_connected = False
    time.sleep(ws_reconnect_delay * 2)  # 재연결 대기 시간 2배로 증가
    try:
        if ws is not None:
            ws.close()
    except:
        pass
    # 재귀 호출 제거
    return False

def on_close(ws, close_status_code, close_msg):
    """
    웹소켓 연결 종료 처리
    """
    global ws_connected
    #debug_message(f"웹소켓 연결 종료됨 (코드: {close_status_code}, 메시지: {close_msg})", "INFO")
    ws_connected = False
    time.sleep(ws_reconnect_delay)
    try:
        if ws is not None:
            ws.close()
    except:
        pass
    # 재귀 호출 제거
    return False

def on_open(ws):
    """
    웹소켓 연결 시작 처리
    """
    global ws_connected
    try:
        ws_connected = True
        # 구독할 심볼 목록
        symbols = list(open_trades.keys())
        if CONFIG["market_maker"]["enabled"]:
            # 시총 상위 심볼 가져오기
            top_symbols = get_top_symbols(20)
            if top_symbols:
                symbols.extend(top_symbols)
            
            # 현재 활성화된 그리드 주문 심볼 추가
            current_time = datetime.now()
            active_symbols = [sym for sym, time in market_maker_orders.items() 
                            if (current_time - time).total_seconds() < 1800]
            symbols.extend(active_symbols)
        
        # 중복 제거 및 정렬
        symbols = sorted(list(set(symbols)))
        
        # 구독 메시지 전송 (배치 처리)
        batch_size = 3  # 한 번에 3개씩 구독으로 감소
        for i in range(0, len(symbols), batch_size):
            batch_symbols = symbols[i:i + batch_size]
            try:
                subscribe_message = {
                    "method": "SUBSCRIBE",
                    "params": [f"{symbol.lower()}@bookTicker" for symbol in batch_symbols],
                    "id": 1
                }
                ws.send(json.dumps(subscribe_message))
                
                # price_sockets 초기화
                for symbol in batch_symbols:
                    price_sockets[symbol] = {'bid': 0, 'ask': 0}
                
                debug_message(f"웹소켓 구독: {', '.join(batch_symbols)}", "INFO")
                time.sleep(2)  # 구독 요청 사이에 2초 대기로 증가
                
            except Exception as e:
                #debug_message(f"웹소켓 구독 실패 (배치 {i//batch_size + 1}): {str(e)}", "ERROR")
                continue
        
        debug_message(f"웹소켓 구독 완료: {len(symbols)}개 심볼", "INFO")
        
    except Exception as e:
        #debug_message(f"웹소켓 구독 실패: {str(e)}", "ERROR")
        ws_connected = False
        time.sleep(ws_reconnect_delay)
        try:
            if ws is not None:
                ws.close()
        except:
            pass
        start_websocket_connections()

def enter_trade_from_wave(symbol: str, wave_info: dict, current_price: float):
    """
    파동 분석 결과를 기반으로 포지션 진입
    """
    try:
        # 이미 포지션이 있는 경우 스킵
        if symbol in open_trades:
            return
            
        # 최대 포지션 수 체크
        if len(open_trades) >= CONFIG["max_open_positions"]:
            debug_message(f"최대 포지션 수 도달: {CONFIG['max_open_positions']}개", "INFO")
            return
            
        # 거래 시간 체크
        if not is_trading_allowed():
            debug_message("현재 거래 시간이 아님", "INFO")
            return
            
        # 일일 손실 제한 체크
        if not check_daily_loss_limit():
            debug_message("일일 손실 제한 도달", "WARNING")
            return
            
        # 변동성 계산
        df = get_1m_klines(symbol, interval="3m", limit=20)
        volatility = calculate_volatility(df)
        
        # 포지션 크기 계산
        position_size = calculate_position_size(symbol, current_price, volatility)
        
        # 리스크 제한 체크
        direction = "long" if wave_info["direction"] == "up" else "short"
        if not check_risk_limits(symbol, direction, position_size):
            return
            
        # 동적 SL 계산
        sl = calculate_dynamic_sl(df, direction)
        if sl is None:
            sl = current_price * 0.985 if direction == "long" else current_price * 1.015
            
        # TP 계산
        tp = current_price * 1.015 if direction == "long" else current_price * 0.985
        
        # 모드 결정
        mode = determine_trade_mode_from_wave(wave_info)
        
        # 포지션 진입
        try:
            # 레버리지 설정
            client.futures_change_leverage(symbol=symbol, leverage=CONFIG["leverage"])
            
            # 주문 실행
            order = client.futures_create_order(
                symbol=symbol,
                side="BUY" if direction == "long" else "SELL",
                type="MARKET",
                quantity=position_size
            )
            
            # 포지션 정보 저장
            open_trades[symbol] = {
                'entry_price': current_price,
                'direction': direction,
                'qty': position_size,
                'tp': tp,
                'sl': sl,
                'mode': mode,
                'current_price': current_price,
                'leverage': CONFIG["leverage"]
            }
            
            # TP/SL 주문
            client.futures_create_order(
                symbol=symbol,
                side="SELL" if direction == "long" else "BUY",
                type="TAKE_PROFIT_MARKET",
                stopPrice=tp,
                closePosition=True
            )
            
            client.futures_create_order(
                symbol=symbol,
                side="SELL" if direction == "long" else "BUY",
                type="STOP_MARKET",
                stopPrice=sl,
                closePosition=True
            )
            
            # 메시지 전송
            message = f"""
🎯 포지션 진입: `{symbol}`
   ├ 방향     : `{direction.upper()}`
   ├ 진입가   : `{round(current_price, 4)}`
   ├ 수량     : `{round(position_size, 4)}`
   ├ 레버리지 : `{CONFIG["leverage"]}x`
   ├ TP       : `{round(tp, 4)}`
   ├ SL       : `{round(sl, 4)}`
   └ 모드     : `{mode}`
"""
            send_telegram_message(message)
            
            # 거래 내역 업데이트
            daily_stats["total_trades"] += 1
            
        except Exception as e:
            debug_message(f"포지션 진입 실패: {symbol} - {str(e)}", "ERROR")
            
    except Exception as e:
        debug_message(f"포지션 진입 처리 실패: {symbol} - {str(e)}", "ERROR")

def execute_market_maker_strategy(symbol: str):
    """
    마켓 메이커 전략 실행
    """
    try:
        if not CONFIG["market_maker"]["enabled"]:
            return
            
        # 주문 상태 확인 (더 엄격한 체크)
        current_time = datetime.now()
        
        # 1. 현재 활성 그리드 주문 수 확인
        active_grid_orders = sum(1 for sym in market_maker_orders.keys() 
                               if (current_time - market_maker_orders[sym]).total_seconds() < 1800)
        if active_grid_orders >= CONFIG["market_maker"]["max_positions"]:
            active_symbols = [sym for sym, time in market_maker_orders.items() 
                            if (current_time - time).total_seconds() < 1800]
            remaining_times = [f"{sym}({int((1800 - (current_time - time).total_seconds()) / 60)}분)" 
                             for sym, time in market_maker_orders.items() 
                             if (current_time - time).total_seconds() < 1800]
            
            debug_message(f"마켓 메이커 상태:\n"
                        f"   ├ 활성 그리드: {active_grid_orders}/{CONFIG['market_maker']['max_positions']}개\n"
                        f"   ├ 활성 심볼: {', '.join(active_symbols)}\n"
                        f"   └ 남은 시간: {', '.join(remaining_times)}", "INFO")
            return
            
        # 2. 해당 심볼의 최근 주문 확인
        if symbol in market_maker_orders:
            last_order_time = market_maker_orders[symbol]
            time_diff = (current_time - last_order_time).total_seconds()
            if time_diff < 1800:  # 30분 이내
                remaining_minutes = int((1800 - time_diff) / 60)
                debug_message(f"마켓 메이커: {symbol} 상태\n"
                            f"   ├ 마지막 주문: {last_order_time.strftime('%H:%M:%S')}\n"
                            f"   └ 남은 시간: {remaining_minutes}분", "INFO")
                return
            
        # 3. 기존 주문 확인
        try:
            # 미체결 주문 확인
            open_orders = client.futures_get_open_orders(symbol=symbol)
            if open_orders:
                order_details = [f"{order['side']} @ {order['price']}" for order in open_orders]
                debug_message(f"마켓 메이커: {symbol} 미체결 주문\n"
                            f"   ├ 주문 수: {len(open_orders)}개\n"
                            f"   └ 주문 내역: {', '.join(order_details)}", "INFO")
                return
                
            # 포지션 확인
            position_info = client.futures_position_information(symbol=symbol)
            if position_info and float(position_info[0]['positionAmt']) != 0:
                position = position_info[0]
                position_amt = float(position['positionAmt'])
                entry_price = float(position['entryPrice'])
                current_price = float(position['markPrice'])
                pnl = float(position['unRealizedProfit'])
                
                debug_message(f"마켓 메이커: {symbol} 포지션 정보\n"
                            f"   ├ 방향: {'LONG' if position_amt > 0 else 'SHORT'}\n"
                            f"   ├ 수량: {abs(position_amt)}\n"
                            f"   ├ 진입가: {entry_price}\n"
                            f"   ├ 현재가: {current_price}\n"
                            f"   └ 미실현 손익: {pnl:.2f} USDT", "INFO")
                return
                
            # 최근 주문 내역 확인 (30분 이내)
            recent_orders = client.futures_get_all_orders(symbol=symbol, limit=50)
            if recent_orders:
                recent_active = False
                for order in recent_orders:
                    order_time = datetime.fromtimestamp(order['time'] / 1000)
                    if (current_time - order_time).total_seconds() < 1800:
                        recent_active = True
                        debug_message(f"마켓 메이커: {symbol} 최근 주문\n"
                                    f"   ├ 시간: {order_time.strftime('%H:%M:%S')}\n"
                                    f"   ├ 유형: {order['type']}\n"
                                    f"   └ 상태: {order['status']}", "INFO")
                        break
                if recent_active:
                    return
                    
        except Exception as e:
            debug_message(f"마켓 메이커: {symbol} 주문 조회 실패 - {str(e)}", "ERROR")
            return
            
        # 4. 현재가 조회
        ticker = client.futures_symbol_ticker(symbol=symbol)
        current_price = float(ticker['price'])
        
        # 5. 심볼 정보 가져오기 (캐싱 적용)
        symbol_info = get_symbol_info(symbol)
        if not symbol_info:
            debug_message(f"마켓 메이커: {symbol} 심볼 정보 없음", "ERROR")
            return
            
        # 6. 필터 확인
        lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
        price_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'PRICE_FILTER'), None)
        
        if not lot_size_filter or not price_filter:
            debug_message(f"마켓 메이커: {symbol} 필터 정보 없음", "ERROR")
            return
            
        # 7. 수량 및 가격 정밀도 계산
        min_qty = float(lot_size_filter['minQty'])
        step_size = float(lot_size_filter['stepSize'])
        tick_size = float(price_filter['tickSize'])
        price_precision = len(str(tick_size).split('.')[-1].rstrip('0'))
        
        # 8. 포지션 크기 계산
        position_size = CONFIG["min_position_size"] / current_price
        position_size = round(position_size / step_size) * step_size
        if position_size < min_qty:
            position_size = min_qty
            
        # 9. 그리드 레벨 설정
        grid_levels = min(CONFIG["market_maker"]["grid_levels"], 3)  # 최대 3개 레벨로 제한
        grid_distance = CONFIG["market_maker"]["grid_distance"] / 100
        
        # 10. 주문 생성 전 최종 확인
        try:
            final_check = client.futures_get_open_orders(symbol=symbol)
            if final_check:
                debug_message(f"마켓 메이커: {symbol} 최종 확인 - 기존 주문 발견", "INFO")
                return
        except Exception as e:
            debug_message(f"마켓 메이커: {symbol} 최종 확인 실패 - {str(e)}", "ERROR")
            return
        
        # 11. 주문 생성
        orders_created = False
        order_details = []
        
        # 레버리지 설정
        client.futures_change_leverage(symbol=symbol, leverage=CONFIG["leverage"])
        
        for i in range(grid_levels):
            # 매수 주문
            buy_price = current_price * (1 - grid_distance * (i + 1))
            buy_price = round(buy_price / tick_size) * tick_size
            buy_price = round(buy_price, price_precision)
            
            try:
                client.futures_create_order(
                    symbol=symbol,
                    side="BUY",
                    type="LIMIT",
                    timeInForce="GTC",
                    quantity=position_size,
                    price=buy_price
                )
                orders_created = True
                order_details.append(f"BUY @ {buy_price}")
                time.sleep(0.1)  # 주문 사이에 0.1초 대기
            except Exception as e:
                debug_message(f"마켓 메이커: {symbol} 매수 주문 실패 - {str(e)}", "ERROR")
                return
            
            # 매도 주문
            sell_price = current_price * (1 + grid_distance * (i + 1))
            sell_price = round(sell_price / tick_size) * tick_size
            sell_price = round(sell_price, price_precision)
            
            try:
                client.futures_create_order(
                    symbol=symbol,
                    side="SELL",
                    type="LIMIT",
                    timeInForce="GTC",
                    quantity=position_size,
                    price=sell_price
                )
                orders_created = True
                order_details.append(f"SELL @ {sell_price}")
                time.sleep(0.1)  # 주문 사이에 0.1초 대기
            except Exception as e:
                debug_message(f"마켓 메이커: {symbol} 매도 주문 실패 - {str(e)}", "ERROR")
                return
        
        # 12. 주문 생성 성공 시 시간 기록
        if orders_created:
            market_maker_orders[symbol] = current_time
            debug_message(f"마켓 메이커: {symbol} 그리드 주문 생성\n"
                        f"   ├ 현재가: {current_price}\n"
                        f"   ├ 수량: {position_size}\n"
                        f"   ├ 레버리지: {CONFIG['leverage']}x\n"
                        f"   ├ 레벨: {grid_levels}\n"
                        f"   └ 주문 내역: {', '.join(order_details)}", "INFO")
        
    except Exception as e:
        debug_message(f"마켓 메이커 전략 실행 실패: {symbol} - {str(e)}", "ERROR")

def get_top_symbols(limit: int = 20) -> List[str]:
    """
    거래량 기준 상위 심볼 목록 반환 (캐싱 적용)
    """
    global last_top_symbols_update, top_symbols_cache
    
    current_time = datetime.now()
    
    # 캐시가 있고 5분 이내인 경우 캐시된 데이터 반환
    if top_symbols_cache and last_top_symbols_update and \
       (current_time - last_top_symbols_update).total_seconds() < 300:
        return top_symbols_cache[:limit]
    
    try:
        # 24시간 티커 정보 가져오기 (API 요청 제한 적용)
        tickers = rate_limited_api_call(client.futures_ticker)
        
        # USDT 마켓만 필터링
        usdt_tickers = [t for t in tickers if t['symbol'].endswith('USDT')]
        
        # 거래량 기준 정렬
        sorted_tickers = sorted(usdt_tickers, 
                              key=lambda x: float(x['quoteVolume']), 
                              reverse=True)
        
        # 상위 심볼 추출
        top_symbols = [t['symbol'] for t in sorted_tickers[:limit]]
        
        # 캐시 업데이트
        top_symbols_cache = top_symbols
        last_top_symbols_update = current_time
        
        return top_symbols
        
    except Exception as e:
        debug_message(f"거래금액 순위 가져오기 실패: {str(e)}", "ERROR")
        # 캐시된 데이터가 있으면 반환
        if top_symbols_cache:
            return top_symbols_cache[:limit]
        return []

def get_symbol_info(symbol: str) -> Optional[Dict]:
    """
    심볼 정보 조회 (캐싱 적용)
    """
    global symbol_info_cache, last_symbol_info_update
    
    current_time = datetime.now()
    
    # 캐시가 있고 1시간 이내인 경우 캐시된 데이터 반환
    if symbol in symbol_info_cache and symbol in last_symbol_info_update and \
       (current_time - last_symbol_info_update[symbol]).total_seconds() < 3600:
        return symbol_info_cache[symbol]
    
    try:
        # 심볼 정보 조회
        info = client.futures_exchange_info()
        symbol_info = next((s for s in info['symbols'] if s['symbol'] == symbol), None)
        
        if symbol_info:
            # 캐시 업데이트
            symbol_info_cache[symbol] = symbol_info
            last_symbol_info_update[symbol] = current_time
            
        return symbol_info
        
    except Exception as e:
        debug_message(f"심볼 정보 조회 실패 ({symbol}): {str(e)}", "ERROR")
        # 캐시된 데이터가 있으면 반환
        return symbol_info_cache.get(symbol)

def rate_limited_api_call(func, *args, **kwargs):
    """
    API 요청 제한을 관리하는 래퍼 함수
    """
    global last_api_request
    
    func_name = func.__name__
    current_time = time.time()
    
    # 마지막 요청 시간 확인
    if func_name in last_api_request:
        time_since_last = current_time - last_api_request[func_name]
        if time_since_last < api_request_delay:
            time.sleep(api_request_delay - time_since_last)
    
    try:
        result = func(*args, **kwargs)
        last_api_request[func_name] = time.time()
        return result
    except Exception as e:
        if "Way too many requests" in str(e):
            debug_message(f"API 요청 제한 도달. 1분 대기 후 재시도합니다.", "WARNING")
            time.sleep(60)  # 1분 대기
            return rate_limited_api_call(func, *args, **kwargs)
        raise e

def on_message(ws, message):
    """
    웹소켓 메시지 수신 처리
    """
    try:
        data = json.loads(message)
        
        # 가격 업데이트 처리
        if 'e' in data and data['e'] == 'bookTicker':
            symbol = data['s']
            if symbol in price_sockets:
                price_sockets[symbol]['bid'] = float(data['b'])
                price_sockets[symbol]['ask'] = float(data['a'])
                
                # 포지션 업데이트
                if symbol in open_trades:
                    trade = open_trades[symbol]
                    current_price = float(data['b']) if trade['direction'] == 'long' else float(data['a'])
                    trade['current_price'] = current_price
                    
                    # TP/SL 체크
                    if trade['direction'] == 'long':
                        if current_price >= trade['tp']:
                            debug_message(f"TP 도달 (웹소켓): {symbol}\n"
                                        f"   ├ 현재가: {current_price}\n"
                                        f"   └ TP: {trade['tp']}", "INFO")
                            process_trade_exit(symbol, current_price, 'TP')
                        elif current_price <= trade['sl']:
                            debug_message(f"SL 도달 (웹소켓): {symbol}\n"
                                        f"   ├ 현재가: {current_price}\n"
                                        f"   └ SL: {trade['sl']}", "INFO")
                            process_trade_exit(symbol, current_price, 'SL')
                    else:  # short
                        if current_price <= trade['tp']:
                            debug_message(f"TP 도달 (웹소켓): {symbol}\n"
                                        f"   ├ 현재가: {current_price}\n"
                                        f"   └ TP: {trade['tp']}", "INFO")
                            process_trade_exit(symbol, current_price, 'TP')
                        elif current_price >= trade['sl']:
                            debug_message(f"SL 도달 (웹소켓): {symbol}\n"
                                        f"   ├ 현재가: {current_price}\n"
                                        f"   └ SL: {trade['sl']}", "INFO")
                            process_trade_exit(symbol, current_price, 'SL')
                    
                    # 트레일링 스탑 업데이트
                    update_trailing_stop(symbol, current_price)
                    
                    # 부분 익절 체크
                    check_partial_tp(symbol, current_price)
                    
                    # 그리드 전략 청산 체크
                    if trade.get('mode') == 'grid':
                        if check_grid_exit(symbol, trade):
                            debug_message(f"그리드 청산 조건 도달: {symbol}", "INFO")
                            process_trade_exit(symbol, current_price, 'GRID')
        
    except Exception as e:
        debug_message(f"웹소켓 메시지 처리 오류: {str(e)}", "ERROR")

def monitor_positions():
    """
    주기적으로 포지션 상태를 체크하는 함수
    """
    last_price_update = {}  # 가격 업데이트 시간 추적
    price_cache = {}  # 가격 캐시
    
    while True:
        try:
            current_time = datetime.now()
            
            for symbol in list(open_trades.keys()):
                try:
                    # 가격 캐시 확인 (1초 이내면 캐시된 가격 사용)
                    if symbol in price_cache and symbol in last_price_update and \
                       (current_time - last_price_update[symbol]).total_seconds() < 1:
                        current_price = price_cache[symbol]
                    else:
                        # 웹소켓에서 가격 정보 확인
                        if symbol in price_sockets:
                            current_price = price_sockets[symbol]['bid'] if open_trades[symbol]['direction'] == 'long' else price_sockets[symbol]['ask']
                            price_cache[symbol] = current_price
                            last_price_update[symbol] = current_time
                        else:
                            # 웹소켓 정보가 없을 때만 API 호출 (API 요청 제한 적용)
                            ticker = rate_limited_api_call(client.futures_symbol_ticker, symbol=symbol)
                            current_price = float(ticker['price'])
                            price_cache[symbol] = current_price
                            last_price_update[symbol] = current_time
                    
                    trade = open_trades[symbol]
                    trade['current_price'] = current_price
                    
                    # TP/SL 체크
                    if trade['direction'] == 'long':
                        if current_price >= trade['tp']:
                            debug_message(f"TP 도달 (모니터링): {symbol}\n"
                                        f"   ├ 현재가: {current_price}\n"
                                        f"   └ TP: {trade['tp']}", "INFO")
                            process_trade_exit(symbol, current_price, 'TP')
                        elif current_price <= trade['sl']:
                            debug_message(f"SL 도달 (모니터링): {symbol}\n"
                                        f"   ├ 현재가: {current_price}\n"
                                        f"   └ SL: {trade['sl']}", "INFO")
                            process_trade_exit(symbol, current_price, 'SL')
                    else:  # short
                        if current_price <= trade['tp']:
                            debug_message(f"TP 도달 (모니터링): {symbol}\n"
                                        f"   ├ 현재가: {current_price}\n"
                                        f"   └ TP: {trade['tp']}", "INFO")
                            process_trade_exit(symbol, current_price, 'TP')
                        elif current_price >= trade['sl']:
                            debug_message(f"SL 도달 (모니터링): {symbol}\n"
                                        f"   ├ 현재가: {current_price}\n"
                                        f"   └ SL: {trade['sl']}", "INFO")
                            process_trade_exit(symbol, current_price, 'SL')
                    
                    # 트레일링 스탑 업데이트
                    update_trailing_stop(symbol, current_price)
                    
                    # 부분 익절 체크
                    check_partial_tp(symbol, current_price)
                    
                except Exception as e:
                    debug_message(f"포지션 모니터링 오류 ({symbol}): {str(e)}", "ERROR")
                    time.sleep(1)  # 에러 발생 시 1초 대기
            
            time.sleep(0.5)  # 전체 루프는 0.5초마다 실행
            
        except Exception as e:
            debug_message(f"포지션 모니터링 스레드 오류: {str(e)}", "ERROR")
            time.sleep(5)  # 오류 발생 시 5초 대기

def monitor_websocket_connection():
    """
    웹소켓 연결 상태를 모니터링하고 필요시 재연결
    """
    global ws, ws_connected
    last_message_time = time.time()
    connection_status = {
        'last_message': last_message_time,
        'reconnect_count': 0,
        'last_reconnect': time.time()
    }
    
    while True:
        try:
            current_time = time.time()
            
            # 연결 상태 로깅
            # if ws_connected:
            #     debug_message(f"웹소켓 상태: 연결됨 (마지막 메시지: {int(current_time - connection_status['last_message'])}초 전)", "INFO")
            # else:
            #     debug_message(f"웹소켓 상태: 연결 끊김 (재연결 시도: {connection_status['reconnect_count']}회)", "WARNING")
            
            # 메시지 수신 타임아웃 체크
            if current_time - connection_status['last_message'] > 30:
                debug_message("웹소켓 메시지 수신 타임아웃", "WARNING")
                if ws is not None:
                    ws.close()
                ws_connected = False
                connection_status['reconnect_count'] += 1
                connection_status['last_reconnect'] = current_time
                
                # 재연결 시도
                if start_websocket_connections():
                    connection_status['last_message'] = current_time
                    connection_status['reconnect_count'] = 0
            
            # 재연결 시도 횟수 제한
            if connection_status['reconnect_count'] >= 5:
                debug_message("웹소켓 재연결 시도 횟수 초과. 5분 대기 후 재시도", "ERROR")
                time.sleep(300)  # 5분 대기
                connection_status['reconnect_count'] = 0
            
            time.sleep(5)
            
        except Exception as e:
            debug_message(f"웹소켓 모니터링 오류: {str(e)}", "ERROR")
            time.sleep(5)

def check_websocket_status():
    global ws, ws_connected
    try:
        if ws is None:
            return "연결 없음"
        
        if not ws_connected:
            return "연결 끊김"
        
        if not is_websocket_connected():
            return "소켓 닫힘"
        
        # 핑 테스트
        try:
            ws.ping()
            return "정상"
        except:
            return "핑 실패"
            
    except Exception as e:
        return f"상태 확인 오류: {str(e)}"