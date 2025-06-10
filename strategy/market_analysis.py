import pandas as pd
import numpy as np
from binance.client import Client
from datetime import datetime, timedelta
import time
from tqdm import tqdm

class MarketAnalyzer:
    def __init__(self, api_key=None, api_secret=None):
        self.client = Client(api_key, api_secret)
        
    def get_historical_data(self, symbol='BTCUSDT', interval='1h', lookback='30d'):
        """과거 데이터 가져오기"""
        try:
            klines = self.client.get_historical_klines(
                symbol=symbol,
                interval=interval,
                start_str=lookback
            )
            
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            # 데이터 전처리
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
                
            return df
            
        except Exception as e:
            print(f"데이터 수집 중 오류 발생: {e}")
            return None
    
    def calculate_indicators(self, df):
        """기술적 지표 계산 (순수 pandas/numpy)"""
        # 이동평균선
        df['MA20'] = df['close'].rolling(window=20).mean()
        df['MA50'] = df['close'].rolling(window=50).mean()
        df['MA200'] = df['close'].rolling(window=200).mean()
        
        # RSI (순수 pandas)
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=14, min_periods=14).mean()
        avg_loss = loss.rolling(window=14, min_periods=14).mean()
        rs = avg_gain / avg_loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # MACD (순수 pandas)
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['MACDs'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACDh'] = df['MACD'] - df['MACDs']
        
        # 볼린저 밴드 (순수 pandas)
        ma20 = df['close'].rolling(window=20).mean()
        std20 = df['close'].rolling(window=20).std()
        df['BBL'] = ma20 - 2 * std20
        df['BBM'] = ma20
        df['BBU'] = ma20 + 2 * std20
        
        # ATR (순수 pandas)
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(window=14).mean()
        
        return df
    
    def analyze_market_patterns(self, df):
        """시장 패턴 분석"""
        patterns = {}
        
        # 1. 거래량 분석
        volume_mean = df['volume'].mean()
        volume_std = df['volume'].std()
        patterns['high_volume_periods'] = df[df['volume'] > volume_mean + volume_std]
        
        # 2. 가격 변동성 분석
        df['price_change'] = df['close'].pct_change()
        patterns['high_volatility_periods'] = df[abs(df['price_change']) > df['price_change'].std() * 2]
        
        # 3. 추세 분석
        df['trend'] = np.where(df['MA20'] > df['MA50'], 'up', 'down')
        patterns['trend_changes'] = df[df['trend'] != df['trend'].shift(1)]
        
        # 4. 과매수/과매도 구간
        patterns['overbought'] = df[df['RSI'] > 70]
        patterns['oversold'] = df[df['RSI'] < 30]
        
        return patterns
    
    def find_optimal_entry_points(self, df, patterns):
        """최적의 진입 포인트 찾기"""
        entry_points = []
        
        for idx, row in df.iterrows():
            score = 0
            
            # 1. 거래량 기반 점수
            if row['volume'] > df['volume'].mean() + df['volume'].std():
                score += 2
            
            # 2. RSI 기반 점수
            if row['RSI'] < 30:  # 과매도
                score += 2
            elif row['RSI'] > 70:  # 과매수
                score -= 2
            
            # 3. MACD 기반 점수
            if row['MACD'] > row['MACDs']:
                score += 1
            else:
                score -= 1
            
            # 4. 볼린저 밴드 기반 점수
            if row['close'] < row['BBL']:
                score += 2
            elif row['close'] > row['BBU']:
                score -= 2
            
            # 5. 추세 기반 점수
            if row['MA20'] > row['MA50']:
                score += 1
            else:
                score -= 1
            
            if score >= 3:  # 진입 기준점
                entry_points.append({
                    'timestamp': row['timestamp'],
                    'price': row['close'],
                    'score': score,
                    'indicators': {
                        'RSI': row['RSI'],
                        'MACD': row['MACD'],
                        'BB_position': (row['close'] - row['BBL']) / (row['BBU'] - row['BBL']) if (row['BBU'] - row['BBL']) != 0 else np.nan,
                        'volume_ratio': row['volume'] / df['volume'].mean()
                    }
                })
        
        return entry_points

def main():
    analyzer = MarketAnalyzer()
    
    print("시장 데이터 수집 중...")
    df = analyzer.get_historical_data(symbol='BTCUSDT', interval='1h', lookback='30d')
    
    if df is not None:
        print("기술적 지표 계산 중...")
        df = analyzer.calculate_indicators(df)
        
        print("시장 패턴 분석 중...")
        patterns = analyzer.analyze_market_patterns(df)
        
        print("최적 진입 포인트 찾는 중...")
        entry_points = analyzer.find_optimal_entry_points(df, patterns)
        
        # 결과 저장
        results = pd.DataFrame(entry_points)
        results.to_csv('market_analysis_results.csv', index=False)
        
        # 결과 출력
        print("\n=== 분석 결과 ===")
        print(f"총 진입 포인트: {len(entry_points)}")
        print("\n상위 5개 진입 포인트:")
        for point in sorted(entry_points, key=lambda x: x['score'], reverse=True)[:5]:
            print(f"\n시간: {point['timestamp']}")
            print(f"가격: {point['price']:.2f}")
            print(f"점수: {point['score']}")
            print(f"RSI: {point['indicators']['RSI']:.2f}")
            print(f"볼린저밴드 위치: {point['indicators']['BB_position']:.2f}")
            print(f"거래량 비율: {point['indicators']['volume_ratio']:.2f}")

if __name__ == "__main__":
    main() 