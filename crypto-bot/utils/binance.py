from binance.client import Client
import pandas as pd
from utils.telegram import send_telegram_message

from dotenv import load_dotenv
import requests
import time
import os

load_dotenv()




API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
client = Client(API_KEY, API_SECRET)


def has_open_position(symbol):
    send_telegram_message(f"[{symbol}] position")
    positions = client.futures_account()['positions']
    positions = client.futures_account()['positions']
    send_telegram_message(f"🔍 포지션 수: {len(positions)}")

    for p in positions:
        send_telegram_message(f"[{p['symbol']}] position")
        send_telegram_message(f"[{float(p['positionAmt'])}] position")
        if p['symbol'] == symbol.upper() and float(p['positionAmt']) != 0:
            return True
    return False

def get_1m_klines(symbol, interval='1m', limit=120):
    try:
        klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        #df['close'] = df['close'].astype(float)
        #df['volume'] = df['volume'].astype(float)
        
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        print(f"[{symbol}] 1분봉 데이터 불러오기 실패: {e}")
        return pd.DataFrame()
      
def get_top_symbols(n=20):
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
        usdt_tickers = [t for t in tickers if t['symbol'] in tradable_symbols]
        sorted_tickers = sorted(usdt_tickers, key=lambda x: float(x['quoteVolume']), reverse=True)
        return [t['symbol'] for t in sorted_tickers[:n]]
    except Exception as e:
        print("시총 순위 불러오기 실패:", e)
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