import pandas as pd
import requests
from datetime import datetime, timedelta

def get_btc_dominance(start_time, end_time):
    """
    BTC 도미넌스 데이터를 가져오는 함수
    
    Args:
        start_time (int): 시작 시간 (밀리초)
        end_time (int): 종료 시간 (밀리초)
    
    Returns:
        pd.DataFrame: BTC 도미넌스 데이터
    """
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": "BTCUSDT",
        "interval": "1d",
        "startTime": start_time,
        "endTime": end_time,
        "limit": 1000
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    # BTC 가격 데이터
    btc_df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])
    btc_df['timestamp'] = pd.to_datetime(btc_df['timestamp'], unit='ms')
    btc_df['close'] = btc_df['close'].astype(float)
    
    # 전체 시가총액 데이터 (Binance API에서 제공하지 않으므로 추정값 사용)
    total_market_cap = btc_df['close'] * 1000000  # 예시로 BTC 시가총액의 100만배로 가정
    
    # BTC 도미넌스 계산
    btc_dominance = (btc_df['close'] * 1000000) / total_market_cap * 100
    
    result_df = pd.DataFrame({
        'timestamp': btc_df['timestamp'],
        'btc_dominance': btc_dominance
    })
    
    return result_df

def analyze_btc_dominance(symbol, start_time, end_time):
    """
    BTC 도미넌스와 특정 심볼의 가격 데이터를 분석하는 함수
    
    Args:
        symbol (str): 분석할 심볼
        start_time (int): 시작 시간 (밀리초)
        end_time (int): 종료 시간 (밀리초)
    
    Returns:
        pd.DataFrame: 분석 결과
    """
    # BTC 도미넌스 데이터 가져오기
    btc_dom_df = get_btc_dominance(start_time, end_time)
    
    # 심볼 가격 데이터 가져오기
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": "1d",
        "startTime": start_time,
        "endTime": end_time,
        "limit": 1000
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    symbol_df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])
    symbol_df['timestamp'] = pd.to_datetime(symbol_df['timestamp'], unit='ms')
    symbol_df['close'] = symbol_df['close'].astype(float)
    
    # 데이터 병합
    merged_df = pd.merge(btc_dom_df, symbol_df[['timestamp', 'close']], on='timestamp', how='inner')
    merged_df.columns = ['timestamp', 'btc_dominance', 'symbol_price']
    
    return merged_df

if __name__ == "__main__":
    # 테스트 실행
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - (180 * 24 * 60 * 60 * 1000)  # 180일 전
    
    # TRBUSDT에 대해 테스트
    result_df = analyze_btc_dominance("TRBUSDT", start_time, end_time)
    print(result_df.head()) 