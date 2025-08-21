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
        self.ws_rsi_threshold = 80 # 웹소켓 동적 관리를 위한 RSI 임계값
        self.data_length = 200

        # 스레딩 및 동시성 관리
        self.lock = threading.RLock()
        self.message_queue = queue.Queue()
        self.telegram_bot = None

        # 웹소켓 관리 (단일 웹소켓으로 단순화)
        self.ws_app = None
        self.ws_thread = None
        self.ws_should_run = True

        # 데이터 저장 구조 (4시간봉만 사용)
        self.kline_data_4h = {}
        self.current_rsi_14_4h = {}
        self.current_rsi_7_4h = {}
        self.last_update_time = {}

        # 알림 상태 관리
        self.alerted_overbought_14_4h = set()
        self.alerted_oversold_14_4h = set()
        
        # 자동매매 관련 설정 (유지)
        self.investment_amount = 10
        self.leverage = 10
        self.position_size_usdt = self.investment_amount * self.leverage
        self.active_positions = {}
        
        self.futures_usdt_symbols = [] # 동적으로 업데이트되므로 초기에는 비워둠
        self.auto_trading = False
        
        # API 관련 설정
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.api_secret = os.getenv('BINANCE_API_SECRET')
        self.base_url = 'https://fapi.binance.com' # 선물 거래로 고정
        self.testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'
        
        if self.testnet:
            self.base_url = 'https://testnet.binance.vision'
            logger.info("🔧 테스트넷 모드로 실행 중")
        else:
            logger.info("🚀 실제 거래 모드로 실행 중")
        
        if not self.api_key or not self.api_secret:
            logger.warning("⚠️ 경고: 바이낸스 API 키가 설정되지 않았습니다. API 관련 기능이 제한됩니다.")
            self.simulation_mode = True
        else:
            self.simulation_mode = False
            logger.info("✅ 바이낸스 API 키가 설정되었습니다.")

    def get_historical_data(self, symbol, interval, limit=None, startTime=None):
        """
        Binance API를 통해 과거 KLINE 데이터를 가져옵니다.
        """
        try:
            url = "https://fapi.binance.com/fapi/v1/klines"
            params = {'symbol': symbol, 'interval': interval}
            if limit: params['limit'] = limit
            if startTime: params['startTime'] = startTime

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"[{symbol}-{interval}] 데이터 요청 중 오류 발생: {e}")
            return []

    def get_current_rsi(self):
        """
        현재 모든 심볼의 4시간봉 RSI 값을 반환합니다. (단순화된 버전)
        """
        print("\n=== 현재 RSI 상태 ===")
        with self.lock:
            rsi_14_4h_copy = dict(self.current_rsi_14_4h)
            rsi_7_4h_copy = dict(self.current_rsi_7_4h)

        for symbol, rsi14 in rsi_14_4h_copy.items():
            rsi7 = rsi_7_4h_copy.get(symbol)
            if rsi14 is not None and rsi7 is not None:
                print(f"{symbol} 4h: RSI(14)={rsi14:.2f}, RSI(7)={rsi7:.2f}")
        print("===================\n")
        return rsi_14_4h_copy

    def get_rsi_summary_messages(self):
        """
        4시간봉 RSI 요약 메시지들을 생성하여 반환합니다. (단순화된 버전)
        """
        with self.lock:
            rsi_14_4h_copy = dict(self.current_rsi_14_4h)
            rsi_7_4h_copy = dict(self.current_rsi_7_4h)
            last_update_time_copy = dict(self.last_update_time)

        generation_time_str = datetime.now().strftime('%H:%M:%S')
        if not rsi_14_4h_copy:
            return [f"⚠️ RSI 데이터가 없습니다. (생성: {generation_time_str})"]

        candidates = []
        for symbol, rsi14 in rsi_14_4h_copy.items():
            rsi7 = rsi_7_4h_copy.get(symbol)
            if rsi14 is not None and rsi7 is not None:
                candidates.append((symbol, rsi14, rsi7))

        overbought = sorted([c for c in candidates if c[1] >= self.rsi_overbought or c[2] >= self.rsi_overbought], key=lambda x: x[1], reverse=True)[:10]
        oversold = sorted([c for c in candidates if c[1] <= self.rsi_oversold or c[2] <= self.rsi_oversold], key=lambda x: x[1])[:10]
        
        messages = []
        if overbought:
            msg = f"📊 <b>4시간봉 RSI 과매수 TOP10 (생성: {generation_time_str})</b>\n\n"
            for symbol, rsi14, rsi7 in overbought:
                update_time = last_update_time_copy.get(f"{symbol}_4h", "N/A")
                update_time_str = update_time.strftime('%H:%M:%S') if isinstance(update_time, datetime) else "N/A"
                msg += f"<b>{symbol}</b>: (14)-{rsi14:.2f} | (7)-{rsi7:.2f} <i>(업데이트: {update_time_str})</i>\n"
            messages.append(msg)

        if oversold:
            msg = f"📊 <b>4시간봉 RSI 과매도 TOP10 (생성: {generation_time_str})</b>\n\n"
            for symbol, rsi14, rsi7 in oversold:
                update_time = last_update_time_copy.get(f"{symbol}_4h", "N/A")
                update_time_str = update_time.strftime('%H:%M:%S') if isinstance(update_time, datetime) else "N/A"
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

    def _load_initial_data(self, symbols):
        logger.info(f"총 {len(symbols)}개 심볼의 초기 데이터 로드를 시작합니다.")
        for i, symbol in enumerate(symbols):
            logger.info(f"초기 데이터 로드 진행 중: [{i + 1}/{len(symbols)}] {symbol}")
            time.sleep(0.1) # API 요청 제한 방지
            initial_data = self.get_historical_data(symbol, '4h', limit=self.data_length)
            if initial_data:
                with self.lock:
                    self.kline_data_4h[symbol] = deque(initial_data, maxlen=self.data_length)
                    self._calculate_and_update_rsi(symbol)
        logger.info("초기 데이터 로드가 완료되었습니다.")
        if self.telegram_bot:
            self.telegram_bot.send_message("초기 데이터 로드가 완료되었습니다. 곧 첫 RSI 요약이 전송됩니다.")

    def _process_message_queue(self):
        logger.info("메시지 처리 스레드 시작...")
        last_summary_time = 0
        initial_summary_sent = False

        while True:
            try:
                message = self.message_queue.get()
                data = json.loads(message)['data']
                symbol = data['s']
                kline = data['k']
                
                self._update_kline_data(symbol, kline)
                
                # 첫 데이터 로드 완료 후 또는 30분마다 요약 전송
                is_ready_for_summary = not initial_summary_sent and self.message_queue.empty() and len(self.current_rsi_14_4h) > 0
                is_time_for_summary = initial_summary_sent and (time.time() - last_summary_time > 1800)

                if is_ready_for_summary or is_time_for_summary:
                    logger.info("RSI 요약을 전송합니다.")
                    summary_messages = self.get_rsi_summary_messages()
                    for msg in summary_messages:
                        self.telegram_bot.send_message(msg)
                    last_summary_time = time.time()
                    if not initial_summary_sent: initial_summary_sent = True

            except Exception as e:
                logger.error(f"메시지 처리 중 오류 발생: {e}", exc_info=True)

    def _update_kline_data(self, symbol, kline):
        with self.lock:
            kline_data_deque = self.kline_data_4h.get(symbol)
            if kline_data_deque is None: return

            new_kline = [kline['t'], kline['o'], kline['h'], kline['l'], kline['c'], kline['v'], kline['T'], kline['q'], kline['n'], kline['V'], kline['Q'], kline['B']]
            
            if kline['x']: # is_closed
                kline_data_deque.append(new_kline)
            elif kline_data_deque:
                kline_data_deque[-1] = new_kline
            else:
                kline_data_deque.append(new_kline)
            
            self._calculate_and_update_rsi(symbol)

    def _calculate_and_update_rsi(self, symbol):
        kline_data_deque = self.kline_data_4h.get(symbol)
        if not kline_data_deque or len(kline_data_deque) < 14: return

        close_prices = [float(k[4]) for k in kline_data_deque]
        self.current_rsi_14_4h[symbol] = calculate_rsi_binance(close_prices, period=14)
        self.current_rsi_7_4h[symbol] = calculate_rsi_binance(close_prices, period=7)
        self.last_update_time[f"{symbol}_4h"] = datetime.now()

    def _get_high_rsi_symbols(self):
        """
        4시간봉 RSI가 ws_rsi_threshold를 초과하는 모든 USDT-M 선물 심볼을 찾아 반환합니다.
        """
        logger.info(f"RSI > {self.ws_rsi_threshold} 조건에 맞는 심볼 스캔 시작...")
        try:
            url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            all_symbols = [s['symbol'] for s in data['symbols'] if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']
            logger.info(f"총 {len(all_symbols)}개의 전체 선물 심볼을 확인합니다.")

            high_rsi_symbols = set()
            for i, symbol in enumerate(all_symbols):
                logger.debug(f"RSI 스캔 진행 중: [{i + 1}/{len(all_symbols)}] {symbol}")
                hist_data = self.get_historical_data(symbol, '4h', limit=200)
                if hist_data and len(hist_data) >= 14:
                    closes = [float(k[4]) for k in hist_data]
                    rsi14 = calculate_rsi_binance(closes, period=14)
                    if rsi14 is not None and rsi14 > self.ws_rsi_threshold:
                        high_rsi_symbols.add(symbol)
                        logger.info(f"✅ 조건 충족 심볼 발견: {symbol} (4h RSI: {rsi14:.2f})")
                time.sleep(0.1)

            logger.info(f"RSI > {self.ws_rsi_threshold} 스캔 완료. 총 {len(high_rsi_symbols)}개의 심볼 발견: {high_rsi_symbols}")
            return high_rsi_symbols
        except Exception as e:
            logger.error(f"상위 RSI 심볼 조회 중 오류 발생: {e}", exc_info=True)
            return set()

    def start_monitoring(self):
        """
        주기적으로 RSI 조건을 확인하여 웹소켓 연결을 동적으로 관리합니다.
        """
        if not self.telegram_bot:
            self.telegram_bot = TelegramBot(self)

        logger.info("RSI 동적 모니터링 시작")
        self.telegram_bot.send_message("🔔 RSI 동적 모니터링을 시작합니다.")
        threading.Thread(target=self._process_message_queue, daemon=True).start()

        while True:
            try:
                target_symbols = self._get_high_rsi_symbols()
                self.futures_usdt_symbols = list(target_symbols)

                with self.lock:
                    current_symbols = set(self.kline_data_4h.keys())
                    needs_restart = (target_symbols != current_symbols)

                if needs_restart:
                    logger.info(f"모니터링 목록 변경 감지. 웹소켓을 재시작합니다. 새 목록: {target_symbols}")
                    self.telegram_bot.send_message(f"🔄 모니터링 목록 업데이트: {len(target_symbols)}개 감시 시작.\n{', '.join(target_symbols) if target_symbols else '없음'}")

                    if self.ws_app:
                        self.ws_should_run = False
                        self.ws_app.close()
                        if self.ws_thread and self.ws_thread.is_alive(): self.ws_thread.join(timeout=5)
                        logger.info("기존 웹소켓 연결이 종료되었습니다.")

                    with self.lock:
                        self.kline_data_4h.clear()
                        self.current_rsi_14_4h.clear()
                        self.current_rsi_7_4h.clear()
                        self.last_update_time.clear()

                    if target_symbols:
                        self._load_initial_data(list(target_symbols))
                        self._connect_websocket(list(target_symbols))
                    else:
                        logger.info("모니터링할 심볼이 없어 대기합니다.")

                elif self.ws_thread and not self.ws_thread.is_alive() and target_symbols:
                     logger.warning("웹소켓 연결이 끊어져 재연결을 시도합니다.")
                     self.telegram_bot.send_message("🔌 웹소켓 연결이 끊어져 재연결을 시도합니다.")
                     self._connect_websocket(list(target_symbols))
                else:
                    logger.info("모니터링 목록에 변경사항이 없습니다.")

                logger.info("다음 스캔까지 1시간 대기합니다.")
                time.sleep(3600)
            except Exception as e:
                logger.critical(f"모니터링 메인 루프에서 심각한 오류 발생: {e}", exc_info=True)
                self.telegram_bot.send_message(f"🚨 모니터링 시스템에 심각한 오류가 발생했습니다. 5분 후 재시도합니다.")
                time.sleep(300)

    def _generate_signature(self, params):
        """
        바이낸스 API 서명을 생성합니다.
        """
        query_string = urllib.parse.urlencode(params)
        return hmac.new(self.api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    
    def _make_request(self, method, endpoint, params=None, signed=False):
        """
        바이낸스 API 요청을 보냅니다.
        """
        url = f"{self.base_url}{endpoint}"
        headers = {'X-MBX-APIKEY': self.api_key}
        if params is None: params = {}
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._generate_signature(params)
        
        try:
            if method == 'GET': response = requests.get(url, params=params, headers=headers)
            elif method == 'POST': response = requests.post(url, data=params, headers=headers)
            
            if response.status_code == 200: return response.json()
            else:
                logger.error(f"API 요청 실패: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"API 요청 중 오류: {e}")
            return None
        
    def get_ema_321_proximity(self, top_n=10):
        """
        4시간봉 321EMA와 현재가 이격률이 가장 작은 USDT-M 선물 코인 TOP N 반환
        """
        symbols = self.futures_usdt_symbols
        if not symbols:
            logger.warning("EMA 근접도 계산을 위한 심볼 목록이 비어있습니다.")
            return []
        results = []
        for symbol in symbols:
            try:
                data = self.get_historical_data(symbol, '4h', limit=350)
                if not data or len(data) < 321: continue
                
                closes = [float(c[4]) for c in data]
                ema = self.calculate_ema(closes, 321)[-1]
                current_price = closes[-1]
                diff = abs(current_price - ema) / ema * 100
                results.append((symbol, current_price, ema, diff))
            except Exception as e:
                logger.error(f"{symbol} 321EMA 계산 오류: {e}")
        
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