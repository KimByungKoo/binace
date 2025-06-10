import pandas as pd
import requests
from datetime import datetime, timedelta

def fetch_ohlcv_data(symbol, days=180):
    """
    각 심볼별로 180일치 OHLCV 데이터를 가져옵니다.
    """
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    
    # Binance API를 통해 데이터 가져오기
    url = f"https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": "1d",
        "startTime": int(start_time.timestamp() * 1000),
        "endTime": int(end_time.timestamp() * 1000),
        "limit": 1000
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    # 데이터프레임으로 변환
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    
    # 필요한 컬럼만 선택
    df = df[['open', 'high', 'low', 'close', 'volume']]
    df = df.astype(float)
    
    return df

# 예시: BTCUSDT 데이터 가져오기
symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "MASKUSDT", "1000PEPEUSDT", "DOGEUSDT", "XRPUSDT", "SUIUSDT", "TRUMPUSDT", "LAUSDT", "FARTCOINUSDT", "ADAUSDT", "HUMAUSDT", "BNBUSDT", "VIRTUALUSDT", "LPTUSDT", "WIFUSDT", "RVNUSDT", "COMPUSDT", "WCTUSDT", "ENAUSDT", "ANIMEUSDT", "AAVEUSDT", "TRBUSDT", "LINKUSDT", "UMAUSDT", "AVAXUSDT", "NEIROUSDT", "HYPEUSDT", "MOODENGUSDT"]

for symbol in symbols:
    df = fetch_ohlcv_data(symbol)
    print(f"{symbol} 데이터 수집 완료: {len(df)} 행") 