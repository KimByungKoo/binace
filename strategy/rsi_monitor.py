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
        self.rsi_overbought = 95  # 과매수 RSI 임계값
        self.rsi_oversold = 5  # 과매도 RSI 임계값
        self.data_length = 100  # RSI 계산을 위한 데이터 길이
        self.telegram_bot = TelegramBot(self)  # RSI 모니터 인스턴스 전달
        self.alerted_overbought_14 = set()  # RSI(14) 과매수 알림을 보낸 심볼 추적
        self.alerted_oversold_14 = set()  # RSI(14) 과매도 알림을 보낸 심볼 추적
        self.alerted_overbought_7 = set()  # RSI(7) 과매수 알림을 보낸 심볼 추적
        self.alerted_oversold_7 = set()  # RSI(7) 과매도 알림을 보낸 심볼 추적
        self.current_rsi_14 = {}  # 현재 RSI(14) 값 저장
        self.current_rsi_7 = {}  # 현재 RSI(7) 값 저장
        self.start_times = {}  # 각 심볼별 데이터 수집 시작 시간

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
                # 종가 데이터만 추출 (인덱스 4가 종가)
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
        historical_prices = self.get_historical_data(symbol)
        if historical_prices:
            self.price_data[symbol] = deque(historical_prices, maxlen=self.data_length)
            if len(historical_prices) >= self.data_length:
                rsi_14 = calculate_rsi_binance(list(historical_prices), period=14)
                rsi_7 = calculate_rsi_binance(list(historical_prices), period=7)
                self.current_rsi_14[symbol] = rsi_14
                self.current_rsi_7[symbol] = rsi_7
                print(f"{symbol} 초기 RSI 계산 완료:")
                print(f"RSI(14): {rsi_14:.2f}")
                print(f"RSI(7): {rsi_7:.2f}")
            else:
                print(f"{symbol} 초기 데이터 부족: {len(historical_prices)}개")
        else:
            print(f"{symbol} 초기 데이터 로드 실패")
            self.price_data[symbol] = deque(maxlen=self.data_length)
        
    def get_current_rsi(self):
        """
        현재 모든 심볼의 RSI 값을 반환합니다.
        """
        print("\n=== 현재 RSI 상태 ===")
        for symbol in self.current_rsi_14.keys():
            if symbol in self.start_times:
                elapsed_time = time.time() - self.start_times[symbol]
                print(f"{symbol}:")
                print(f"  RSI(14) = {self.current_rsi_14[symbol]:.2f}")
                print(f"  RSI(7) = {self.current_rsi_7[symbol]:.2f}")
                print(f"  수집 시간: {elapsed_time:.1f}초")
            else:
                print(f"{symbol}:")
                print(f"  RSI(14) = {self.current_rsi_14[symbol]:.2f}")
                print(f"  RSI(7) = {self.current_rsi_7[symbol]:.2f}")
        print("===================\n")
        return self.current_rsi_14, self.current_rsi_7
        
    def on_message(self, ws, message):
        """
        웹소켓 메시지 처리
        """
        try:
            data = json.loads(message)
            stream_data = data.get('data', {})
            symbol = stream_data.get('s', '')
            kline = stream_data.get('k', {})
            
            # 종가 데이터만 사용
            price = float(kline.get('c', 0))  # 'c'는 종가(Close)
            is_closed = kline.get('x', False)  # 캔들이 닫혔는지 확인
            
            if not symbol or price == 0:
                return
                
            if symbol not in self.price_data:
                self.initialize_symbol_data(symbol)
                self.start_times[symbol] = time.time()
            
            # 캔들이 닫힐 때만 데이터 추가
            if is_closed:
                self.price_data[symbol].append(price)
                
                if len(self.price_data[symbol]) >= self.data_length:
                    prices = list(self.price_data[symbol])
                    rsi_14 = calculate_rsi_binance(prices, period=14)
                    rsi_7 = calculate_rsi_binance(prices, period=7)
                    self.current_rsi_14[symbol] = rsi_14
                    self.current_rsi_7[symbol] = rsi_7
                    
                    if symbol in self.start_times:
                        elapsed_time = time.time() - self.start_times[symbol]
                        print(f"\n{symbol} 실시간 데이터 수집 완료")
                        print(f"수집된 데이터: {len(self.price_data[symbol])}개")
                        print(f"수집 시간: {elapsed_time:.1f}초")
                        print(f"RSI(14): {rsi_14:.2f}")
                        print(f"RSI(7): {rsi_7:.2f}")
                        print(f"현재 가격: {price:.8f}")
                        del self.start_times[symbol]
                    
                    # RSI(14) 과매수 조건 체크
                    if rsi_14 >= self.rsi_overbought and symbol not in self.alerted_overbought_14:
                        message = f"🚨 <b>RSI(14) 과매수 알림</b>\n\n" \
                                 f"심볼: {symbol}\n" \
                                 f"RSI(14): {rsi_14:.2f}\n" \
                                 f"RSI(7): {rsi_7:.2f}\n" \
                                 f"현재 가격: {price:.8f} USDT"
                        
                        self.telegram_bot.send_message(message)
                        self.alerted_overbought_14.add(symbol)
                        print(f"RSI(14) 과매수 알림 전송: {symbol} - RSI(14): {rsi_14:.2f}")
                    
                    # RSI(14) 과매도 조건 체크
                    elif rsi_14 <= self.rsi_oversold and symbol not in self.alerted_oversold_14:
                        message = f"📉 <b>RSI(14) 과매도 알림</b>\n\n" \
                                 f"심볼: {symbol}\n" \
                                 f"RSI(14): {rsi_14:.2f}\n" \
                                 f"RSI(7): {rsi_7:.2f}\n" \
                                 f"현재 가격: {price:.8f} USDT"
                        
                        self.telegram_bot.send_message(message)
                        self.alerted_oversold_14.add(symbol)
                        print(f"RSI(14) 과매도 알림 전송: {symbol} - RSI(14): {rsi_14:.2f}")

                    # RSI(7) 과매수 조건 체크
                    if rsi_7 >= self.rsi_overbought and symbol not in self.alerted_overbought_7:
                        message = f"🚨 <b>RSI(7) 과매수 알림</b>\n\n" \
                                 f"심볼: {symbol}\n" \
                                 f"RSI(14): {rsi_14:.2f}\n" \
                                 f"RSI(7): {rsi_7:.2f}\n" \
                                 f"현재 가격: {price:.8f} USDT"
                        
                        self.telegram_bot.send_message(message)
                        self.alerted_overbought_7.add(symbol)
                        print(f"RSI(7) 과매수 알림 전송: {symbol} - RSI(7): {rsi_7:.2f}")
                    
                    # RSI(7) 과매도 조건 체크
                    elif rsi_7 <= self.rsi_oversold and symbol not in self.alerted_oversold_7:
                        message = f"📉 <b>RSI(7) 과매도 알림</b>\n\n" \
                                 f"심볼: {symbol}\n" \
                                 f"RSI(14): {rsi_14:.2f}\n" \
                                 f"RSI(7): {rsi_7:.2f}\n" \
                                 f"현재 가격: {price:.8f} USDT"
                        
                        self.telegram_bot.send_message(message)
                        self.alerted_oversold_7.add(symbol)
                        print(f"RSI(7) 과매도 알림 전송: {symbol} - RSI(7): {rsi_7:.2f}")
                    
                    # RSI(14) 알림 초기화
                    if rsi_14 < self.rsi_overbought and symbol in self.alerted_overbought_14:
                        self.alerted_overbought_14.remove(symbol)
                        print(f"RSI(14) 과매수 알림 초기화: {symbol} - RSI(14): {rsi_14:.2f}")
                    
                    if rsi_14 > self.rsi_oversold and symbol in self.alerted_oversold_14:
                        self.alerted_oversold_14.remove(symbol)
                        print(f"RSI(14) 과매도 알림 초기화: {symbol} - RSI(14): {rsi_14:.2f}")

                    # RSI(7) 알림 초기화
                    if rsi_7 < self.rsi_overbought and symbol in self.alerted_overbought_7:
                        self.alerted_overbought_7.remove(symbol)
                        print(f"RSI(7) 과매수 알림 초기화: {symbol} - RSI(7): {rsi_7:.2f}")
                    
                    if rsi_7 > self.rsi_oversold and symbol in self.alerted_oversold_7:
                        self.alerted_oversold_7.remove(symbol)
                        print(f"RSI(7) 과매도 알림 초기화: {symbol} - RSI(7): {rsi_7:.2f}")
                    
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
        symbols = get_top_coins(10)
        for symbol in symbols:
            self.initialize_symbol_data(symbol)
        
        # 초기 RSI 상태 메시지 전송
        if self.current_rsi_14:
            message = "📊 <b>RSI 모니터링 시작</b>\n\n"
            for symbol in self.current_rsi_14.keys():
                message += f"{symbol}:\n"
                message += f"RSI(14): {self.current_rsi_14[symbol]:.2f}\n"
                message += f"RSI(7): {self.current_rsi_7[symbol]:.2f}\n\n"
            self.telegram_bot.send_message(message)
    
    def start_monitoring(self):
        """
        모니터링 시작
        """
        symbols = get_top_coins(10)
        if not symbols:
            print("Failed to get top coins")
            return
        
        print(f"Monitoring symbols: {symbols}")
        
        streams = [f"{symbol.lower()}@kline_1m" for symbol in symbols]
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