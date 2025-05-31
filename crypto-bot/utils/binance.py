from binance.client import Client
import pandas as pd
from utils.telegram import send_telegram_message

from dotenv import load_dotenv
import requests
import time
import os

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
client = Client(API_KEY, API_SECRET)




def has_open_position(symbol):
    try:
        positions = client.futures_account()['positions']

        for p in positions:
            sym = p['symbol']
            amt = float(p['positionAmt'])
            if sym == symbol.upper() and amt != 0:
                return True

        return False

    except Exception as e:
        send_telegram_message(f"💥 포지션 조회 실패: {symbol} → {e}")
        return False
        

def get_1m_klines(symbol, interval='1m', limit=120):
    try:
        # 바이낸스 API의 최대 limit 값
        MAX_LIMIT = 1000
        
        if limit <= MAX_LIMIT:
            # 한 번에 가져올 수 있는 경우
            klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        else:
            # 여러 번 나눠서 가져오기
            klines = []
            remaining = limit
            end_time = None
            
            while remaining > 0:
                current_limit = min(remaining, MAX_LIMIT)
                params = {
                    'symbol': symbol,
                    'interval': interval,
                    'limit': current_limit
                }
                
                if end_time:
                    params['endTime'] = end_time
                
                batch = client.futures_klines(**params)
                if not batch:
                    break
                    
                klines = batch + klines
                remaining -= len(batch)
                
                if len(batch) < current_limit:
                    break
                    
                end_time = batch[0][0]  # 이전 배치의 시작 시간
                time.sleep(0.1)  # API 호출 제한 방지
        
        if not klines:
            return pd.DataFrame()
            
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        
        return df
        
    except Exception as e:
        print(f"[{symbol}] {interval} 데이터 불러오기 실패: {e}")
        return pd.DataFrame()
      
# def get_top_symbols(n=20):
#     try:
#         tickers = client.futures_ticker()
#         info = client.futures_exchange_info()
#         tradable_symbols = set()
#         for s in info['symbols']:
#             if (s['contractType'] == 'PERPETUAL' and
#                 s['quoteAsset'] == 'USDT' and
#                 not s['symbol'].endswith('DOWN') and
#                 s['status'] == 'TRADING'):
#                 tradable_symbols.add(s['symbol'])
#         usdt_tickers = [t for t in tickers if t['symbol'] in tradable_symbols]
#         sorted_tickers = sorted(usdt_tickers, key=lambda x: float(x['quoteVolume']), reverse=True)
#         return [t['symbol'] for t in sorted_tickers[:n]]
#     except Exception as e:
#         print("시총 순위 불러오기 실패:", e)
#         return []
def get_top_symbols(n=20, direction="up"):
    try:
        tickers = client.futures_ticker()
        info = client.futures_exchange_info()

        tradable_symbols = set()
        for s in info['symbols']:
            if (s['contractType'] == 'PERPETUAL' and
                s['quoteAsset'] == 'USDT' and
                not s['symbol'].endswith('DOWN') and
                s['status'] == 'TRADING'):
                tradable_symbols.add(s['symbol'])

        usdt_tickers = [
            t for t in tickers
            if t['symbol'] in tradable_symbols
        ]

        sorted_tickers = sorted(
            usdt_tickers,
            key=lambda x: float(x['quoteVolume']),
            reverse=True
        )

        return [t['symbol'] for t in sorted_tickers[:n]]

    except Exception as e:
        print("거래금액 순위 가져오기 실패:", e)
        return []
    

def check_ma365_proximity_with_slope(symbol, price_thresh=0.002, slope_thresh=0.0005):
    try:
        klines = client.futures_klines(symbol=symbol, interval='1m', limit=600)
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        df['close'] = df['close'].astype(float)
        df['ma365'] = df['close'].rolling(365).mean()
        valid_df = df.dropna(subset=['ma365'])
        if len(valid_df) < 21:
            return None
        latest_ma = valid_df['ma365'].iloc[-1]
        earlier_ma = valid_df['ma365'].iloc[-21]
        latest_close = valid_df['close'].iloc[-1]
        ma_slope = (latest_ma - earlier_ma) / earlier_ma
        diff_pct = abs(latest_close - latest_ma) / latest_ma
        is_near = diff_pct <= price_thresh
        is_flat = abs(ma_slope) <= slope_thresh
        return {
            'symbol': symbol,
            'price': latest_close,
            'ma': latest_ma,
            'diff_pct': diff_pct * 100,
            'slope_pct': ma_slope * 100,
            'entry_signal': is_near and is_flat
        }
    except:
        return None

def check_15m_ma90_disparity(symbol):
    try:
        klines = client.futures_klines(symbol=symbol, interval='15m', limit=100)
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        df['close'] = df['close'].astype(float)
        df['ma90'] = df['close'].rolling(90).mean()
        df.dropna(inplace=True)
        if len(df) == 0:
            return None
        latest_close = df['close'].iloc[-1]
        latest_ma = df['ma90'].iloc[-1]
        disparity = (latest_close / latest_ma) * 100
        if disparity < 98 or disparity > 102:
            return {
                'symbol': symbol,
                'price': latest_close,
                'ma90': latest_ma,
                'disparity': disparity
            }
        return None
    except:
        return None