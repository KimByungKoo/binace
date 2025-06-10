import pandas as pd
import numpy as np
from binance.client import Client
from datetime import datetime, timedelta
import time
from tqdm import tqdm

class LeaderboardAnalyzer:
    def __init__(self, api_key=None, api_secret=None):
        self.client = Client(api_key, api_secret)
        
    def get_top_traders(self, limit=100):
        """상위 트레이더 목록 가져오기"""
        try:
            # 리더보드 API 호출
            leaderboard = self.client.get_leaderboard()
            return leaderboard[:limit]
        except Exception as e:
            print(f"리더보드 데이터 수집 중 오류 발생: {e}")
            return []
    
    def get_trader_trades(self, trader_id, start_time=None, end_time=None):
        """특정 트레이더의 거래 내역 가져오기"""
        try:
            if not start_time:
                start_time = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
            if not end_time:
                end_time = int(datetime.now().timestamp() * 1000)
                
            trades = self.client.get_trader_trades(
                traderId=trader_id,
                startTime=start_time,
                endTime=end_time
            )
            return trades
        except Exception as e:
            print(f"트레이더 {trader_id}의 거래 내역 수집 중 오류 발생: {e}")
            return []
    
    def analyze_trading_pattern(self, trades):
        """거래 패턴 분석"""
        if not trades:
            return None
            
        df = pd.DataFrame(trades)
        
        # 기본 통계
        stats = {
            'total_trades': len(trades),
            'win_rate': len(df[df['profit'] > 0]) / len(df) * 100,
            'avg_profit': df['profit'].mean(),
            'avg_holding_time': df['holdingTime'].mean(),
            'max_profit': df['profit'].max(),
            'max_loss': df['profit'].min(),
        }
        
        # 시간대별 분석
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['hour'] = df['timestamp'].dt.hour
        
        hourly_stats = df.groupby('hour').agg({
            'profit': ['mean', 'count'],
            'win_rate': lambda x: (x > 0).mean() * 100
        })
        
        # 포지션 크기 분석
        position_sizes = df['positionSize'].value_counts()
        
        return {
            'basic_stats': stats,
            'hourly_stats': hourly_stats,
            'position_sizes': position_sizes
        }
    
    def analyze_top_traders(self, limit=10):
        """상위 트레이더들의 전략 분석"""
        top_traders = self.get_top_traders(limit)
        analysis_results = []
        
        for trader in tqdm(top_traders, desc="트레이더 분석 중"):
            trades = self.get_trader_trades(trader['userId'])
            pattern = self.analyze_trading_pattern(trades)
            
            if pattern:
                analysis_results.append({
                    'trader_id': trader['userId'],
                    'nickname': trader['nickname'],
                    'roi': trader['roi'],
                    'pattern': pattern
                })
            
            # API 호출 제한을 위한 딜레이
            time.sleep(0.5)
        
        return analysis_results

def main():
    # API 키 설정 (선택사항)
    api_key = None
    api_secret = None
    
    analyzer = LeaderboardAnalyzer(api_key, api_secret)
    
    print("상위 트레이더 분석 시작...")
    results = analyzer.analyze_top_traders(limit=10)
    
    # 결과 저장
    pd.DataFrame(results).to_csv('leaderboard_analysis.csv', index=False)
    
    # 결과 출력
    for result in results:
        print(f"\n=== 트레이더: {result['nickname']} (ROI: {result['roi']}%) ===")
        stats = result['pattern']['basic_stats']
        print(f"총 거래 횟수: {stats['total_trades']}")
        print(f"승률: {stats['win_rate']:.2f}%")
        print(f"평균 수익: {stats['avg_profit']:.2f}%")
        print(f"평균 보유 시간: {stats['avg_holding_time']/1000/60:.1f}분")
        print(f"최대 수익: {stats['max_profit']:.2f}%")
        print(f"최대 손실: {stats['max_loss']:.2f}%")

if __name__ == "__main__":
    main() 