import websocket
import json
import threading
import time
from collections import deque
import queue

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
        self.data_length = 200

        # 스레딩 및 동시성 관리
        self.lock = threading.RLock()
        self.message_queue = queue.Queue()
        self.telegram_bot = None

        # 웹소켓 관리
        self.ws_app = None
        self.ws_thread = None
        self.ws_should_run = True
        self.ws_manager_thread = None

        # 데이터 저장 구조
        self.kline_data_4h = {}
        self.current_rsi_14_4h = {}
        self.current_rsi_7_4h = {}
        self.last_update_time = {}

        # 알림 상태 관리
        self.alerted_overbought_14_4h = set()
        self.alerted_oversold_14_4h = set()
        self.alerted_overbought_7_4h = set()
        self.alerted_oversold_7_4h = set()

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

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"[{symbol}-{interval}] get_historical_data 응답: {len(data)}개 데이터 수신")
            return data
        except requests.exceptions.Timeout:
            logger.error(f"[{symbol}-{interval}] 데이터 요청 타임아웃 발생.")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"[{symbol}-{interval}] 데이터 요청 중 네트워크 오류 발생: {e}")
            return []
        except json.JSONDecodeError:
            logger.error(f"[{symbol}-{interval}] API 응답 JSON 디코딩 실패: {response.text}")
            return []
        except Exception as e:
            logger.error(f"[{symbol}-{interval}] get_historical_data 함수에서 예상치 못한 오류 발생: {e}", exc_info=True)
            return []

    def get_current_rsi(self):
        """
        현재 모든 심볼의 4시간봉 RSI 값을 반환합니다. (스레드 안전 방식)
        """
        print("\n=== 현재 RSI 상태 ===")
        with self.lock:
            rsi_14_4h_copy = dict(self.current_rsi_14_4h)
            rsi_7_4h_copy = dict(self.current_rsi_7_4h)

        result = {}
        all_symbols = set(rsi_14_4h_copy.keys())

        for symbol in all_symbols:
            result[symbol] = {}
            rsi14_4h = rsi_14_4h_copy.get(symbol)
            rsi7_4h = rsi_7_4h_copy.get(symbol)
            if rsi14_4h is not None and rsi7_4h is not None:
                result[symbol]['4h'] = {'rsi14': rsi14_4h, 'rsi7': rsi7_4h}
                print(f"{symbol} 4h: RSI(14)={rsi14_4h:.2f}, RSI(7)={rsi7_4h:.2f}")

        print("===================\n")
        return result

    def get_rsi_summary_messages(self):
        """
        4시간봉 RSI 요약 메시지들을 생성하여 반환합니다.
        """
        with self.lock:
            rsi_14_4h_copy = dict(self.current_rsi_14_4h)
            rsi_7_4h_copy = dict(self.current_rsi_7_4h)
            last_update_time_copy = dict(self.last_update_time)

        # 데이터의 스냅샷을 기준으로 메시지 생성 시간을 기록
        generation_time_str = datetime.now().strftime('%H:%M:%S')

        rsi_dict = {}
        all_symbols = set(rsi_14_4h_copy.keys())
        for symbol in all_symbols:
            rsi_dict[symbol] = {}
            if symbol in rsi_14_4h_copy:
                rsi_dict[symbol]['4h'] = {
                    'rsi14': rsi_14_4h_copy.get(symbol),
                    'rsi7': rsi_7_4h_copy.get(symbol)
                }
        
        messages = []
        if not rsi_dict:
            return [f"⚠️ RSI 데이터가 없습니다. (생성: {generation_time_str})"]

        rsi_4h_candidates = []
        for symbol, v in rsi_dict.items():
            if v.get('4h'):
                rsi14_4h = v['4h'].get('rsi14')
                rsi7_4h = v['4h'].get('rsi7')
                if rsi14_4h is not None and rsi7_4h is not None:
                    rsi_4h_candidates.append((symbol, rsi14_4h, rsi7_4h))

        # RSI 값을 기준으로 정렬 (None 값 예외 처리)
        rsi_4h_over = sorted([c for c in rsi_4h_candidates if (c[1] is not None and c[1] >= 70) or (c[2] is not None and c[2] >= 70)], key=lambda x: (x[1] is None, x[1]), reverse=True)[:10]
        rsi_4h_under = sorted([c for c in rsi_4h_candidates if (c[1] is not None and c[1] <= 30) or (c[2] is not None and c[2] <= 30)], key=lambda x: (x[1] is None, x[1]))[:10]

        if rsi_4h_over:
            msg = f"📊 <b>4시간봉 RSI 과매수 TOP10 (생성: {generation_time_str})</b>\n\n"
            for symbol, rsi14, rsi7 in rsi_4h_over:
                update_time_str = last_update_time_copy.get(f"{symbol}_4h", datetime.now()).strftime('%H:%M:%S')
                msg += f"<b>{symbol}</b>: (14)-{rsi14:.2f} | (7)-{rsi7:.2f} <i>(업데이트: {update_time_str})</i>\n"
            messages.append(msg)

        if rsi_4h_under:
            msg = f"📊 <b>4시간봉 RSI 과매도 TOP10 (생성: {generation_time_str})</b>\n\n"
            for symbol, rsi14, rsi7 in rsi_4h_under:
                update_time_str = last_update_time_copy.get(f"{symbol}_4h", datetime.now()).strftime('%H:%M:%S')
                msg += f"<b>{symbol}</b>: (14)-{rsi14:.2f} | (7)-{rsi7:.2f} <i>(업데이트: {update_time_str})</i>\n"
            messages.append(msg)

        if not messages:
            messages.append(f"ℹ️ 현재 과매수/과매도 상태인 4시간봉 코인이 없습니다. (생성: {generation_time_str})")

        return messages

    def on_message(self, ws, message):
        self.message_queue.put(message)

    def on_error(self, ws, error):
        logger.error(f"웹소켓 오류 발생: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        logger.warning(f"웹소켓 연결이 닫혔습니다: code={close_status_code}, msg={close_msg}")
        self.ws_should_run = False

    def on_open(self, ws):
        logger.info("웹소켓 연결이 열렸습니다.")
        self.ws_should_run = True

    def _connect_websocket(self, symbols):
        logger.info(f"{len(symbols)}개 심볼에 대한 웹소켓 연결을 시작합니다.")
        streams = [f"{s.lower()}@kline_4h" for s in symbols]
        ws_url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
        
        self.ws_app = websocket.WebSocketApp(ws_url,
                                             on_message=self.on_message,
                                             on_error=self.on_error,
                                             on_close=self.on_close,
                                             on_open=self.on_open)
        
        self.ws_thread = threading.Thread(target=lambda: self.ws_app.run_forever(ping_interval=30, ping_timeout=10), daemon=True)
        self.ws_thread.start()
        logger.info("웹소켓 스레드가 시작되었습니다.")

    def manage_websocket_connection(self, symbols):
        """웹소켓 연결을 관리하고 필요시 재연결합니다."""
        while True:
            if not self.ws_thread or not self.ws_thread.is_alive() or not self.ws_should_run:
                logger.warning("웹소켓 연결이 끊어졌습니다. 재연결을 시도합니다...")
                if self.telegram_bot:
                    self.telegram_bot.send_message("🔌 웹소켓 연결이 끊어져 재연결을 시도합니다.")
                
                if self.ws_app:
                    try: self.ws_app.close()
                    except Exception as e: logger.error(f"기존 웹소켓 종료 중 오류: {e}")
                
                self._connect_websocket(symbols)
                if self.telegram_bot:
                    self.telegram_bot.send_message("✅ 웹소켓이 성공적으로 재연결되었습니다.")
            time.sleep(30) # 30초마다 연결 상태 확인

    def _load_initial_data(self, symbols):
        logger.info(f"총 {len(symbols)}개 심볼의 초기 데이터 로드를 시작합니다.")
        for i, symbol in enumerate(symbols):
            logger.info(f"초기 데이터 로드 진행 중: [{i + 1}/{len(symbols)}] {symbol}")
            time.sleep(0.1) # API 요청 제한 방지
            initial_data = self.get_historical_data(symbol, '4h', limit=self.data_length)
            if initial_data:
                msg = {"type": "initial_data", "symbol": symbol, "data": initial_data}
                self.message_queue.put(msg)
        logger.info("초기 데이터 로드가 완료되어 큐로 전송되었습니다.")
        if self.telegram_bot:
            self.telegram_bot.send_message("초기 데이터 로드가 완료되었습니다. 곧 첫 RSI 요약이 전송됩니다.")

    def _process_message_queue(self):
        logger.info("메시지 처리 스레드 시작...")
        initial_summary_sent = False
        last_summary_time = 0

        while True:
            try:
                message = self.message_queue.get()
                
                if isinstance(message, str):
                    data = json.loads(message)['data']
                    symbol = data['s']
                    kline = data['k']
                    interval = kline.get('i', '')
                    logger.info(f"[큐 처리] {symbol} - {interval} 실시간 데이터 처리") # 로그 추가
                    self._update_kline_data(symbol, interval, kline, kline['x'])
                
                elif isinstance(message, dict) and message.get("type") == "initial_data":
                    symbol = message["symbol"]
                    logger.info(f"[큐] {symbol} 초기 데이터 처리")
                    with self.lock:
                        self.kline_data_4h[symbol] = deque(message["data"], maxlen=self.data_length)
                        self._calculate_and_update_rsi(symbol, '4h')
                
                # 모든 초기 데이터가 로드된 후 첫 요약 메시지 전송
                if not initial_summary_sent and self.message_queue.empty():
                    if len(self.current_rsi_14_4h) >= len(self.futures_usdt_symbols) * 0.9:
                        logger.info("초기 데이터 처리 완료. 첫번째 RSI 요약을 전송합니다.")
                        summary_messages = self.get_rsi_summary_messages()
                        for msg in summary_messages:
                            self.telegram_bot.send_message(msg)
                        initial_summary_sent = True
                        last_summary_time = time.time()

                # 30분마다 정기적으로 요약 메시지 전송
                if initial_summary_sent and (time.time() - last_summary_time > 1800):
                    logger.info("정기 RSI 요약을 전송합니다.")
                    summary_messages = self.get_rsi_summary_messages()
                    for msg in summary_messages:
                        self.telegram_bot.send_message(msg)
                    last_summary_time = time.time()

            except json.JSONDecodeError:
                logger.error(f"JSON 디코딩 실패: {message}")
            except Exception as e:
                logger.error(f"메시지 처리 중 오류 발생: {e}", exc_info=True)

    def _update_kline_data(self, symbol, interval, kline, is_closed):
        with self.lock:
            kline_data_deque = self.kline_data_4h.get(symbol)
            if kline_data_deque is None: return

            new_kline = [kline['t'], kline['o'], kline['h'], kline['l'], kline['c'], kline['v'], kline['T'], kline['q'], kline['n'], kline['V'], kline['Q'], kline['B']]

            if is_closed:
                kline_data_deque.append(new_kline)
            elif kline_data_deque:
                kline_data_deque[-1] = new_kline
            else:
                kline_data_deque.append(new_kline)
            
            self._calculate_and_update_rsi(symbol, interval)

    def _calculate_and_update_rsi(self, symbol, interval):
        kline_data_deque = self.kline_data_4h.get(symbol)
        if not kline_data_deque or len(kline_data_deque) < 14: return

        close_prices = [float(k[4]) for k in kline_data_deque]
        self.current_rsi_14_4h[symbol] = calculate_rsi_binance(close_prices, period=14)
        self.current_rsi_7_4h[symbol] = calculate_rsi_binance(close_prices, period=7)
        self.last_update_time[f"{symbol}_4h"] = datetime.now()

    def start_monitoring(self):
        if not self.telegram_bot:
            self.telegram_bot = TelegramBot(self)
        
        logger.info("RSI 모니터링 시작 (실시간 웹소켓 방식)")
        self.telegram_bot.send_message("🔔 RSI 모니터링을 시작합니다. (실시간)")

        all_symbols = self.get_futures_usdt_symbols()
        if not all_symbols:
            logger.critical("모니터링할 심볼을 가져오지 못했습니다.")
            return

        # 1. 메시지 처리 스레드 시작
        threading.Thread(target=self._process_message_queue, daemon=True).start()

        # 2. 초기 데이터 로드 스레드 시작
        threading.Thread(target=self._load_initial_data, args=(all_symbols,), daemon=True).start()

        # 3. 웹소켓 연결 및 관리 스레드 시작
        self._connect_websocket(all_symbols)
        self.ws_manager_thread = threading.Thread(target=self.manage_websocket_connection, args=(all_symbols,), daemon=True)
        self.ws_manager_thread.start()

        # 메인 스레드는 대기
        while True:
            time.sleep(60)
            logger.info(f"[상태] 활성 스레드: {threading.active_count()}개, 메시지 큐 크기: {self.message_queue.qsize()}")



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
        바이낸스 USDT-M 선물 마켓에서 24시간 가격 변화율 기준 상위 100개 심볼 반환
        """
        try:
            # 1. 심볼 리스트 가져오기
            url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
            response = requests.get(url)
            if response.status_code != 200:
                logger.error(f"거래소 정보 조회 실패: {response.status_code} - {response.text}")
                return []
            data = response.json()
            symbols = [
                s['symbol']
                for s in data['symbols']
                if s['contractType'] == 'PERPETUAL'
                and s['quoteAsset'] == 'USDT'
                and s['status'] == 'TRADING'
            ]
            
            # 2. 24시간 Ticker 정보 가져오기
            url_ticker = "https://fapi.binance.com/fapi/v1/ticker/24hr"
            response_ticker = requests.get(url_ticker)
            if response_ticker.status_code != 200:
                logger.error(f"틱커 정보 조회 실패: {response_ticker.status_code} - {response_ticker.text}")
                return [] # 실패 시 빈 리스트 반환

            ticker_data = response_ticker.json()
            
            # 가격 변화율 기준 정렬
            change_rate_map = {t['symbol']: float(t['priceChangePercent']) for t in ticker_data if t['symbol'] in symbols}
            sorted_symbols = sorted(symbols, key=lambda x: change_rate_map.get(x, -9999), reverse=True)

            # 상위 100개만 반환
            top_100_symbols = sorted_symbols[:100]
            logger.info(f"총 {len(top_100_symbols)}개의 USDT 선물 심볼을 가져왔습니다. (24시간 변화율 상위)")
            return top_100_symbols
        except Exception as e:
            logger.error(f"선물 심볼 조회 오류: {e}", exc_info=True)
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