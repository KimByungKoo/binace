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
import hmac
import hashlib
import urllib.parse
import os
from dotenv import load_dotenv
import numpy as np

load_dotenv()

class RSIMonitor:
    def __init__(self):
        # 123456aq
        
        self.rsi_overbought =93  # 과매수 RSI 임계값
        self.rsi_oversold = 7  # 과매도 RSI 임계값
        self.rsi_warning_high = 85  # 주의 RSI 상단 임계값
        self.rsi_warning_low =15   # 주의 RSI 하단 임계값
        self.data_length = 100  # RSI 계산을 위한 데이터 길이
        self.telegram_bot = TelegramBot(self)  # RSI 모니터 인스턴스 전달
        
        self.start_times = {}  # 각 심볼별 데이터 수집 시작 시간
        self.price_data_4h = {}  # 4시간봉 가격 데이터
        self.volume_data_4h = {}  # 4시간봉 거래량 데이터
        self.current_rsi_14_4h = {}  # 4시간봉 RSI(14)
        self.current_rsi_7_4h = {}   # 4시간봉 RSI(7)
        self.alerted_overbought_14_4h = set()  # 4시간봉 RSI(14) 과매수 알림
        self.alerted_oversold_14_4h = set()    # 4시간봉 RSI(14) 과매도 알림
        self.alerted_overbought_7_4h = set()   # 4시간봉 RSI(7) 과매수 알림
        self.alerted_oversold_7_4h = set()     # 4시간봉 RSI(7) 과매도 알림
        self.alerted_warning_high_14_4h = set()  # 4시간봉 RSI(14) 주의 상단
        self.alerted_warning_low_14_4h = set()   # 4시간봉 RSI(14) 주의 하단
        self.alerted_warning_high_7_4h = set()   # 4시간봉 RSI(7) 주의 상단
        self.alerted_warning_low_7_4h = set()    # 4시간봉 RSI(7) 주의 하단
        
        # SL/TP 관련 설정
        self.investment_amount = 10  # 투자금액 (USDT)
        self.leverage = 10  # 레버리지 배수
        self.position_size_usdt = self.investment_amount * self.leverage  # 실제 포지션 크기 (100 USDT)
        self.roi_threshold = 0.05  # ROI 5% 기준
        self.stop_loss_percent = 0.02  # 손절 2%
        self.take_profit_percent = 0.05  # 익절 5%
        self.active_positions = {}  # 활성 포지션 관리
        self.position_history = []  # 거래 이력
        
        self.futures_usdt_symbols = self.get_futures_usdt_symbols()
        # 자동주문 옵션
        self.auto_trading = False  # True: 자동주문 활성화, False: 자동주문 비활성화
        
        # 매수 조건 설정
        self.buy_conditions = {
            'rsi_15m_oversold': True,  # 15분봉 RSI 과매도
            'rsi_1m_oversold': True,   # 1분봉 RSI 과매도
            'volume_spike': True,      # 거래량 스파이크 (필수 조건)
            'price_drop': 0.03         # 가격 하락 3% 이상
        }
        
        # 거래량 스파이크 설정
        self.volume_spike_threshold = 10.0  # 평균 대비 2배 이상 거래량
        self.volume_lookback_period = 20   # 거래량 평균 계산 기간
        
        # 바이낸스 API 설정
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.api_secret = os.getenv('BINANCE_API_SECRET')
        self.base_url = 'https://api.binance.com'
        self.testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'
        
        if self.testnet:
            self.base_url = 'https://testnet.binance.vision'
            print("🔧 테스트넷 모드로 실행 중")
        else:
            print("🚀 실제 거래 모드로 실행 중")
        
        # API 키 확인
        if not self.api_key or not self.api_secret:
            print("⚠️ 경고: 바이낸스 API 키가 설정되지 않았습니다. 시뮬레이션 모드로 실행됩니다.")
            self.simulation_mode = True
        else:
            self.simulation_mode = False
            print("✅ 바이낸스 API 키가 설정되었습니다.")
        
        # 거래 설정
        self.min_order_amount = 10  # 최소 주문 금액 (USDT)
        self.max_positions = 3      # 최대 동시 포지션 수
        self.trading_type = 'FUTURES'  # 거래 타입 (FUTURES/MARGIN/SPOT)
        
        # 선물 거래 설정
        if self.trading_type == 'FUTURES':
            self.base_url = 'https://fapi.binance.com'  # 선물 거래 API
            print("📈 선물 거래 모드로 설정됨")

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
                prices = [float(candle[4]) for candle in data]  # 종가
                volumes = [float(candle[5]) for candle in data]  # 거래량
                return prices, volumes
            else:
                print(f"Error fetching historical data for {symbol}: {response.text}")
                return [], []
        except Exception as e:
            print(f"Error fetching historical data for {symbol}: {e}")
            return [], []

    def initialize_symbol_data(self, symbol):
        """
        심볼의 초기 4시간봉 데이터를 설정합니다.
        """
        print(f"\n{symbol} 초기 데이터 로드 시작...")
        prices_4h, volumes_4h = self.get_historical_data(symbol, interval='4h', limit=self.data_length)
        
        if len(prices_4h) < 14: # RSI 계산을 위한 최소 데이터 확인
            print(f"{symbol} 초기 데이터 부족: {len(prices_4h)}개. 모니터링에서 제외될 수 있습니다.")
            return

        self.price_data_4h[symbol] = deque(prices_4h, maxlen=self.data_length)
        self.volume_data_4h[symbol] = deque(volumes_4h, maxlen=self.data_length)
        
        rsi_14_4h = calculate_rsi_binance(list(prices_4h), period=14)
        rsi_7_4h = calculate_rsi_binance(list(prices_4h), period=7)
        
        self.current_rsi_14_4h[symbol] = rsi_14_4h
        self.current_rsi_7_4h[symbol] = rsi_7_4h
        
        print(f"{symbol} 초기 4시간봉 RSI 계산 완료:")
        print(f"RSI(14): {rsi_14_4h:.2f}")
        print(f"RSI(7): {rsi_7_4h:.2f}")
        
    def check_volume_spike(self, symbol, interval='15m'):
        """
        거래량 스파이크를 확인합니다.
        """
        if interval == '15m':
            volume_data = self.volume_data_15m.get(symbol, [])
        else:
            volume_data = self.volume_data_1m.get(symbol, [])
        
        volume_data = list(volume_data)  # 슬라이스를 위해 리스트로 변환
        if len(volume_data) < self.volume_lookback_period:
            return False
        
        # 최근 거래량
        current_volume = volume_data[-1]
        
        # 과거 거래량 평균 (최근 거래량 제외)
        historical_volumes = volume_data[-self.volume_lookback_period:-1]
        if not historical_volumes:
            return False
        
        avg_volume = sum(historical_volumes) / len(historical_volumes)
        
        # 거래량 스파이크 확인
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        return volume_ratio >= self.volume_spike_threshold, volume_ratio
        
    
    

    def get_current_rsi(self):
        """
        현재 모든 심볼의 4시간봉 RSI 값을 반환합니다.
        """
        print("\n=== 현재 4시간봉 RSI 상태 ===")
        result = {}
        # 4시간봉 데이터가 있는 심볼만 순회
        for symbol in self.current_rsi_14_4h.keys():
            rsi14 = self.current_rsi_14_4h.get(symbol)
            rsi7 = self.current_rsi_7_4h.get(symbol)
            if rsi14 is not None and rsi7 is not None:
                result[symbol] = {
                    '4h': {
                        'rsi14': rsi14,
                        'rsi7': rsi7
                    }
                }
                print(f"{symbol}:")
                print(f"  4시간봉 RSI(14) = {rsi14:.2f}")
                print(f"  4시간봉 RSI(7) = {rsi7:.2f}")
        print("===================\n")
        return result

    def get_rsi_summary_messages(self):
        """
        4시간봉 RSI 요약 메시지들을 생성하여 반환합니다.
        """
        rsi_dict = self.get_current_rsi()
        messages = []
        
        if not rsi_dict:
            return ["⚠️ 4시간봉 RSI 데이터가 없습니다."]
        
        # 4시간봉 과매수/과매도 TOP10
        rsi_4h_list = [(symbol, v['4h']['rsi14']) for symbol, v in rsi_dict.items() if v.get('4h') and v['4h'].get('rsi14') is not None]
        
        rsi_4h_over = sorted([x for x in rsi_4h_list if x[1] >= 70], key=lambda x: x[1], reverse=True)[:10]
        rsi_4h_under = sorted([x for x in rsi_4h_list if x[1] <= 30], key=lambda x: x[1])[:10]
        
        if rsi_4h_over:
            msg_4h_over = "📊 <b>4시간봉 RSI(14) 과매수 TOP10 (70~100)</b>\n\n"
            for symbol, rsi in rsi_4h_over:
                m4h = rsi_dict[symbol]['4h']
                msg_4h_over += f"<b>{symbol}</b>\n  RSI(14): {m4h['rsi14']:.2f}\n  RSI(7): {m4h['rsi7']:.2f}\n\n"
            messages.append(msg_4h_over)
        
        if rsi_4h_under:
            msg_4h_under = "📊 <b>4시간봉 RSI(14) 과매도 TOP10 (0~30)</b>\n\n"
            for symbol, rsi in rsi_4h_under:
                m4h = rsi_dict[symbol]['4h']
                msg_4h_under += f"<b>{symbol}</b>\n  RSI(14): {m4h['rsi14']:.2f}\n  RSI(7): {m4h['rsi7']:.2f}\n\n"
            messages.append(msg_4h_under)
            
        if not messages:
            messages.append("ℹ️ 현재 과매수/과매도 상태인 4시간봉 코인이 없습니다.")

        return messages

    def on_message(self, ws, message):
        """
        웹소켓 메시지 처리 (4시간봉 전용)
        """
        try:
            data = json.loads(message)
            stream_data = data.get('data', {})
            symbol = stream_data.get('s', '')
            kline = stream_data.get('k', {})
            interval = kline.get('i', '')
            price = float(kline.get('c', 0))
            volume = float(kline.get('v', 0))
            is_closed = kline.get('x', False)

            if not symbol or price == 0 or interval != '4h':
                return

            # 데이터가 초기화될 때까지 수신 메시지 무시
            if symbol not in self.price_data_4h:
                return

            # 실시간 RSI 계산: 진행 중인 캔들 가격을 price_data에 임시로 반영
            price_list = list(self.price_data_4h[symbol])
            
            # if(symbol == 'REIUSDT'):

            #     print(f"symbol: {symbol}")
            #     print(f"price: {price}")
            #     print(f"volume: {volume}")
            # print(f"is_closed: {is_closed}")

            if is_closed:
                # 봉 마감: 새로운 봉 데이터 추가
                self.price_data_4h[symbol].append(price)
                self.volume_data_4h[symbol].append(volume)
                price_list = list(self.price_data_4h[symbol]) # 업데이트된 리스트 사용
            else:
                # 봉 진행 중: 마지막 봉의 가격을 현재 가격으로 교체
                if price_list:
                    price_list[-1] = price
                else:
                    # 데이터가 없는 경우 현재 가격으로 시작
                    price_list = [price]
            
            # RSI 계산 (데이터가 충분할 경우)
            if len(price_list) >= 14:
                rsi_14 = calculate_rsi_binance(price_list, period=14)
                rsi_7 = calculate_rsi_binance(price_list, period=7)
                self.current_rsi_14_4h[symbol] = rsi_14
                self.current_rsi_7_4h[symbol] = rsi_7

            # --- 항상 dict에서 값을 꺼내서 지역변수로 사용 ---
            rsi_14_4h = self.current_rsi_14_4h.get(symbol)
            rsi_7_4h = self.current_rsi_7_4h.get(symbol)

            # SL/TP 체크 (모든 가격 업데이트에서)
            self.check_sl_tp(symbol, price)
            
            # RSI 알림 로직 (실시간 봉에서만 동작)
            if not is_closed and rsi_14_4h is not None and rsi_7_4h is not None:
                # 4시간봉 RSI(14) 과매수 알림
                if rsi_14_4h >= self.rsi_overbought and symbol not in self.alerted_overbought_14_4h:
                    msg = f"🔴 <b>4시간봉 RSI(14) 과매수 알림 - {symbol}</b>\n\n" \
                          f"RSI(14): {rsi_14_4h:.2f}\n" \
                          f"RSI(7): {rsi_7_4h:.2f}\n" \
                          f"현재가: {price:.8f} USDT"
                    self.telegram_bot.send_message(msg)
                    self.alerted_overbought_14_4h.add(symbol)
                    print(f"4시간봉 RSI(14) 과매수 알림: {symbol} - RSI: {rsi_14_4h:.2f}")
                
                # 4시간봉 RSI(14) 과매도 알림
                elif rsi_14_4h <= self.rsi_oversold and symbol not in self.alerted_oversold_14_4h:
                    msg = f"🟢 <b>4시간봉 RSI(14) 과매도 알림 - {symbol}</b>\n\n" \
                          f"RSI(14): {rsi_14_4h:.2f}\n" \
                          f"RSI(7): {rsi_7_4h:.2f}\n" \
                          f"현재가: {price:.8f} USDT"
                    self.telegram_bot.send_message(msg)
                    self.alerted_oversold_14_4h.add(symbol)
                    print(f"4시간봉 RSI(14) 과매도 알림: {symbol} - RSI: {rsi_14_4h:.2f}")
                
                # 4시간봉 RSI(7) 과매수 알림
                if rsi_7_4h >= self.rsi_overbought and symbol not in self.alerted_overbought_7_4h:
                    msg = f"🔴 <b>4시간봉 RSI(7) 과매수 알림 - {symbol}</b>\n\n" \
                          f"RSI(14): {rsi_14_4h:.2f}\n" \
                          f"RSI(7): {rsi_7_4h:.2f}\n" \
                          f"현재가: {price:.8f} USDT"
                    self.telegram_bot.send_message(msg)
                    self.alerted_overbought_7_4h.add(symbol)
                    print(f"4시간봉 RSI(7) 과매수 알림: {symbol} - RSI: {rsi_7_4h:.2f}")
                
                # 4시간봉 RSI(7) 과매도 알림
                elif rsi_7_4h <= self.rsi_oversold and symbol not in self.alerted_oversold_7_4h:
                    msg = f"🟢 <b>4시간봉 RSI(7) 과매도 알림 - {symbol}</b>\n\n" \
                          f"RSI(14): {rsi_14_4h:.2f}\n" \
                          f"RSI(7): {rsi_7_4h:.2f}\n" \
                          f"현재가: {price:.8f} USDT"
                    self.telegram_bot.send_message(msg)
                    self.alerted_oversold_7_4h.add(symbol)
                    print(f"4시간봉 RSI(7) 과매도 알림: {symbol} - RSI: {rsi_7_4h:.2f}")
                
                # 4시간봉 RSI 주의 알림 (과매수/과매도 구간에서 벗어났을 때)
                if rsi_14_4h < self.rsi_overbought and symbol in self.alerted_overbought_14_4h:
                    self.alerted_overbought_14_4h.remove(symbol)
                if rsi_14_4h > self.rsi_oversold and symbol in self.alerted_oversold_14_4h:
                    self.alerted_oversold_14_4h.remove(symbol)
                if rsi_7_4h < self.rsi_overbought and symbol in self.alerted_overbought_7_4h:
                    self.alerted_overbought_7_4h.remove(symbol)
                if rsi_7_4h > self.rsi_oversold and symbol in self.alerted_oversold_7_4h:
                    self.alerted_oversold_7_4h.remove(symbol)

        except Exception as e:
            print(f"Error processing message: {e}")
            print(f"Raw message: {message}")
    
    def on_error(self, ws, error):
        print(f"Error: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        print(f"WebSocket connection closed (code={close_status_code}, msg={close_msg})")
        self.telegram_bot.stop()
        print("5초 후 재연결 시도...")
        time.sleep(5)
        self.start_monitoring()
    
    def on_open(self, ws):
        print(f"WebSocket connection opened. Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    def _load_initial_data(self):
        """
        백그라운드에서 초기 데이터를 안전하게 로드하고 RSI를 계산합니다.
        """
        print("백그라운드에서 초기 데이터 로드를 시작합니다...")
        symbols = self.futures_usdt_symbols
        symbols = list(dict.fromkeys(symbols)) # 중복 제거
        
        for symbol in symbols:
            try:
                # API 속도 제한을 피하기 위해 0.5초 딜레이
                time.sleep(0.5)
                print(f"{symbol} 데이터 로드 중...")
                prices_4h, volumes_4h = self.get_historical_data(symbol, interval='4h', limit=self.data_length)
                
                if prices_4h and len(prices_4h) >= 14:
                    self.price_data_4h[symbol] = deque(prices_4h, maxlen=self.data_length)
                    self.volume_data_4h[symbol] = deque(volumes_4h, maxlen=self.data_length)
                    
                    rsi_14_4h = calculate_rsi_binance(list(prices_4h), period=14)
                    rsi_7_4h = calculate_rsi_binance(list(prices_4h), period=7)
                    
                    self.current_rsi_14_4h[symbol] = rsi_14_4h
                    self.current_rsi_7_4h[symbol] = rsi_7_4h
                else:
                    print(f"[데이터 부족] {symbol}: 데이터가 부족하여 모니터링에서 제외됩니다.")
            except Exception as e:
                print(f"{symbol} 데이터 로드 중 오류 발생: {e}")

        print("\n초기 데이터 로드가 완료되었습니다.")
        # 초기 RSI 상태 메시지 전송
        if self.current_rsi_14_4h:
            print("초기 RSI 요약 메시지를 텔레그램으로 전송합니다.")
            rsi_messages = self.get_rsi_summary_messages()
            for message in rsi_messages:
                self.telegram_bot.send_message(message)
        else:
            print("전송할 초기 RSI 데이터가 없습니다.")

    def start_monitoring(self):
        # 1. 모든 심볼 리스트 가져오기 (API 호출 최소화)
        all_symbols = self.futures_usdt_symbols
        if not all_symbols:
            print("모니터링할 심볼을 가져오지 못했습니다. 프로그램을 종료합니다.")
            return

        # 2. 백그라운드에서 데이터 로드 시작
        threading.Thread(target=self._load_initial_data, daemon=True).start()

        # 3. 웹소켓 연결 시작
        print(f"{len(all_symbols)}개 전체 심볼에 대한 실시간 스트림 연결을 시작합니다.")
        chunk_size = 30
        symbol_chunks = [all_symbols[i:i + chunk_size] for i in range(0, len(all_symbols), chunk_size)]
        
        for chunk in symbol_chunks:
            streams = [f"{s.lower()}@kline_4h" for s in chunk]
            ws_url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
            print(f"Connecting to WebSocket for {len(chunk)} symbols...")
            ws = websocket.WebSocketApp(
                ws_url,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
                on_open=self.on_open
            )
            threading.Thread(
                target=lambda: ws.run_forever(ping_interval=30, ping_timeout=10),
                daemon=True
            ).start()
            
        # 메인 스레드가 종료되지 않도록 유지
        while True:
            time.sleep(60)

    def _generate_signature(self, params):
        """
        바이낸스 API 서명을 생성합니다.
        """
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _make_request(self, method, endpoint, params=None, signed=False):
        """
        바이낸스 API 요청을 보냅니다.
        """
        url = f"{self.base_url}{endpoint}"
        headers = {'X-MBX-APIKEY': self.api_key}
        
        if params is None:
            params = {}
        
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._generate_signature(params)
        
        try:
            if method == 'GET':
                response = requests.get(url, params=params, headers=headers)
            elif method == 'POST':
                response = requests.post(url, data=params, headers=headers)
            elif method == 'DELETE':
                response = requests.delete(url, data=params, headers=headers)
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"API 요청 실패: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"API 요청 중 오류: {e}")
            return None
    
    
    
    def get_futures_usdt_symbols(self):
        """
        바이낸스 USDT-M 선물 마켓에서 실제 거래(TRADING) 중인 심볼 리스트 반환
        """
        try:
            url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
            response = requests.get(url)
            if response.status_code != 200:
                return []
            data = response.json()
            symbols = [
                s['symbol']
                for s in data['symbols']
                if s['contractType'] == 'PERPETUAL'
                and s['quoteAsset'] == 'USDT'
                and s['status'] == 'TRADING'
            ]
            return symbols
        except Exception as e:
            print(f"선물 심볼 조회 오류: {e}")
            return []

    def get_ema_321_proximity(self, top_n=10):
        """
        4시간봉 321EMA와 현재가 이격률이 가장 작은 USDT-M 선물 코인 TOP N 반환
        """
        symbols = self.futures_usdt_symbols
        results = []
        for symbol in symbols:
            try:
                url = "https://fapi.binance.com/fapi/v1/klines"
                params = {'symbol': symbol, 'interval': '4h', 'limit': 350}
                response = requests.get(url, params=params)
                if response.status_code != 200:
                    continue
                data = response.json()
                closes = [float(c[4]) for c in data]
                if len(closes) < 321:
                    continue
                ema = self.calculate_ema(closes, 321)[-1]
                current_price = closes[-1]
                diff = abs(current_price - ema) / ema * 100
                results.append((symbol, current_price, ema, diff))
            except Exception as e:
                print(f"{symbol} 321EMA 계산 오류: {e}")
                continue
        results.sort(key=lambda x: x[3])
        return results[:top_n]

    def calculate_ema(self, prices, period):
        """
        단순 EMA 계산 함수 (numpy 활용)
        """
        prices = np.array(prices)
        ema = np.zeros_like(prices)
        alpha = 2 / (period + 1)
        ema[0] = prices[0]
        for i in range(1, len(prices)):
            ema[i] = alpha * prices[i] + (1 - alpha) * ema[i-1]
        return ema

if __name__ == "__main__":
    monitor = RSIMonitor()
    monitor.start_monitoring() 