import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import ccxt
import time
import os
from dotenv import load_dotenv
import pandas_ta as ta
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm
import warnings
from itertools import product
warnings.filterwarnings('ignore')

# 환경 변수 로드
load_dotenv()

# API 키 설정
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')

# Binance 클라이언트 초기화
exchange = ccxt.binance({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True
})

def fetch_ohlcv_all(symbol, timeframe, since, until):
    """여러 번 나눠서 OHLCV 데이터 받아오기"""
    all_ohlcv = []
    since_ms = int(since.timestamp() * 1000)
    until_ms = int(until.timestamp() * 1000)
    pbar = tqdm(total=(until_ms-since_ms)//(60*1000))
    while since_ms < until_ms:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
            if not ohlcv:
                break
            all_ohlcv += ohlcv
            last_time = ohlcv[-1][0]
            since_ms = last_time + 60*1000  # 1분봉 기준
            pbar.update(len(ohlcv))
            if len(ohlcv) < 1000:
                break
            time.sleep(exchange.rateLimit / 1000)
        except Exception as e:
            print(f"Error fetching data: {e}")
            time.sleep(3)
    pbar.close()
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def get_or_load_ohlcv(symbol, timeframe, days, filename):
    if os.path.exists(filename):
        print(f"[데이터 로드] {filename}에서 데이터 불러오는 중...")
        df = pd.read_csv(filename, parse_dates=['timestamp'])
    else:
        print(f"[데이터 다운로드] {days}일치 {timeframe} 데이터 다운로드 중...")
        until = datetime.utcnow()
        since = until - timedelta(days=days)
        df = fetch_ohlcv_all(symbol, timeframe, since, until)
        df.to_csv(filename, index=False)
        print(f"[저장 완료] {filename}")
    return df

def load_data(file_path):
    """데이터 로드 및 전처리"""
    print(f"\n[데이터 로드] {file_path}에서 데이터 불러오는 중...")
    df = pd.read_csv(file_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

def calculate_indicators(df, params):
    """기술적 지표 계산"""
    # 이동평균선
    df['ma_short'] = df['close'].rolling(window=params['ma_short']).mean()
    df['ma_long'] = df['close'].rolling(window=params['ma_long']).mean()
    df['ema_short'] = df['close'].ewm(span=params['ma_short']).mean()
    df['ema_long'] = df['close'].ewm(span=params['ma_long']).mean()
    
    # RSI
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    # MACD
    macd = ta.macd(df['close'])
    df['macd'] = macd['MACD_12_26_9']
    df['macd_signal'] = macd['MACDs_12_26_9']
    df['macd_hist'] = macd['MACDh_12_26_9']
    
    # 스토캐스틱
    stoch = ta.stoch(df['high'], df['low'], df['close'])
    df['stoch_k'] = stoch['STOCHk_14_3_3']
    df['stoch_d'] = stoch['STOCHd_14_3_3']
    
    # 볼린저 밴드
    bb = ta.bbands(df['close'], length=20, std=params['bb_std'])
    df['bb_upper'] = bb['BBU_20_'+str(params['bb_std'])]
    df['bb_middle'] = bb['BBM_20_'+str(params['bb_std'])]
    df['bb_lower'] = bb['BBL_20_'+str(params['bb_std'])]
    
    # ATR
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    
    return df

def backtest_strategy(df, params):
    """전략 백테스트"""
    balance = 3000
    position = None
    entry_price = None
    entry_time = None
    trades = []
    partial_exit = False
    
    for i in range(max(params['ma_long'], 20, 14), len(df)):
        current_price = df['close'].iloc[i]
        current_time = df['timestamp'].iloc[i]
        
        # 숏 진입 조건
        if position is None:
            # 1. 이동평균선 역배열 (단기 < 장기)
            ma_aligned = df['ma_short'].iloc[i] < df['ma_long'].iloc[i]
            
            # 2. EMA 크로스오버 (데드크로스)
            ema_cross = (df['ema_short'].iloc[i] < df['ema_long'].iloc[i] and 
                        df['ema_short'].iloc[i-1] >= df['ema_long'].iloc[i-1])
            
            # 3. RSI 과매수 구간
            rsi_overbought = df['rsi'].iloc[i] > (100 - params['rsi_entry'])
            
            # 4. MACD 데드크로스
            macd_cross = (df['macd'].iloc[i] < df['macd_signal'].iloc[i] and 
                         df['macd'].iloc[i-1] >= df['macd_signal'].iloc[i-1])
            
            # 5. MACD 히스토그램 감소
            macd_hist_decrease = df['macd_hist'].iloc[i] < df['macd_hist'].iloc[i-1]
            
            # 6. 스토캐스틱 과매수
            stoch_overbought = df['stoch_k'].iloc[i] > 70
            
            # 7. 현재가가 볼린저 밴드 상단 근처
            price_near_bb_upper = (current_price >= df['bb_upper'].iloc[i] * 0.97 and 
                                 current_price <= df['bb_upper'].iloc[i] * 1.03)
            
            # 8. ATR 기준 변동성 체크
            volatility_ok = df['atr'].iloc[i] > df['atr'].iloc[i-20:i].mean()
            
            # 진입 조건 (일부만 만족해도 진입)
            if ((ma_aligned or ema_cross) and rsi_overbought) or \
               (macd_cross and macd_hist_decrease and stoch_overbought) or \
               (price_near_bb_upper and volatility_ok):
                position = 'short'
                entry_price = current_price * 0.999  # 슬리피지 적용
                entry_time = current_time
                trades.append({
                    'entry_time': current_time,
                    'entry_price': entry_price,
                    'type': 'short'
                })
        
        # 포지션 청산
        elif position == 'short':
            exit_price = current_price * 1.001  # 슬리피지 적용
            profit_pct = (entry_price - exit_price) / entry_price * 100  # 숏 포지션 수익률 계산
            
            # 손절 체크 (-0.8%)
            if profit_pct <= -0.8:
                balance *= (1 + profit_pct/100)
                position = None
                entry_price = None
                entry_time = None
                partial_exit = False
                trades[-1].update({
                    'exit_time': current_time,
                    'exit_price': exit_price,
                    'profit_pct': profit_pct,
                    'exit_type': 'stop_loss'
                })
            
            # 익절 체크 (+1.2%)
            elif not partial_exit and profit_pct >= 1.2:
                balance *= (1 + profit_pct/200)  # 50% 청산
                partial_exit = True
                entry_price = current_price
                entry_time = current_time
                trades[-1].update({
                    'partial_exit_time': current_time,
                    'partial_exit_price': exit_price,
                    'partial_profit_pct': profit_pct/2
                })
            
            # RSI 과매도 구간에서 청산
            elif partial_exit and df['rsi'].iloc[i] < 25:
                balance *= (1 + profit_pct/100)
                position = None
                entry_price = None
                entry_time = None
                partial_exit = False
                trades[-1].update({
                    'exit_time': current_time,
                    'exit_price': exit_price,
                    'profit_pct': profit_pct,
                    'exit_type': 'rsi_exit'
                })
    
    # 마지막 포지션 청산
    if position is not None:
        exit_price = df['close'].iloc[-1] * 1.001
        profit_pct = (entry_price - exit_price) / entry_price * 100
        balance *= (1 + profit_pct/100)
        trades[-1].update({
            'exit_time': df['timestamp'].iloc[-1],
            'exit_price': exit_price,
            'profit_pct': profit_pct,
            'exit_type': 'time_exit'
        })
    
    # 결과 계산
    n_trades = len(trades)
    win_trades = [t for t in trades if t.get('profit_pct', 0) > 0]
    win_rate = len(win_trades) / n_trades * 100 if n_trades else 0
    avg_return = np.mean([t.get('profit_pct', 0) for t in trades]) if trades else 0
    
    return {
        'ma_short': params['ma_short'],
        'ma_long': params['ma_long'],
        'rsi_entry': params['rsi_entry'],
        'bb_std': params['bb_std'],
        'trades': n_trades,
        'win_rate': win_rate,
        'avg_return': avg_return,
        'final_balance': balance
    }

def main():
    # 데이터 로드
    df = load_data('ohlcv_BTCUSDT_1m_180d.csv')
    
    # 최적화할 파라미터 범위
    ma_short_list = [7, 20, 50]
    ma_long_list = [50, 90, 200]
    rsi_entry_list = [40, 50, 60]  # RSI 조건 더 완화
    bb_std_list = [2.0, 2.5, 3.0]  # 볼린저밴드 폭 증가
    
    results = []
    
    # 모든 조합에 대해 백테스트 실행
    for ma_short, ma_long, rsi_entry, bb_std in tqdm(product(ma_short_list, ma_long_list, rsi_entry_list, bb_std_list)):
        if ma_short >= ma_long:
            continue
        
        params = {
            'ma_short': ma_short,
            'ma_long': ma_long,
            'rsi_entry': rsi_entry,
            'bb_std': bb_std
        }
        
        # 지표 계산
        temp_df = calculate_indicators(df.copy(), params)
        
        # 백테스트 실행
        result = backtest_strategy(temp_df, params)
        results.append(result)
    
    # 결과 DataFrame으로 저장 및 최적 조합 출력
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values(by='final_balance', ascending=False)
    results_df.to_csv('grid_search_results.csv', index=False)
    
    print('\n=== 최고 수익 조합 상위 5개 ===')
    print(results_df.head().to_string())
    
    # 상세 분석
    best_result = results_df.iloc[0]
    print(f'\n=== 최적 조합 상세 분석 ===')
    print(f'MA 단기: {best_result["ma_short"]}')
    print(f'MA 장기: {best_result["ma_long"]}')
    print(f'RSI 진입: {best_result["rsi_entry"]}')
    print(f'볼린저밴드 폭: {best_result["bb_std"]}')
    print(f'거래 횟수: {best_result["trades"]}')
    print(f'승률: {best_result["win_rate"]:.2f}%')
    print(f'평균 수익률: {best_result["avg_return"]:.2f}%')
    print(f'최종 잔고: {best_result["final_balance"]:.2f}')

if __name__ == "__main__":
    main() 