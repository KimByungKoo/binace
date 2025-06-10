import pandas as pd
import numpy as np
from binance.client import Client
from datetime import datetime, timedelta
import time
from tqdm import tqdm
import os

class MAAlignmentBacktest:
    def __init__(self, api_key=None, api_secret=None):
        self.client = Client(api_key, api_secret)
        self.data_file = '/Users/bkkim/workspace/binace/binace/ohlcv_BTCUSDT_1m_180d.csv'
        
    def get_historical_data(self, symbol='BTCUSDT', interval='1m', lookback='30d'):
        """기존 데이터 파일 사용"""
        print("기존 데이터 파일 로드 중...")
        try:
            df = pd.read_csv(self.data_file)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            print(f"데이터 로드 완료: {len(df)}개의 캔들")
            return df
        except Exception as e:
            print(f"데이터 로드 중 오류 발생: {e}")
            return None
    
    def calculate_mas(self, df):
        """이동평균선 계산"""
        ma_periods = [7, 20, 30, 60, 90, 200]
        for period in ma_periods:
            df[f'MA{period}'] = df['close'].rolling(window=period).mean()
        return df
    
    def check_alignment(self, row):
        """MA 정배열 확인"""
        mas = [row['MA7'], row['MA20'], row['MA30'], row['MA60'], row['MA90'], row['MA200']]
        return all(mas[i] >= mas[i+1] for i in range(len(mas)-1))
    
    def backtest(self, df, initial_balance=10000):
        """백테스트 실행"""
        balance = initial_balance
        position = 0
        entry_price = 0
        trades = []
        half_profit_taken = False
        
        for i in range(200, len(df)):
            current_price = df['close'].iloc[i]
            current_time = df['timestamp'].iloc[i]
            
            # 포지션이 없을 때
            if position == 0 and balance > 0:
                if self.check_alignment(df.iloc[i]):
                    position = balance / current_price
                    entry_price = current_price
                    half_profit_taken = False
                    trades.append({
                        'type': 'entry',
                        'time': current_time,
                        'price': current_price,
                        'position': position,
                        'balance': balance
                    })
            # 포지션이 있을 때
            else:
                # 손절 (-1%)
                if current_price <= entry_price * 0.99:
                    balance += position * current_price
                    trades.append({
                        'type': 'stop_loss',
                        'time': current_time,
                        'price': current_price,
                        'position': position,
                        'balance': balance
                    })
                    position = 0
                    half_profit_taken = False
                # 익절 (+1%)
                elif current_price >= entry_price * 1.01:
                    if not half_profit_taken:
                        # 50% 익절: 잔고에 50%만큼 추가, 포지션 절반만 남김
                        sell_amount = position * 0.5
                        balance += sell_amount * current_price
                        position = position * 0.5
                        half_profit_taken = True
                        trades.append({
                            'type': 'half_take_profit',
                            'time': current_time,
                            'price': current_price,
                            'position': position,
                            'balance': balance
                        })
                    elif current_price <= entry_price:
                        # 나머지 청산: 잔고에 남은 포지션 추가
                        balance += position * current_price
                        trades.append({
                            'type': 'exit_break_even',
                            'time': current_time,
                            'price': current_price,
                            'position': position,
                            'balance': balance
                        })
                        position = 0
                        half_profit_taken = False
                # MA 정배열 깨짐
                elif not self.check_alignment(df.iloc[i]):
                    balance += position * current_price
                    trades.append({
                        'type': 'alignment_break',
                        'time': current_time,
                        'price': current_price,
                        'position': position,
                        'balance': balance
                    })
                    position = 0
                    half_profit_taken = False
        # 마지막 포지션 청산
        if position > 0:
            balance += position * df['close'].iloc[-1]
            trades.append({
                'type': 'final_exit',
                'time': df['timestamp'].iloc[-1],
                'price': df['close'].iloc[-1],
                'position': position,
                'balance': balance
            })
        return trades, balance

def main():
    backtest = MAAlignmentBacktest()
    
    print("BTCUSDT 데이터 로드 중...")
    df = backtest.get_historical_data()
    
    if df is not None:
        print("이동평균선 계산 중...")
        df = backtest.calculate_mas(df)
        
        print("백테스트 실행 중...")
        trades, final_balance = backtest.backtest(df)
        
        # 결과 분석
        trades_df = pd.DataFrame(trades)
        total_trades = len(trades_df[trades_df['type'] == 'entry'])
        winning_trades = len(trades_df[trades_df['type'].isin(['half_take_profit', 'exit_break_even'])])
        
        print("\n=== 백테스트 결과 ===")
        print(f"초기 자본: $10,000")
        print(f"최종 자본: ${final_balance:,.2f}")
        print(f"수익률: {(final_balance/10000 - 1)*100:.2f}%")
        print(f"총 거래 횟수: {total_trades}")
        print(f"승률: {winning_trades/total_trades*100:.2f}%")
        
        # 거래 내역 저장
        trades_df.to_csv('ma_alignment_trades.csv', index=False)
        
        # 상세 거래 내역 출력
        print("\n=== 거래 내역 ===")
        for trade in trades:
            print(f"\n시간: {trade['time']}")
            print(f"유형: {trade['type']}")
            print(f"가격: ${trade['price']:,.2f}")
            print(f"포지션: {trade['position']:.8f}")
            print(f"잔고: ${trade['balance']:,.2f}")

if __name__ == "__main__":
    main() 