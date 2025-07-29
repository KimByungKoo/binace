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

import sys
import logging.handlers

# 로깅 설정1q
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 파일 핸들러 (최대 10MB, 7개 백업 유지)
file_handler = logging.handlers.RotatingFileHandler(
    "rsi_monitor.log",
    maxBytes=10*1024*1024, # 10MB
    backupCount=7,
    encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# 콘솔 핸들러
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

# 전역 예외 핸들러
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.critical("예상치 못한 오류 발생", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_exception

load_dotenv()

class RSIMonitor:
    def __init__(self):
        
        
        # RSI 임계값
        self.rsi_overbought = 90
        self.rsi_oversold = 10
        self.rsi_overbought_15m = 80
        self.rsi_oversold_15m = 20

        self.data_length = 200  # RSI 계산을 위한 데이터 길이 (조금 더 넉넉하게)
        self.telegram_bot = TelegramBot(self)
        
        # 데이터 저장 구조 변경: 캔들 전체 정보를 저장
        self.kline_data_4h = {} # 4시간봉 캔들 데이터
        self.kline_data_15m = {} # 15분봉 캔들 데이터

        # 실시간 RSI 값 저장
        self.current_rsi_14_4h = {}
        self.current_rsi_7_4h = {}
        self.current_rsi_14_15m = {}
        self.current_rsi_7_15m = {}

        # 알림 상태 관리
        self.alerted_overbought_14_4h = set()
        self.alerted_oversold_14_4h = set()
        self.alerted_overbought_7_4h = set()
        self.alerted_oversold_7_4h = set()
        self.alerted_overbought_14_15m = set()
        self.alerted_oversold_14_15m = set()

        # ... (기존 나머지 설정들은 유지) ...
        
        self.investment_amount = 10
        self.leverage = 10
        self.position_size_usdt = self.investment_amount * self.leverage
        self.roi_threshold = 0.05
        self.stop_loss_percent = 0.02
        self.take_profit_percent = 0.05
        self.active_positions = {}
        self.position_history = []
        
        self.futures_usdt_symbols = self.get_futures_usdt_symbols()
        self.auto_trading = False
        
        self.buy_conditions = {
            'rsi_15m_oversold': True,
            'rsi_1m_oversold': True,
            'volume_spike': True,
            'price_drop': 0.03
        }
        
        self.volume_spike_threshold = 10.0
        self.volume_lookback_period = 20
        
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.api_secret = os.getenv('BINANCE_API_SECRET')
        self.base_url = 'https://api.binance.com'
        self.testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'
        
        if self.testnet:
            self.base_url = 'https://testnet.binance.vision'
            print("🔧 테스트넷 모드로 실행 중")
        else:
            print("🚀 실제 거래 모드로 실행 중")
        
        if not self.api_key or not self.api_secret:
            print("⚠️ 경고: 바이낸스 API 키가 설정되지 않았습니다. 시뮬레이션 모드로 실행됩니다.")
            self.simulation_mode = True
        else:
            self.simulation_mode = False
            print("✅ 바이낸스 API 키가 설정되었습니다.")
        
        self.min_order_amount = 10
        self.max_positions = 3
        self.trading_type = 'FUTURES'
        
        if self.trading_type == 'FUTURES':
            self.base_url = 'https://fapi.binance.com'
            print("📈 선물 거래 모드로 설정됨")

    def get_historical_data(self, symbol, interval, limit=None, startTime=None):
        """
        Binance API를 통해 과거 KLINE 데이터를 가져옵니다.
        startTime 파라미터를 지원하도록 수정되었습니다.
        """
        try:
            url = "https://fapi.binance.com/fapi/v1/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
            }
            if limit:
                params['limit'] = limit
            if startTime:
                params['startTime'] = startTime

            response = requests.get(url, params=params, timeout=10) # 타임아웃 추가
            response.raise_for_status() # HTTP 오류 발생 시 예외 발생
            data = response.json()
            logging.debug(f"[{symbol}-{interval}] get_historical_data 응답: {len(data)}개 데이터 수신")
            return data # 전체 kline 데이터 반환
        except requests.exceptions.Timeout:
            logging.error(f"[{symbol}-{interval}] 데이터 요청 타임아웃 발생.")
            return []
        except requests.exceptions.RequestException as e:
            logging.error(f"[{symbol}-{interval}] 데이터 요청 중 네트워크 오류 발생: {e}")
            return []
        except json.JSONDecodeError:
            logging.error(f"[{symbol}-{interval}] API 응답 JSON 디코딩 실패: {response.text}")
            return []
        except Exception as e:
            logging.error(f"[{symbol}-{interval}] get_historical_data 함수에서 예상치 못한 오류 발생: {e}", exc_info=True)
            return []

    
        
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
        현재 모든 심볼의 4시간봉 및 15분봉 RSI 값을 반환합니다.
        """
        print("\n=== 현재 RSI 상태 ===")
        result = {}
        all_symbols = set(self.current_rsi_14_4h.keys()) | set(self.current_rsi_14_15m.keys())

        for symbol in all_symbols:
            result[symbol] = {}
            
            # 4시간봉 데이터
            rsi14_4h = self.current_rsi_14_4h.get(symbol)
            rsi7_4h = self.current_rsi_7_4h.get(symbol)
            if rsi14_4h is not None and rsi7_4h is not None:
                result[symbol]['4h'] = {'rsi14': rsi14_4h, 'rsi7': rsi7_4h}
                print(f"{symbol} 4h: RSI(14)={rsi14_4h:.2f}, RSI(7)={rsi7_4h:.2f}")

            # 15분봉 데이터
            rsi14_15m = self.current_rsi_14_15m.get(symbol)
            rsi7_15m = self.current_rsi_7_15m.get(symbol)
            if rsi14_15m is not None and rsi7_15m is not None:
                result[symbol]['15m'] = {'rsi14': rsi14_15m, 'rsi7': rsi7_15m}
                # print(f"{symbol} 15m: RSI(14)={rsi14_15m:.2f}, RSI(7)={rsi7_15m:.2f}")

        print("===================\n")
        return result

    def get_rsi_summary_messages(self):
        """
        4시간봉 RSI 요약 메시지들을 생성하여 반환합니다. (15분봉 데이터 포함)
        """
        rsi_dict = self.get_current_rsi()
        messages = []
        
        if not rsi_dict:
            return ["⚠️ RSI 데이터가 없습니다."]
        
        # 4시간봉 과매수/과매도 TOP10
        rsi_4h_list = [(symbol, v['4h']['rsi14']) for symbol, v in rsi_dict.items() if v.get('4h') and v['4h'].get('rsi14') is not None]
        
        rsi_4h_over = sorted([x for x in rsi_4h_list if x[1] >= 70], key=lambda x: x[1], reverse=True)[:10]
        rsi_4h_under = sorted([x for x in rsi_4h_list if x[1] <= 30], key=lambda x: x[1])[:10]
        
        if rsi_4h_over:
            msg_4h_over = "📊 <b>4시간봉 RSI(14) 과매수 TOP10 (70~100)</b>\n\n"
            for symbol, rsi in rsi_4h_over:
                m4h = rsi_dict[symbol].get('4h', {})
                m15m = rsi_dict[symbol].get('15m', {})
                rsi14_4h = m4h.get('rsi14', 'N/A')
                rsi7_4h = m4h.get('rsi7', 'N/A')
                rsi14_15m = m15m.get('rsi14', 'N/A')
                rsi7_15m = m15m.get('rsi7', 'N/A')
                
                msg_4h_over += f"<b>{symbol}</b>\n" \
                              f"  - 4h: (14)-{rsi14_4h:.2f} | (7)-{rsi7_4h:.2f}\n" \
                              f"  - 15m: (14)-{rsi14_15m:.2f} | (7)-{rsi7_15m:.2f}\n\n"
            messages.append(msg_4h_over)
        
        if rsi_4h_under:
            msg_4h_under = "📊 <b>4시간봉 RSI(14) 과매도 TOP10 (0~30)</b>\n\n"
            for symbol, rsi in rsi_4h_under:
                m4h = rsi_dict[symbol].get('4h', {})
                m15m = rsi_dict[symbol].get('15m', {})
                rsi14_4h = m4h.get('rsi14', 'N/A')
                rsi7_4h = m4h.get('rsi7', 'N/A')
                rsi14_15m = m15m.get('rsi14', 'N/A')
                rsi7_15m = m15m.get('rsi7', 'N/A')

                msg_4h_under += f"<b>{symbol}</b>\n" \
                               f"  - 4h: {rsi14_4h:.2f} | {rsi7_4h:.2f}\n" \
                               f"  - 15m: {rsi14_15m:.2f} | {rsi7_15m:.2f}\n\n"
            # messages.append(msg_4h_under)
            
        if not messages:
            messages.append("ℹ️ 현재 과매수/과매도 상태인 4시간봉 코인이 없습니다.")

        return messages

    def on_message(self, ws, message):
        """
        웹소켓 메시지 처리 (4시간봉, 15분봉)
        """
        try:
            data = json.loads(message)
            stream_data = data.get('data', {})
            symbol = stream_data.get('s', '')
            kline = stream_data.get('k', {})
            interval = kline.get('i', '')
            is_closed = kline.get('x', False)

            # if not symbol or not kline:
                # logging.debug(f"유효하지 않은 웹소켓 메시지 수신: {message}")
                # return

            # 실시간 kline 데이터를 self.kline_data에 반영
            kline_data_deque = None
            if interval == '4h':
                kline_data_deque = self.kline_data_4h
            elif interval == '15m':
                kline_data_deque = self.kline_data_15m
            
            if kline_data_deque is None or symbol not in kline_data_deque:
                # logger.warning(f"[{symbol}-{interval}] 해당 심볼/인터벌에 대한 데이터 덱이 초기화되지 않았습니다. 메시지 무시.")
                return

            new_kline = [
                kline['t'], kline['o'], kline['h'], kline['l'], kline['c'], kline['v'],
                kline['T'], kline['q'], kline['n'], kline['V'], kline['Q'], kline['B']
            ]

            if is_closed:
                kline_data_deque[symbol].append(new_kline)
                logging.debug(f"[{symbol}-{interval}] 캔들 마감: {datetime.fromtimestamp(kline['t']/1000)} 종가: {float(kline['c']):.2f}")
            else:
                if kline_data_deque[symbol]:
                    kline_data_deque[symbol][-1] = new_kline
                else:
                    kline_data_deque[symbol].append(new_kline)
                logging.debug(f"[{symbol}-{interval}] 캔들 업데이트: {datetime.fromtimestamp(kline['t']/1000)} 종가: {float(kline['c']):.2f}")

            # RSI 계산을 위한 종가 리스트 추출
            close_prices = [float(k[4]) for k in kline_data_deque[symbol]]
            if len(close_prices) < 14:
                logging.debug(f"[{symbol}-{interval}] RSI 계산을 위한 데이터 부족 ({len(close_prices)}/14)")
                return

            # 실시간 RSI 계산
            rsi_14 = calculate_rsi_binance(close_prices, period=14)
            rsi_7 = calculate_rsi_binance(close_prices, period=7)

            # 4시간봉 데이터 처리: 상태 업데이트
            if interval == '4h':
                self.current_rsi_14_4h[symbol] = rsi_14
                self.current_rsi_7_4h[symbol] = rsi_7
                if rsi_14 >= self.rsi_overbought: self.alerted_overbought_14_4h.add(symbol)
                else: self.alerted_overbought_14_4h.discard(symbol)
                if rsi_14 <= self.rsi_oversold: self.alerted_oversold_14_4h.add(symbol)
                else: self.alerted_oversold_14_4h.discard(symbol)

            # 15분봉 데이터 처리: 조건 결합 및 알림
            elif interval == '15m':
                self.current_rsi_14_15m[symbol] = rsi_14
                self.current_rsi_7_15m[symbol] = rsi_7
                price = float(kline['c'])

                # 조건 동시 만족 시 알림
                if (rsi_14 >= self.rsi_overbought_15m and 
                    symbol in self.alerted_overbought_14_4h and 
                    symbol not in self.alerted_overbought_14_15m):
                    msg = self.create_alert_message(symbol, "과매수", price, rsi_14, rsi_7)
                    self.telegram_bot.send_message(msg)
                    self.alerted_overbought_14_15m.add(symbol)
                    logging.info(f"[{symbol}] 4h 과매수 & 15m 과매수 동시 만족 알림 발송.")

                elif (rsi_14 <= self.rsi_oversold_15m and
                      symbol in self.alerted_oversold_14_4h and
                      symbol not in self.alerted_oversold_14_15m):
                    msg = self.create_alert_message(symbol, "과매도", price, rsi_14, rsi_7)
                    self.telegram_bot.send_message(msg)
                    self.alerted_oversold_14_15m.add(symbol)
                    logging.info(f"[{symbol}] 4h 과매도 & 15m 과매도 동시 만족 알림 발송.")
                
                # 15분봉 알림 상태 해제
                if rsi_14 < self.rsi_overbought_15m: self.alerted_overbought_14_15m.discard(symbol)
                if rsi_14 > self.rsi_oversold_15m: self.alerted_oversold_14_15m.discard(symbol)

        except json.JSONDecodeError:
            logging.error(f"웹소켓 메시지 JSON 디코딩 실패: {message}")
        except Exception as e:
            logging.error(f"on_message 함수에서 예상치 못한 오류 발생: {e}", exc_info=True)
            logging.error(f"Raw message: {message}")

    def create_alert_message(self, symbol, alert_type, price, rsi_14_15m, rsi_7_15m):
        """
        조건 동시 만족 시 텔레그램 메시지를 생성합니다.
        """
        rsi_14_4h = self.current_rsi_14_4h.get(symbol, 'N/A')
        rsi_7_4h = self.current_rsi_7_4h.get(symbol, 'N/A')
        
        # 'N/A'가 아닐 경우에만 소수점 포매팅
        rsi_14_4h_str = f"{rsi_14_4h:.2f}" if isinstance(rsi_14_4h, float) else rsi_14_4h
        rsi_7_4h_str = f"{rsi_7_4h:.2f}" if isinstance(rsi_7_4h, float) else rsi_7_4h

        msg = f"🔥 <b>[조건 동시 만족: {alert_type}] - {symbol}</b>\n\n" \
              f"4시간봉 {alert_type} 상태에서 15분봉도 {alert_type} 상태에 진입했습니다.\n\n" \
              f"<b>4시간봉 RSI:</b>\n" \
              f"  - RSI(14): {rsi_14_4h_str}\n" \
              f"  - RSI(7): {rsi_7_4h_str}\n" \
              f"<b>15분봉 RSI:</b>\n" \
              f"  - RSI(14): {rsi_14_15m:.2f}\n" \
              f"  - RSI(7): {rsi_7_15m:.2f}\n" \
              f"<b>현재가:</b> {price:.8f} USDT"
        return msg
    
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

    def _load_initial_data(self, symbols):
        """
        백그라운드에서 초기 데이터를 로드하고, 데이터 갭을 채웁니다.
        """
        logging.info("백그라운드 데이터 처리 시작...")
        # symbols = self.get_futures_usdt_symbols() # 이제 인자로 받으므로 주석 처리
        if not symbols:
            logging.warning("모니터링할 심볼이 없습니다.")
            return

        total_symbols = len(symbols)
        logging.info(f"총 {total_symbols}개 심볼의 초기 데이터 로드를 시작합니다.")

        for i, symbol in enumerate(symbols):
            progress = f"[{i + 1}/{total_symbols}]"
            logging.info(f"초기 데이터 로드 진행 중: {progress} {symbol}")
            time.sleep(0.1) # API 요청 제한 방지
            # Initialize deques once per symbol, outside the interval loop
            self.kline_data_4h[symbol] = deque(maxlen=self.data_length)
            self.kline_data_15m[symbol] = deque(maxlen=self.data_length)

            for interval in ['4h', '15m']:
                kline_data_key = f"kline_data_{interval}"
                
                # Select the correct deque based on interval
                target_kline_deque = None
                if interval == '4h':
                    target_kline_deque = self.kline_data_4h[symbol]
                elif interval == '15m':
                    target_kline_deque = self.kline_data_15m[symbol]
                
                if target_kline_deque is None:
                    logging.error(f"Invalid interval {interval} for symbol {symbol}")
                    continue

                # 캐시가 없으면 전체 데이터 요청 (초기 로드)
                logging.info(f"{progress} [{symbol}-{interval}] 초기 데이터 로드 중...")
                initial_data = self.get_historical_data(symbol, interval, limit=self.data_length)
                logging.debug(f"[{symbol}-{interval}] 초기 데이터 {len(initial_data)}개 수신.")
                if initial_data:
                    target_kline_deque.extend(initial_data)
                    logging.debug(f"[{symbol}-{interval}] 초기 데이터 추가 후 덱 길이: {len(target_kline_deque)}")

                # 3. 초기 RSI 계산
                if len(target_kline_deque) >= 14:
                    close_prices = [float(k[4]) for k in target_kline_deque]
                    if interval == '4h':
                        self.current_rsi_14_4h[symbol] = calculate_rsi_binance(close_prices, period=14)
                        self.current_rsi_7_4h[symbol] = calculate_rsi_binance(close_prices, period=7)
                    elif interval == '15m':
                        self.current_rsi_14_15m[symbol] = calculate_rsi_binance(close_prices, period=14)
                        self.current_rsi_7_15m[symbol] = calculate_rsi_binance(close_prices, period=7)

        logging.info("초기 데이터 로드가 완료되었습니다.")
        # 초기 RSI 상태 메시지 전송
        if self.current_rsi_14_4h:
            logging.info("초기 RSI 요약 메시지를 텔레그램으로 전송합니다.")
            rsi_messages = self.get_rsi_summary_messages()
            for message in rsi_messages:
                self.telegram_bot.send_message(message)
        else:
            logging.info("전송할 초기 RSI 데이터가 없습니다.")

    def start_monitoring(self):
        logging.info("모니터링 시작...")
        # 1. 모든 심볼 리스트 가져오기
        all_symbols = self.get_futures_usdt_symbols()
        if not all_symbols:
            logging.critical("모니터링할 심볼을 가져오지 못했습니다. 프로그램을 종료합니다.")
            return
        logging.info(f"총 {len(all_symbols)}개의 심볼을 모니터링합니다.")

        # 2. 백그라운드에서 데이터 로드 시작
        threading.Thread(target=self._load_initial_data, args=(all_symbols,), daemon=True).start()

        # 3. 웹소켓 연결 시작
        logging.info(f"{len(all_symbols)}개 전체 심볼에 대한 실시간 스트림 연결을 시작합니다.")
        chunk_size = 20
        symbol_chunks = [all_symbols[i:i + chunk_size] for i in range(0, len(all_symbols), chunk_size)]
        
        for chunk in symbol_chunks:
            streams = [f"{s.lower()}@kline_4h" for s in chunk] + [f"{s.lower()}@kline_15m" for s in chunk]
            ws_url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
            logging.info(f"Connecting to WebSocket for {len(chunk)} symbols: {ws_url}")
            ws = websocket.WebSocketApp(
                ws_url,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
                on_open=self.on_open
            )
            threading.Thread(
                target=lambda: ws.run_forever(ping_interval=60, ping_timeout=30),
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
        바이낸스 USDT-M 선물 마켓에서 거래량 기준 상위 200개 심볼 반환
        """
        try:
            # 1. 심볼 리스트 가져오기
            url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
            response = requests.get(url)
            if response.status_code != 200:
                logging.error(f"거래소 정보 조회 실패: {response.status_code} - {response.text}")
                return []
            data = response.json()
            symbols = [
                s['symbol']
                for s in data['symbols']
                if s['contractType'] == 'PERPETUAL'
                and s['quoteAsset'] == 'USDT'
                and s['status'] == 'TRADING'
            ]
            
            # 2. 거래량 정보 가져오기
            url_ticker = "https://fapi.binance.com/fapi/v1/ticker/24hr"
            response_ticker = requests.get(url_ticker)
            if response_ticker.status_code != 200:
                logging.error(f"틱커 정보 조회 실패: {response_ticker.status_code} - {response_ticker.text}")
                return symbols[:100]  # 실패 시 기본 리스트로 대체
            
            ticker_data = response_ticker.json()
            # 거래량 기준 정렬
            volume_map = {t['symbol']: float(t['quoteVolume']) for t in ticker_data if t['symbol'] in symbols}
            sorted_symbols = sorted(symbols, key=lambda x: volume_map.get(x, 0), reverse=True)
            
            # 상위 200개만 반환
            sorted_symbols = sorted_symbols[:200]
            logging.info(f"총 {len(sorted_symbols)}개의 USDT 선물 심볼을 가져왔습니다.")
            return sorted_symbols
        except Exception as e:
            logging.error(f"선물 심볼 조회 오류: {e}", exc_info=True)
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