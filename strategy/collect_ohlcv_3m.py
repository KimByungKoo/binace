import pandas as pd
from binance.client import Client
from datetime import datetime, timedelta
import time

# 바이낸스 API 키 필요 없음(공개 데이터)
client = Client()

symbol = 'BTCUSDT'
interval = Client.KLINE_INTERVAL_3MINUTE
lookback_days = 180

end_time = datetime.now()
start_time = end_time - timedelta(days=lookback_days)

print(f"{symbol} 3분봉 {lookback_days}일치 데이터 수집 시작...")

klines = []
fetch_time = start_time

while fetch_time < end_time:
    fetch_str = fetch_time.strftime('%Y-%m-%d %H:%M:%S')
    tmp_klines = client.get_historical_klines(symbol, interval, fetch_str, limit=1000)
    if not tmp_klines:
        break
    klines.extend(tmp_klines)
    last_open_time = tmp_klines[-1][0] // 1000
    fetch_time = datetime.fromtimestamp(last_open_time) + timedelta(minutes=3)
    time.sleep(0.2)
    if fetch_time > end_time:
        break

print(f"총 {len(klines)}개 캔들 수집 완료")

columns = [
    'timestamp', 'open', 'high', 'low', 'close', 'volume',
    'close_time', 'quote_volume', 'trades', 'taker_buy_base',
    'taker_buy_quote', 'ignore'
]
df = pd.DataFrame(klines, columns=columns)
df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
for col in ['open', 'high', 'low', 'close', 'volume']:
    df[col] = df[col].astype(float)

save_path = 'ohlcv_BTCUSDT_3m_180d.csv'
df.to_csv(save_path, index=False)
print(f"저장 완료: {save_path}") 