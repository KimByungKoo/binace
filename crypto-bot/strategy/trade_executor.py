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
import math

def execute_trades(df: pd.DataFrame) -> List[Dict]:
    """
    백테스트를 위한 거래 실행 함수
    
    Args:
        df: 가격 데이터가 포함된 DataFrame

    Returns:
        List[Dict]: 거래 기록 리스트
    """
    trades = []
    position = None
    
    # RSI 계산
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # 거래량 이동평균
    df['volume_ma'] = df['volume'].rolling(window=20).mean()
    
    for i in range(1, len(df)):
        current = df.iloc[i]
        prev = df.iloc[i-1]
        
        # 1. MA200 기본 조건 확인 (약간 완화)
        ma200_condition = (
            (df['disparity'].iloc[i] < -2.0) &  # 이격도 -2.0% 미만
            (df['angle'].iloc[i] > 0) &
            (df['percent_change'].iloc[i] > 0.1)
        )
        
        # 2. 추가 필터 조건 (약간 완화)
        filter_condition = (
            (df['rsi'].iloc[i] < 35) &  # RSI 35 이하
            (df['volume'].iloc[i] > df['volume_ma'].iloc[i] * 1.5) &  # 거래량 1.5배 이상
            (df['close'].iloc[i] > df['close'].iloc[i-1])
        )
        
        if ma200_condition and filter_condition:
            body = abs(current['close'] - current['open'])
            upper_shadow = current['high'] - max(current['open'], current['close'])
            lower_shadow = min(current['open'], current['close']) - current['low']
            
            is_bullish = current['close'] > current['open']
            is_higher = current['close'] > prev['close']
            has_short_lower_shadow = lower_shadow < body * 0.2
            has_long_upper_shadow = upper_shadow > body * 0.7
            broke_prev_high = current['high'] > prev['high']
            
            # 캔들 패턴 정의
            is_hammer = (
                is_bullish and
                lower_shadow > body * 2.5 and
                upper_shadow < body * 0.2 and
                current['close'] > prev['close']
            )
            
            is_inverted_hammer = (
                is_bullish and
                upper_shadow > body * 2.5 and
                lower_shadow < body * 0.2 and
                current['close'] > prev['close']
            )
            
            is_morning_star = False
            if i >= 2:
                first_candle = df.iloc[i-2]
                second_candle = df.iloc[i-1]
                first_body = abs(first_candle['close'] - first_candle['open'])
                second_body = abs(second_candle['close'] - second_candle['open'])
                is_morning_star = (
                    first_candle['close'] < first_candle['open'] and
                    second_body < first_body * 0.2 and
                    is_bullish and
                    current['close'] > (first_candle['open'] + first_candle['close']) / 2 and
                    current['close'] > prev['close']
                )
            
            is_bullish_engulfing = (
                prev['close'] < prev['open'] and
                is_bullish and
                current['open'] < prev['close'] and
                current['close'] > prev['open'] and
                current['close'] > prev['close'] * 1.02
            )
            
            is_doji = (
                body < (current['high'] - current['low']) * 0.1 and
                current['close'] > prev['close']
            )
            
            # 캔들 패턴 중 1개만 만족해도 진입
            if any([is_hammer, is_inverted_hammer, is_morning_star, is_bullish_engulfing, is_doji]) and position is None:
                position = {
                    'entry_price': current['close'],
                    'entry_time': current.name,
                    'stop_loss': current['close'] * 0.98,  # 손절매 -2.0%
                    'take_profit_1': current['close'] * 1.04,  # 익절 4%
                    'take_profit_2': current['close'] * 1.08,  # 익절 8%
                    'take_profit_3': current['close'] * 1.12,  # 익절 12%
                    'remaining_position': 1.0
                }
        
        if position is not None:
            if current['low'] <= position['stop_loss']:
                profit = (position['stop_loss'] - position['entry_price']) / position['entry_price'] * 100
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': current.name,
                    'entry_price': position['entry_price'],
                    'exit_price': position['stop_loss'],
                    'profit': profit,
                    'exit_type': 'stop_loss'
                })
                position = None
                continue
            
            if current['high'] >= position['take_profit_3'] and position['remaining_position'] > 0:
                exit_amount = position['remaining_position'] * 0.4
                profit = (position['take_profit_3'] - position['entry_price']) / position['entry_price'] * 100
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': current.name,
                    'entry_price': position['entry_price'],
                    'exit_price': position['take_profit_3'],
                    'profit': profit,
                    'exit_type': 'take_profit_3',
                    'position_size': exit_amount
                })
                position['remaining_position'] -= exit_amount
            
            if current['high'] >= position['take_profit_2'] and position['remaining_position'] > 0:
                exit_amount = position['remaining_position'] * 0.3
                profit = (position['take_profit_2'] - position['entry_price']) / position['entry_price'] * 100
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': current.name,
                    'entry_price': position['entry_price'],
                    'exit_price': position['take_profit_2'],
                    'profit': profit,
                    'exit_type': 'take_profit_2',
                    'position_size': exit_amount
                })
                position['remaining_position'] -= exit_amount
            
            if current['high'] >= position['take_profit_1'] and position['remaining_position'] > 0:
                exit_amount = position['remaining_position'] * 0.3
                profit = (position['take_profit_1'] - position['entry_price']) / position['entry_price'] * 100
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': current.name,
                    'entry_price': position['entry_price'],
                    'exit_price': position['take_profit_1'],
                    'profit': profit,
                    'exit_type': 'take_profit_1',
                    'position_size': exit_amount
                })
                position['remaining_position'] -= exit_amount
            
            sell_condition = (
                (df['disparity'].iloc[i] > 2.0) |
                (df['angle'].iloc[i] < 0) |
                (df['percent_change'].iloc[i] < -0.1)
            )
            
            if sell_condition and position['remaining_position'] > 0:
                profit = (current['close'] - position['entry_price']) / position['entry_price'] * 100
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': current.name,
                    'entry_price': position['entry_price'],
                    'exit_price': current['close'],
                    'profit': profit,
                    'exit_type': 'ma200_signal',
                    'position_size': position['remaining_position']
                })
                position = None
    
    return trades

def backtest_ma200_strategy(symbol: str, days: int = 180) -> Dict:
    """
    MA200 전략 백테스트 실행
    
    Args:
        symbol: 심볼
        days: 백테스트 기간 (일)
        
    Returns:
        Dict: 백테스트 결과
    """
    try:
        # 데이터 가져오기
        df = get_1m_klines(symbol, interval="1h", limit=days*24)
        if df.empty:
            return {"error": "데이터 없음"}
        
        # MA200 계산
        df['ma200'] = df['close'].rolling(window=200).mean()
        
        # 이격도 계산
        df['disparity'] = (df['close'] - df['ma200']) / df['ma200'] * 100
        
        # MA200 각도 계산
        df['angle'] = df['ma200'].diff(periods=5) / df['ma200'].shift(5) * 100
        
        # MA200 변화율 계산
        df['percent_change'] = df['ma200'].pct_change(periods=5) * 100
        
        # 거래 실행
        trades = execute_trades(df)
        
        if not trades:
            return {
                "symbol": symbol,
                "total_trades": 0,
                "win_rate": 0,
                "total_profit": 0,
                "max_drawdown": 0,
                "profit_factor": 0
            }
        
        # 결과 분석
        total_trades = len(trades)
        winning_trades = len([t for t in trades if t['profit'] > 0])
        win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0
        
        total_profit = sum(t['profit'] for t in trades)
        
        # 최대 손실폭 계산
        cumulative_profit = 0
        max_profit = 0
        max_drawdown = 0
        
        for trade in trades:
            cumulative_profit += trade['profit']
            max_profit = max(max_profit, cumulative_profit)
            drawdown = max_profit - cumulative_profit
            max_drawdown = max(max_drawdown, drawdown)
        
        # 수익팩터 계산
        total_gain = sum(t['profit'] for t in trades if t['profit'] > 0)
        total_loss = abs(sum(t['profit'] for t in trades if t['profit'] < 0))
        profit_factor = total_gain / total_loss if total_loss > 0 else float('inf')
        
        return {
            "symbol": symbol,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "total_profit": total_profit,
            "max_drawdown": max_drawdown,
            "profit_factor": profit_factor
        }
            
        except Exception as e:
        return {"error": str(e)} 