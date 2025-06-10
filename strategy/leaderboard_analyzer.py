import pandas as pd
import numpy as np
from binance.client import Client
from datetime import datetime, timedelta
import time
from tqdm import tqdm
import requests
import json

class LeaderboardAnalyzer:
    def __init__(self):
        self.base_url = "https://www.binance.com/bapi/futures/v1/public/future/leaderboard"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
    
    def get_top_traders(self, limit=100):
        """상위 트레이더 목록 가져오기"""
        try:
            url = f"{self.base_url}/getLeaderboardRank"
            params = {
                "type": "ALL",
                "periodType": "ALL",
                "isShared": True,
                "limit": limit
            }
            
            response = requests.get(url, params=params, headers=self.headers)
            print(f"API 응답: {response.text[:200]}")  # 디버깅용
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data:
                    return data['data']
            return []
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
            
            url = f"{self.base_url}/getTraderTrades"
            params = {
                "traderId": trader_id,
                "startTime": start_time,
                "endTime": end_time,
                "limit": 1000
            }
            
            response = requests.get(url, params=params, headers=self.headers)
            print(f"트레이더 {trader_id} API 응답: {response.text[:200]}")  # 디버깅용
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data:
                    return data['data']
            return []
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
            'win_rate': len(df[df['profit'] > 0]) / len(df) * 100 if len(df) > 0 else 0,
            'avg_profit': df['profit'].mean() if len(df) > 0 else 0,
            'avg_holding_time': df['holdingTime'].mean() if len(df) > 0 else 0,
            'max_profit': df['profit'].max() if len(df) > 0 else 0,
            'max_loss': df['profit'].min() if len(df) > 0 else 0,
        }
        
        # 코인별 분석
        coin_stats = df.groupby('symbol').agg({
            'profit': ['count', 'mean', 'sum'],
            'win_rate': lambda x: (x > 0).mean() * 100
        }).round(2)
        
        # 시간대별 분석
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['hour'] = df['timestamp'].dt.hour
        
        hourly_stats = df.groupby('hour').agg({
            'profit': ['mean', 'count'],
            'win_rate': lambda x: (x > 0).mean() * 100
        }).round(2)
        
        # 포지션 크기 분석
        position_sizes = df['positionSize'].value_counts()
        
        return {
            'basic_stats': stats,
            'coin_stats': coin_stats,
            'hourly_stats': hourly_stats,
            'position_sizes': position_sizes
        }
    
    def analyze_top_traders(self, limit=10):
        """상위 트레이더들의 전략 분석"""
        top_traders = self.get_top_traders(limit)
        print(f"수집된 트레이더 수: {len(top_traders)}")  # 디버깅용
        
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
    analyzer = LeaderboardAnalyzer()
    
    print("상위 트레이더 분석 시작...")
    results = analyzer.analyze_top_traders(limit=10)
    
    if not results:
        print("분석 결과가 없습니다. API 응답을 확인해주세요.")
        return
    
    # 결과 저장
    pd.DataFrame(results).to_csv('leaderboard_analysis_results.csv', index=False)
    
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
        
        print("\n코인별 통계:")
        print(result['pattern']['coin_stats'])
        
        print("\n시간대별 통계:")
        print(result['pattern']['hourly_stats'])

if __name__ == "__main__":
    main() 