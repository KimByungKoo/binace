import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
from btc_dominance import get_btc_dominance

class BTCDominanceStrategy:
    def __init__(self, symbol, start_time, end_time):
        self.symbol = symbol
        self.start_time = start_time
        self.end_time = end_time
        self.data = None
        self.btc_dom_data = None
        
    def fetch_data(self):
        """데이터 가져오기"""
        # 심볼 데이터 가져오기
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": self.symbol,
            "interval": "1d",
            "startTime": self.start_time,
            "endTime": self.end_time,
            "limit": 1000
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
            
        # BTC 도미넌스 데이터 가져오기
        self.btc_dom_data = get_btc_dominance(self.start_time, self.end_time)
        
        # 데이터 병합
        self.data = pd.merge(df, self.btc_dom_data, on='timestamp', how='inner')
        
        # 기술적 지표 계산
        self.calculate_indicators()
        
    def calculate_indicators(self):
        """기술적 지표 계산"""
        # RSI 계산
        delta = self.data['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        self.data['rsi'] = 100 - (100 / (1 + rs))
        
        # MACD 계산
        exp1 = self.data['close'].ewm(span=12, adjust=False).mean()
        exp2 = self.data['close'].ewm(span=26, adjust=False).mean()
        self.data['macd'] = exp1 - exp2
        self.data['signal'] = self.data['macd'].ewm(span=9, adjust=False).mean()
        
        # 이격도 계산
        ma20 = self.data['close'].rolling(window=20).mean()
        self.data['disp'] = (self.data['close'] - ma20) / ma20 * 100
        
        # BTC 도미넌스 이동평균
        self.data['btc_dom_ma20'] = self.data['btc_dominance'].rolling(window=20).mean()
        
        # 거래량 지표 계산
        self.data['volume_ma20'] = self.data['volume'].rolling(window=20).mean()
        self.data['volume_ratio'] = self.data['volume'] / self.data['volume_ma20']

    def get_symbol_specific_conditions(self, symbol):
        """심볼별 최적화된 조건 반환"""
        conditions = {
            'EOSUSDT': {
                'rsi_range': [40, 45, 50],
                'macd_range': [0, 0.5],
                'disp_range': [-1.0, -0.5],
                'btc_dom_range': [55, 60],
                'volume_ratio': 1.2,
                'stop_loss': 0.04,  # 4% 손절
                'take_profit': 0.08  # 8% 익절
            },
            'LINKUSDT': {
                'rsi_range': [30, 35, 40],
                'macd_range': [0.5],
                'disp_range': [-1.5, -1.0],
                'btc_dom_range': [50, 55],
                'volume_ratio': 1.5,
                'stop_loss': 0.03,  # 3% 손절
                'take_profit': 0.06  # 6% 익절
            },
            'TRBUSDT': {
                'rsi_range': [35, 40],
                'macd_range': [0],
                'disp_range': [-1.0, -0.5],
                'btc_dom_range': [60, 65],
                'volume_ratio': 1.3,
                'stop_loss': 0.05,  # 5% 손절
                'take_profit': 0.10  # 10% 익절
            }
        }
        return conditions.get(symbol, {
            'rsi_range': [35, 40, 45, 50],
            'macd_range': [0, 0.5],
            'disp_range': [-1.5, -1.0, -0.5],
            'btc_dom_range': [50, 55, 60, 65],
            'volume_ratio': 1.2,
            'stop_loss': 0.04,
            'take_profit': 0.08
        })

    def backtest(self, rsi_threshold, macd_threshold, disp_threshold, btc_dom_threshold, volume_ratio=1.2, stop_loss=0.04, take_profit=0.08):
        """
        백테스트 실행
        
        Args:
            rsi_threshold (float): RSI 진입 기준
            macd_threshold (float): MACD 진입 기준
            disp_threshold (float): 이격도 진입 기준
            btc_dom_threshold (float): BTC 도미넌스 진입 기준
            volume_ratio (float): 거래량 비율 기준
            stop_loss (float): 손절 비율
            take_profit (float): 익절 비율
        """
        if self.data is None:
            self.fetch_data()
            
        trades = []
        position = None
        entry_price = None
        
        for i in range(1, len(self.data)):
            current = self.data.iloc[i]
            prev = self.data.iloc[i-1]
            
            # 진입 조건 (일부 조건만 만족해도 진입)
            if position is None:
                conditions_met = 0
                if current['rsi'] < rsi_threshold:
                    conditions_met += 1
                if current['macd'] > macd_threshold:
                    conditions_met += 1
                if current['disp'] < disp_threshold:
                    conditions_met += 1
                if current['btc_dominance'] < btc_dom_threshold:
                    conditions_met += 1
                if current['volume_ratio'] > volume_ratio:
                    conditions_met += 1
                
                # 2개 이상의 조건이 만족되면 진입
                if conditions_met >= 2:
                    position = 'long'
                    entry_price = current['close']
                    entry_date = current['timestamp']
            
            # 청산 조건
            elif position == 'long':
                # 손절 조건
                if current['close'] < entry_price * (1 - stop_loss):
                    trades.append({
                        'entry_date': entry_date,
                        'exit_date': current['timestamp'],
                        'entry_price': entry_price,
                        'exit_price': current['close'],
                        'return': (current['close'] - entry_price) / entry_price * 100
                    })
                    position = None
                    entry_price = None
                
                # 익절 조건
                elif current['close'] > entry_price * (1 + take_profit):
                    trades.append({
                        'entry_date': entry_date,
                        'exit_date': current['timestamp'],
                        'entry_price': entry_price,
                        'exit_price': current['close'],
                        'return': (current['close'] - entry_price) / entry_price * 100
                    })
                    position = None
                    entry_price = None
        
        return pd.DataFrame(trades)

def run_btc_dominance_analysis():
    """BTC 도미넌스 전략 분석 실행"""
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - (180 * 24 * 60 * 60 * 1000)  # 180일 전
    
    symbols = [
        "TRBUSDT", "LPTUSDT", "WIFUSDT", "ENAusdt", "AAVEUSDT",
        "NEIROUSDT", "AVAXUSDT", "SUIUSDT", "TRUMPUSDT", "LAUSDT",
        "FARTCOINUSDT", "ADAUSDT", "BNBUSDT", "ETHUSDT", "XRPUSDT",
        "DOGEUSDT", "SOLUSDT", "DOTUSDT", "MATICUSDT", "LINKUSDT",
        "UNIUSDT", "ATOMUSDT", "LTCUSDT", "XLMUSDT", "VETUSDT",
        "FILUSDT", "THETAUSDT", "XTZUSDT", "EOSUSDT", "AAVEUSDT"
    ]
    
    results = []
    
    for symbol in symbols:
        strategy = BTCDominanceStrategy(symbol, start_time, end_time)
        conditions = strategy.get_symbol_specific_conditions(symbol)
        
        # 심볼별 최적화된 조건으로 테스트
        for rsi in conditions['rsi_range']:
            for macd in conditions['macd_range']:
                for disp in conditions['disp_range']:
                    for btc_dom in conditions['btc_dom_range']:
                        trades_df = strategy.backtest(
                            rsi, macd, disp, btc_dom,
                            conditions['volume_ratio'],
                            conditions['stop_loss'],
                            conditions['take_profit']
                        )
                        
                        if len(trades_df) > 0:
                            win_rate = len(trades_df[trades_df['return'] > 0]) / len(trades_df) * 100
                            avg_return = trades_df['return'].mean()
                            
                            results.append({
                                'symbol': symbol,
                                'rsi_threshold': rsi,
                                'macd_threshold': macd,
                                'disp_threshold': disp,
                                'btc_dom_threshold': btc_dom,
                                'volume_ratio': conditions['volume_ratio'],
                                'stop_loss': conditions['stop_loss'],
                                'take_profit': conditions['take_profit'],
                                'trades': len(trades_df),
                                'win_rate': win_rate,
                                'avg_return': avg_return
                            })
    
    results_df = pd.DataFrame(results)
    results_df.to_csv('btc_dominance_results.csv', index=False)
    return results_df

if __name__ == "__main__":
    results = run_btc_dominance_analysis()
    if results.empty or 'win_rate' not in results.columns:
        print('거래가 발생하지 않아 결과가 없습니다.')
    else:
        print(results.sort_values('win_rate', ascending=False).head(10)) 