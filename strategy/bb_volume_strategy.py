import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import ccxt
import time
import os

def calculate_rsi(df, period=14):
    """RSI 계산"""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def backtest_strategy(df, rsi_threshold=95):
    """전략 백테스트 (RSI 7일 90 이상 & 0.7% TP/SL)"""
    # RSI 계산
    df = calculate_rsi(df, period=7)
    
    balance = 9800  # 초기 자본
    position = None
    entry_price = 0
    entry_time = None
    trades = []
    last_exit_time = None  # 마지막 청산 시간 추가
    
    for i in range(len(df)):
        current_time = df.iloc[i]['timestamp']
        
        # 청산 후 5분 이내면 진입하지 않음
        if last_exit_time and (current_time - last_exit_time).total_seconds() < 300:
            continue
            
        if position is None:  # 포지션이 없을 때
            if df.iloc[i]['RSI'] >= rsi_threshold:
                position = 'short'
                entry_price = df.iloc[i]['close']
                entry_time = current_time
                balance = balance * 0.999  # 수수료 0.1% 차감
                print(f"[ENTRY] {current_time} | 진입가: {entry_price:.2f} | RSI: {df.iloc[i]['RSI']:.2f} | 잔고: {balance:.2f}")
        else:  # 포지션이 있을 때
            if df.iloc[i]['RSI'] < 50:  # RSI가 50 아래로 떨어지면 청산
                exit_price = df.iloc[i]['close']
                pnl = (entry_price - exit_price) / entry_price * 100
                balance = balance * (1 + pnl/100) * 0.999  # 수수료 0.1% 차감
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': current_time,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'balance': balance
                })
                print(f"[EXIT]  {current_time} | 청산가: {exit_price:.2f} | PnL: {pnl:.2f}% | 잔고: {balance:.2f}")
                position = None
                last_exit_time = current_time  # 청산 시간 기록
    
    return trades

def analyze_trades(trades):
    """잔고 변화 위주로 분석"""
    if not trades:
        return {
            'total_trades': 0,
            'final_balance': 0,
            'balance_curve': []
        }
    
    # 잔고 변화 추적
    balance_curve = []
    for t in trades:
        if 'balance' in t:
            balance_curve.append((t['exit_time'], t['balance']))
    final_balance = balance_curve[-1][1] if balance_curve else 0
    
    return {
        'total_trades': len(trades),
        'final_balance': final_balance,
        'balance_curve': balance_curve
    }

def main():
    # 1분봉 데이터 로드 후 15분봉으로 리샘플링
    df = pd.read_csv('/Users/bkkim/workspace/binace/binace/ohlcv_BTCUSDT_1m_180d.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    
    # 15분봉으로 리샘플링
    df_15m = df.resample('15T').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    df_15m.reset_index(inplace=True)
    
    # RSI 기준값 테스트
    rsi_thresholds = [97]  # RSI 기준값
    results = {}
    for rsi_threshold in rsi_thresholds:
        trades = backtest_strategy(df_15m, rsi_threshold=rsi_threshold)
        results[rsi_threshold] = analyze_trades(trades)
        print(f"\n=== RSI {rsi_threshold} 테스트 결과 ===")
        print(f"초기 잔고: 9800.00")
        print(f"총 거래 횟수: {results[rsi_threshold]['total_trades']}")
        print(f"최종 잔고: {results[rsi_threshold]['final_balance']:.2f}")
        print("잔고 변화:")
        for t, bal in results[rsi_threshold]['balance_curve']:
            print(f"{t} | {bal:.2f}")
    
    # 결과 비교
    print("\n=== RSI 기준값별 비교 ===")
    print("RSI 기준값 | 총 거래 | 최종 잔고")
    print("-" * 35)
    for threshold, result in results.items():
        print(f"{threshold:^11} | {result['total_trades']:^6} | {result['final_balance']:.2f}")

if __name__ == "__main__":
    main() 