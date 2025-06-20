import websocket
import json
import threading
import time
from collections import deque
from get_top_coins import get_top_coins
from rsi_utils import calculate_rsi_binance
from telegram_bot import TelegramBot
from datetime import datetime
import requests

class RSIMonitor:
    def __init__(self):
        self.price_data = {}  # 각 심볼별 가격 데이터 저장
        self.rsi_overbought =90  # 과매수 RSI 임계값
        self.rsi_oversold = 10  # 과매도 RSI 임계값
        self.rsi_warning_high = 85  # 주의 RSI 상단 임계값
        self.rsi_warning_low =15   # 주의 RSI 하단 임계값
        self.data_length = 100  # RSI 계산을 위한 데이터 길이
        self.telegram_bot = TelegramBot(self)  # RSI 모니터 인스턴스 전달
        self.alerted_overbought_14 = set()  # RSI(14) 과매수 알림을 보낸 심볼 추적
        self.alerted_oversold_14 = set()  # RSI(14) 과매도 알림을 보낸 심볼 추적
        self.alerted_overbought_7 = set()  # RSI(7) 과매수 알림을 보낸 심볼 추적
        self.alerted_oversold_7 = set()  # RSI(7) 과매도 알림을 보낸 심볼 추적
        self.alerted_warning_high_14 = set()  # RSI(14) 주의 상단 알림을 보낸 심볼 추적
        self.alerted_warning_low_14 = set()   # RSI(14) 주의 하단 알림을 보낸 심볼 추적
        self.alerted_warning_high_7 = set()   # RSI(7) 주의 상단 알림을 보낸 심볼 추적
        self.alerted_warning_low_7 = set()    # RSI(7) 주의 하단 알림을 보낸 심볼 추적
        self.current_rsi_14 = {}  # 현재 RSI(14) 값 저장
        self.current_rsi_7 = {}  # 현재 RSI(7) 값 저장
        self.start_times = {}  # 각 심볼별 데이터 수집 시작 시간
        self.price_data_1m = {}  # 1분봉 가격 데이터
        self.price_data_15m = {} # 15분봉 가격 데이터
        self.current_rsi_14_1m = {}
        self.current_rsi_7_1m = {}
        self.current_rsi_14_15m = {}
        self.current_rsi_7_15m = {}
        self.alerted_strong_14 = set()  # 1m, 15m 동시 만족 강한 알림
        self.alerted_strong_7 = set()

    def get_historical_data(self, symbol, interval='1m', limit=100):
        """
        Binance API를 통해 과거 데이터를 가져옵니다.
        """
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                prices = [float(candle[4]) for candle in data]
                return prices
            else:
                print(f"Error fetching historical data for {symbol}: {response.text}")
                return []
        except Exception as e:
            print(f"Error fetching historical data for {symbol}: {e}")
            return []

    def initialize_symbol_data(self, symbol):
        """
        심볼의 초기 데이터를 설정합니다.
        """
        print(f"\n{symbol} 초기 데이터 로드 시작...")
        prices_1m = self.get_historical_data(symbol, interval='1m', limit=self.data_length)
        prices_15m = self.get_historical_data(symbol, interval='15m', limit=self.data_length)
        self.price_data_1m[symbol] = deque(prices_1m, maxlen=self.data_length)
        self.price_data_15m[symbol] = deque(prices_15m, maxlen=self.data_length)
        if len(prices_1m) >= self.data_length:
            rsi_14_1m = calculate_rsi_binance(list(prices_1m), period=14)
            rsi_7_1m = calculate_rsi_binance(list(prices_1m), period=7)
            self.current_rsi_14_1m[symbol] = rsi_14_1m
            self.current_rsi_7_1m[symbol] = rsi_7_1m
        if len(prices_15m) >= self.data_length:
            rsi_14_15m = calculate_rsi_binance(list(prices_15m), period=14)
            rsi_7_15m = calculate_rsi_binance(list(prices_15m), period=7)
            self.current_rsi_14_15m[symbol] = rsi_14_15m
            self.current_rsi_7_15m[symbol] = rsi_7_15m
        if len(prices_1m) >= self.data_length:
            rsi_14 = calculate_rsi_binance(list(prices_1m), period=14)
            rsi_7 = calculate_rsi_binance(list(prices_1m), period=7)
            self.current_rsi_14[symbol] = rsi_14
            self.current_rsi_7[symbol] = rsi_7
            print(f"{symbol} 초기 RSI 계산 완료:")
            print(f"RSI(14): {rsi_14:.2f}")
            print(f"RSI(7): {rsi_7:.2f}")
        else:
            print(f"{symbol} 초기 데이터 부족: {len(prices_1m)}개")
        self.price_data[symbol] = deque(prices_1m, maxlen=self.data_length)
        
    def get_current_rsi(self):
        """
        현재 모든 심볼의 1분봉/15분봉 RSI 값을 반환합니다.
        """
        print("\n=== 현재 RSI 상태 ===")
        result = {}
        for symbol in set(list(self.current_rsi_14_1m.keys()) + list(self.current_rsi_14_15m.keys())):
            result[symbol] = {
                '1m': {
                    'rsi14': self.current_rsi_14_1m.get(symbol),
                    'rsi7': self.current_rsi_7_1m.get(symbol)
                },
                '15m': {
                    'rsi14': self.current_rsi_14_15m.get(symbol),
                    'rsi7': self.current_rsi_7_15m.get(symbol)
                }
            }
            print(f"{symbol}:")
            print(f"  1분봉 RSI(14) = {result[symbol]['1m']['rsi14']}")
            print(f"  1분봉 RSI(7) = {result[symbol]['1m']['rsi7']}")
            print(f"  15분봉 RSI(14) = {result[symbol]['15m']['rsi14']}")
            print(f"  15분봉 RSI(7) = {result[symbol]['15m']['rsi7']}")
        print("===================\n")
        return result
        
    def on_message(self, ws, message):
        """
        웹소켓 메시지 처리
        """
        try:
            data = json.loads(message)
            stream_data = data.get('data', {})
            symbol = stream_data.get('s', '')
            kline = stream_data.get('k', {})
            interval = kline.get('i', '1m')
            price = float(kline.get('c', 0))
            is_closed = kline.get('x', False)
            if not symbol or price == 0:
                return
            if symbol not in self.price_data_1m or symbol not in self.price_data_15m:
                self.initialize_symbol_data(symbol)
            # 1분봉
            if interval == '1m' and is_closed:
                self.price_data_1m[symbol].append(price)
                if len(self.price_data_1m[symbol]) >= self.data_length:
                    prices = list(self.price_data_1m[symbol])
                    rsi_14 = calculate_rsi_binance(prices, period=14)
                    rsi_7 = calculate_rsi_binance(prices, period=7)
                    self.current_rsi_14_1m[symbol] = rsi_14
                    self.current_rsi_7_1m[symbol] = rsi_7
            # 15분봉
            if interval == '15m' and is_closed:
                self.price_data_15m[symbol].append(price)
                if len(self.price_data_15m[symbol]) >= self.data_length:
                    prices = list(self.price_data_15m[symbol])
                    rsi_14 = calculate_rsi_binance(prices, period=14)
                    rsi_7 = calculate_rsi_binance(prices, period=7)
                    self.current_rsi_14_15m[symbol] = rsi_14
                    self.current_rsi_7_15m[symbol] = rsi_7
            # --- 항상 dict에서 값을 꺼내서 지역변수로 사용 ---
            rsi_14_1m = self.current_rsi_14_1m.get(symbol)
            rsi_7_1m = self.current_rsi_7_1m.get(symbol)
            rsi_14_15m = self.current_rsi_14_15m.get(symbol)
            rsi_7_15m = self.current_rsi_7_15m.get(symbol)
            
            # 15분봉 알림 로직 (15분봉이 업데이트된 경우에만)
            if interval == '15m' and is_closed and rsi_14_15m is not None and rsi_7_15m is not None:
                # 15분봉 RSI(14) 과매수/과매도 알림
                if rsi_14_15m >= self.rsi_overbought and symbol not in self.alerted_overbought_14:
                    message = f"🔥 <b>15분봉 RSI(14) 과매수 - {symbol}</b>\n\n" \
                              f"1분봉 RSI(14): {rsi_14_1m if rsi_14_1m is not None else '-'}\n" \
                              f"1분봉 RSI(7): {rsi_7_1m if rsi_7_1m is not None else '-'}\n" \
                              f"15분봉 RSI(14): {rsi_14_15m:.2f}\n" \
                              f"15분봉 RSI(7): {rsi_7_15m:.2f}\n" \
                              f"현재 가격: {price:.8f} USDT"
                    self.telegram_bot.send_message(message)
                    self.alerted_overbought_14.add(symbol)
                    print(f"15분봉 RSI(14) 과매수 알림 전송: {symbol} - RSI(14): {rsi_14_15m:.2f}")
                
                elif rsi_14_15m <= self.rsi_oversold and symbol not in self.alerted_oversold_14:
                    message = f"🔥 <b>15분봉 RSI(14) 과매도 - {symbol}</b>\n\n" \
                              f"1분봉 RSI(14): {rsi_14_1m if rsi_14_1m is not None else '-'}\n" \
                              f"1분봉 RSI(7): {rsi_7_1m if rsi_7_1m is not None else '-'}\n" \
                              f"15분봉 RSI(14): {rsi_14_15m:.2f}\n" \
                              f"15분봉 RSI(7): {rsi_7_15m:.2f}\n" \
                              f"현재 가격: {price:.8f} USDT"
                    self.telegram_bot.send_message(message)
                    self.alerted_oversold_14.add(symbol)
                    print(f"15분봉 RSI(14) 과매도 알림 전송: {symbol} - RSI(14): {rsi_14_15m:.2f}")
                
                # 15분봉 RSI(7) 과매수/과매도 알림
                if rsi_7_15m >= self.rsi_overbought and symbol not in self.alerted_overbought_7:
                    message = f"🔥 <b>15분봉 RSI(7) 과매수 - {symbol}</b>\n\n" \
                              f"1분봉 RSI(14): {rsi_14_1m if rsi_14_1m is not None else '-'}\n" \
                              f"1분봉 RSI(7): {rsi_7_1m if rsi_7_1m is not None else '-'}\n" \
                              f"15분봉 RSI(14): {rsi_14_15m:.2f}\n" \
                              f"15분봉 RSI(7): {rsi_7_15m:.2f}\n" \
                              f"현재 가격: {price:.8f} USDT"
                    self.telegram_bot.send_message(message)
                    self.alerted_overbought_7.add(symbol)
                    print(f"15분봉 RSI(7) 과매수 알림 전송: {symbol} - RSI(7): {rsi_7_15m:.2f}")
                
                elif rsi_7_15m <= self.rsi_oversold and symbol not in self.alerted_oversold_7:
                    message = f"🔥 <b>15분봉 RSI(7) 과매도 - {symbol}</b>\n\n" \
                              f"1분봉 RSI(14): {rsi_14_1m if rsi_14_1m is not None else '-'}\n" \
                              f"1분봉 RSI(7): {rsi_7_1m if rsi_7_1m is not None else '-'}\n" \
                              f"15분봉 RSI(14): {rsi_14_15m:.2f}\n" \
                              f"15분봉 RSI(7): {rsi_7_15m:.2f}\n" \
                              f"현재 가격: {price:.8f} USDT"
                    self.telegram_bot.send_message(message)
                    self.alerted_oversold_7.add(symbol)
                    print(f"15분봉 RSI(7) 과매도 알림 전송: {symbol} - RSI(7): {rsi_7_15m:.2f}")
                
                # 15분봉 RSI(14) 주의 알림
                if rsi_14_15m >= self.rsi_warning_high and symbol not in self.alerted_warning_high_14:
                    message = f"⚠️ <b>15분봉 RSI(14) 주의 상단 - {symbol}</b>\n\n" \
                             f"1분봉 RSI(14): {rsi_14_1m if rsi_14_1m is not None else '-'}\n" \
                             f"1분봉 RSI(7): {rsi_7_1m if rsi_7_1m is not None else '-'}\n" \
                             f"15분봉 RSI(14): {rsi_14_15m:.2f}\n" \
                             f"15분봉 RSI(7): {rsi_7_15m:.2f}\n" \
                             f"현재 가격: {price:.8f} USDT"
                    self.telegram_bot.send_message(message)
                    self.alerted_warning_high_14.add(symbol)
                    print(f"15분봉 RSI(14) 주의 상단 알림 전송: {symbol} - RSI(14): {rsi_14_15m:.2f}")
                
                elif rsi_14_15m <= self.rsi_warning_low and symbol not in self.alerted_warning_low_14:
                    message = f"⚠️ <b>15분봉 RSI(14) 주의 하단 - {symbol}</b>\n\n" \
                             f"1분봉 RSI(14): {rsi_14_1m if rsi_14_1m is not None else '-'}\n" \
                             f"1분봉 RSI(7): {rsi_7_1m if rsi_7_1m is not None else '-'}\n" \
                             f"15분봉 RSI(14): {rsi_14_15m:.2f}\n" \
                             f"15분봉 RSI(7): {rsi_7_15m:.2f}\n" \
                             f"현재 가격: {price:.8f} USDT"
                    self.telegram_bot.send_message(message)
                    self.alerted_warning_low_14.add(symbol)
                    print(f"15분봉 RSI(14) 주의 하단 알림 전송: {symbol} - RSI(14): {rsi_14_15m:.2f}")
                
                # 15분봉 RSI(7) 주의 알림
                if rsi_7_15m >= self.rsi_warning_high and symbol not in self.alerted_warning_high_7:
                    message = f"⚠️ <b>15분봉 RSI(7) 주의 상단 - {symbol}</b>\n\n" \
                             f"1분봉 RSI(14): {rsi_14_1m if rsi_14_1m is not None else '-'}\n" \
                             f"1분봉 RSI(7): {rsi_7_1m if rsi_7_1m is not None else '-'}\n" \
                             f"15분봉 RSI(14): {rsi_14_15m:.2f}\n" \
                             f"15분봉 RSI(7): {rsi_7_15m:.2f}\n" \
                             f"현재 가격: {price:.8f} USDT"
                    self.telegram_bot.send_message(message)
                    self.alerted_warning_high_7.add(symbol)
                    print(f"15분봉 RSI(7) 주의 상단 알림 전송: {symbol} - RSI(7): {rsi_7_15m:.2f}")
                
                elif rsi_7_15m <= self.rsi_warning_low and symbol not in self.alerted_warning_low_7:
                    message = f"⚠️ <b>15분봉 RSI(7) 주의 하단 - {symbol}</b>\n\n" \
                             f"1분봉 RSI(14): {rsi_14_1m if rsi_14_1m is not None else '-'}\n" \
                             f"1분봉 RSI(7): {rsi_7_1m if rsi_7_1m is not None else '-'}\n" \
                             f"15분봉 RSI(14): {rsi_14_15m:.2f}\n" \
                             f"15분봉 RSI(7): {rsi_7_15m:.2f}\n" \
                             f"현재 가격: {price:.8f} USDT"
                    self.telegram_bot.send_message(message)
                    self.alerted_warning_low_7.add(symbol)
                    print(f"15분봉 RSI(7) 주의 하단 알림 전송: {symbol} - RSI(7): {rsi_7_15m:.2f}")
                
                # 15분봉 조건 해제시 알림 초기화
                if rsi_14_15m < self.rsi_overbought and symbol in self.alerted_overbought_14:
                    self.alerted_overbought_14.remove(symbol)
                    print(f"15분봉 RSI(14) 과매수 알림 초기화: {symbol}")
                if rsi_14_15m > self.rsi_oversold and symbol in self.alerted_oversold_14:
                    self.alerted_oversold_14.remove(symbol)
                    print(f"15분봉 RSI(14) 과매도 알림 초기화: {symbol}")
                if rsi_7_15m < self.rsi_overbought and symbol in self.alerted_overbought_7:
                    self.alerted_overbought_7.remove(symbol)
                    print(f"15분봉 RSI(7) 과매수 알림 초기화: {symbol}")
                if rsi_7_15m > self.rsi_oversold and symbol in self.alerted_oversold_7:
                    self.alerted_oversold_7.remove(symbol)
                    print(f"15분봉 RSI(7) 과매도 알림 초기화: {symbol}")
                if rsi_14_15m < self.rsi_warning_high and symbol in self.alerted_warning_high_14:
                    self.alerted_warning_high_14.remove(symbol)
                    print(f"15분봉 RSI(14) 주의 상단 알림 초기화: {symbol}")
                if rsi_14_15m > self.rsi_warning_low and symbol in self.alerted_warning_low_14:
                    self.alerted_warning_low_14.remove(symbol)
                    print(f"15분봉 RSI(14) 주의 하단 알림 초기화: {symbol}")
                if rsi_7_15m < self.rsi_warning_high and symbol in self.alerted_warning_high_7:
                    self.alerted_warning_high_7.remove(symbol)
                    print(f"15분봉 RSI(7) 주의 상단 알림 초기화: {symbol}")
                if rsi_7_15m > self.rsi_warning_low and symbol in self.alerted_warning_low_7:
                    self.alerted_warning_low_7.remove(symbol)
                    print(f"15분봉 RSI(7) 주의 하단 알림 초기화: {symbol}")
            
            # 1분봉 알림 로직 (15분봉 조건이 맞는 경우에만)
            if interval == '1m' and is_closed and rsi_14_1m is not None and rsi_14_15m is not None and rsi_7_15m is not None:
                # 15분봉이 주의 단계 이상인 경우에만 1분봉 알림 (과매수/과매도 또는 주의)
                if (rsi_14_15m >= self.rsi_warning_high or rsi_14_15m <= self.rsi_warning_low or 
                    rsi_7_15m >= self.rsi_warning_high or rsi_7_15m <= self.rsi_warning_low):
                    # 1분봉 RSI(14) 과매수/과매도 알림
                    if rsi_14_1m >= self.rsi_overbought and symbol not in self.alerted_strong_14:
                        message = f"🔥 <b>1분봉 RSI(14) 과매수 (15분봉 주의 이상) - {symbol}</b>\n\n" \
                                  f"1분봉 RSI(14): {rsi_14_1m:.2f}\n" \
                                  f"1분봉 RSI(7): {rsi_7_1m if rsi_7_1m is not None else '-'}\n" \
                                  f"15분봉 RSI(14): {rsi_14_15m:.2f}\n" \
                                  f"15분봉 RSI(7): {rsi_7_15m:.2f}\n" \
                                  f"현재 가격: {price:.8f} USDT"
                        self.telegram_bot.send_message(message)
                        self.alerted_strong_14.add(symbol)
                        print(f"1분봉 RSI(14) 과매수 알림 전송 (15분봉 주의 이상): {symbol} - RSI(14): {rsi_14_1m:.2f}")
                    
                    elif rsi_14_1m <= self.rsi_oversold and symbol not in self.alerted_strong_14:
                        message = f"🔥 <b>1분봉 RSI(14) 과매도 (15분봉 주의 이상) - {symbol}</b>\n\n" \
                                  f"1분봉 RSI(14): {rsi_14_1m:.2f}\n" \
                                  f"1분봉 RSI(7): {rsi_7_1m if rsi_7_1m is not None else '-'}\n" \
                                  f"15분봉 RSI(14): {rsi_14_15m:.2f}\n" \
                                  f"15분봉 RSI(7): {rsi_7_15m:.2f}\n" \
                                  f"현재 가격: {price:.8f} USDT"
                        self.telegram_bot.send_message(message)
                        self.alerted_strong_14.add(symbol)
                        print(f"1분봉 RSI(14) 과매도 알림 전송 (15분봉 주의 이상): {symbol} - RSI(14): {rsi_14_1m:.2f}")
                    
                    # 1분봉 RSI(7) 과매수/과매도 알림
                    if rsi_7_1m is not None:
                        if rsi_7_1m >= self.rsi_overbought and symbol not in self.alerted_strong_7:
                            message = f"🔥 <b>1분봉 RSI(7) 과매수 (15분봉 주의 이상) - {symbol}</b>\n\n" \
                                      f"1분봉 RSI(14): {rsi_14_1m:.2f}\n" \
                                      f"1분봉 RSI(7): {rsi_7_1m:.2f}\n" \
                                      f"15분봉 RSI(14): {rsi_14_15m:.2f}\n" \
                                      f"15분봉 RSI(7): {rsi_7_15m:.2f}\n" \
                                      f"현재 가격: {price:.8f} USDT"
                            self.telegram_bot.send_message(message)
                            self.alerted_strong_7.add(symbol)
                            print(f"1분봉 RSI(7) 과매수 알림 전송 (15분봉 주의 이상): {symbol} - RSI(7): {rsi_7_1m:.2f}")
                        
                        elif rsi_7_1m <= self.rsi_oversold and symbol not in self.alerted_strong_7:
                            message = f"🔥 <b>1분봉 RSI(7) 과매도 (15분봉 주의 이상) - {symbol}</b>\n\n" \
                                      f"1분봉 RSI(14): {rsi_14_1m:.2f}\n" \
                                      f"1분봉 RSI(7): {rsi_7_1m:.2f}\n" \
                                      f"15분봉 RSI(14): {rsi_14_15m:.2f}\n" \
                                      f"15분봉 RSI(7): {rsi_7_15m:.2f}\n" \
                                      f"현재 가격: {price:.8f} USDT"
                            self.telegram_bot.send_message(message)
                            self.alerted_strong_7.add(symbol)
                            print(f"1분봉 RSI(7) 과매도 알림 전송 (15분봉 주의 이상): {symbol} - RSI(7): {rsi_7_1m:.2f}")
                
                # 15분봉 주의 단계가 해제되면 1분봉 알림도 초기화
                if (rsi_14_15m < self.rsi_warning_high and rsi_14_15m > self.rsi_warning_low and 
                    rsi_7_15m < self.rsi_warning_high and rsi_7_15m > self.rsi_warning_low):
                    if symbol in self.alerted_strong_14:
                        self.alerted_strong_14.remove(symbol)
                        print(f"1분봉 RSI(14) 알림 초기화 (15분봉 주의 단계 해제): {symbol}")
                    if symbol in self.alerted_strong_7:
                        self.alerted_strong_7.remove(symbol)
                        print(f"1분봉 RSI(7) 알림 초기화 (15분봉 주의 단계 해제): {symbol}")
        except Exception as e:
            print(f"Error processing message: {e}")
            print(f"Raw message: {message}")
    
    def on_error(self, ws, error):
        print(f"Error: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        print("WebSocket connection closed")
        self.telegram_bot.stop()
    
    def on_open(self, ws):
        print("WebSocket connection opened")
        print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        # 초기 데이터 로드
        symbols = get_top_coins(30)
        for symbol in symbols:
            self.initialize_symbol_data(symbol)
        # 초기 RSI 상태 메시지 전송 (극단치 TOP10)
        if self.current_rsi_14_1m or self.current_rsi_14_15m:
            # 극단값 계산: 1분봉/15분봉 RSI(14) 중 |RSI-50|이 가장 큰 값
            rsi_dict = {}
            for symbol in set(list(self.current_rsi_14_1m.keys()) + list(self.current_rsi_14_15m.keys())):
                rsi_dict[symbol] = {
                    '1m': {
                        'rsi14': self.current_rsi_14_1m.get(symbol),
                        'rsi7': self.current_rsi_7_1m.get(symbol)
                    },
                    '15m': {
                        'rsi14': self.current_rsi_14_15m.get(symbol),
                        'rsi7': self.current_rsi_7_15m.get(symbol)
                    }
                }
            rsi_extremes = []
            for symbol, v in rsi_dict.items():
                rsi_1m = v['1m']['rsi14']
                rsi_15m = v['15m']['rsi14']
                candidates = [x for x in [rsi_1m, rsi_15m] if x is not None]
                if candidates:
                    extreme = max(candidates, key=lambda x: abs(x-50))
                    rsi_extremes.append((symbol, extreme))
            rsi_extremes.sort(key=lambda x: abs(x[1]-50), reverse=True)
            top10 = [x[0] for x in rsi_extremes[:10]]
            message = "📊 <b>RSI 모니터링 시작 (극단치 TOP10, 1분/15분봉)</b>\n\n"
            for symbol in top10:
                m1 = rsi_dict[symbol]['1m']
                m15 = rsi_dict[symbol]['15m']
                message += f"<b>{symbol}</b>\n"
                message += f"  1분봉 RSI(14): {m1['rsi14'] if m1['rsi14'] is not None else '-'}\n"
                message += f"  1분봉 RSI(7): {m1['rsi7'] if m1['rsi7'] is not None else '-'}\n"
                message += f"  15분봉 RSI(14): {m15['rsi14'] if m15['rsi14'] is not None else '-'}\n"
                message += f"  15분봉 RSI(7): {m15['rsi7'] if m15['rsi7'] is not None else '-'}\n\n"
            self.telegram_bot.send_message(message)
    
    def start_monitoring(self):
        """
        모니터링 시작
        """
        symbols = get_top_coins(30)
        if not symbols:
            print("Failed to get top coins")
            return
        
        print(f"Monitoring symbols: {symbols}")
        
        streams = [f"{symbol.lower()}@kline_1m" for symbol in symbols] + [f"{symbol.lower()}@kline_15m" for symbol in symbols]
        ws_url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
        
        print(f"Connecting to WebSocket URL: {ws_url}")
        
        ws = websocket.WebSocketApp(
            ws_url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open
        )
        
        ws.run_forever()

if __name__ == "__main__":
    monitor = RSIMonitor()
    monitor.start_monitoring() 