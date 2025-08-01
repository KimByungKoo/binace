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

        self.data_length = 200  # RSI 계산을 위한 데이터 길이 (조금 더 넉넉하게)
        self.lock = threading.RLock() # 재진입 가능한 락으로 변경
        self.message_queue = queue.Queue() # 웹소켓 메시지 처리를 위한 큐
        self.message_count = 0 # 처리된 웹소켓 메시지 카운터
        self.telegram_bot = None # TelegramBot 인스턴스를 저장할 변수

        # 웹소켓 관리
        self.ws_apps = {}
        self.ws_threads = {}
        self.ws_should_run = {}
        self.ws_manager_thread = None
        
        # 데이터 저장 구조 변경: 캔들 전체 정보를 저장
        self.kline_data_4h = {} # 4시간봉 캔들 데이터

        # 실시간 RSI 값 저장
        self.current_rsi_14_4h = {}
        self.current_rsi_7_4h = {}

        # RSI 마지막 업데이트 시간 저장
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
            logger.debug(f"[{symbol}-{interval}] get_historical_data 응답: {len(data)}개 데이터 수신")
            return data # 전체 kline 데이터 반환
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
            # 데이터의 스냅샷(복사본)을 만들어 락 점유 시간을 최소화
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
        데이터의 일관성을 유지하고 UI 블로킹을 최소화하기 위해 데이터를 복사한 후 처리합니다.
        """
        with self.lock:
            # 데이터의 스냅샷을 빠르게 생성
            rsi_14_4h_copy = dict(self.current_rsi_14_4h)
            rsi_7_4h_copy = dict(self.current_rsi_7_4h)
            last_update_time_copy = dict(self.last_update_time)

        # 락을 해제한 후, 복사된 데이터를 기반으로 rsi_dict 생성
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
            logger.info("RSI 데이터가 비어있습니다. 요약 메시지를 생성할 수 없습니다.")
            return ["⚠️ RSI 데이터가 없습니다."]

        # 4시간봉 과매수/과매도 TOP10 후보를 위한 리스트 생성
        # (symbol, rsi14_4h, rsi7_4h) 형태로 저장
        rsi_4h_candidates = []
        for symbol, v in rsi_dict.items():
            if v.get('4h'):
                rsi14_4h = v['4h'].get('rsi14')
                rsi7_4h = v['4h'].get('rsi7')
                if rsi14_4h is not None or rsi7_4h is not None:
                    rsi_4h_candidates.append((symbol, rsi14_4h, rsi7_4h))

        logger.info(f"4시간봉 RSI 전체 후보 리스트: {rsi_4h_candidates}")

        # 과매수 종목 필터링 및 정렬 (RSI14 우선, 없으면 RSI7)
        rsi_4h_over = []
        for symbol, rsi14, rsi7 in rsi_4h_candidates:
            if rsi14 is not None and rsi14 >= 70:
                rsi_4h_over.append((symbol, rsi14, 'rsi14'))
            elif rsi7 is not None and rsi7 >= 70: # If rsi14 is not overbought, check rsi7
                rsi_4h_over.append((symbol, rsi7, 'rsi7'))
        rsi_4h_over = sorted(rsi_4h_over, key=lambda x: x[1], reverse=True)[:10]

        # 과매도 종목 필터링 및 정렬 (RSI14 우선, 없으면 RSI7)
        rsi_4h_under = []
        for symbol, rsi14, rsi7 in rsi_4h_candidates:
            if rsi14 is not None and rsi14 <= 30:
                rsi_4h_under.append((symbol, rsi14, 'rsi14'))
            elif rsi7 is not None and rsi7 <= 30: # If rsi14 is not oversold, check rsi7
                rsi_4h_under.append((symbol, rsi7, 'rsi7'))
        rsi_4h_under = sorted(rsi_4h_under, key=lambda x: x[1])[:10]

        logger.info(f"4시간봉 RSI 과매수 TOP10 후보: {rsi_4h_over}")
        logger.info(f"4시간봉 RSI 과매도 TOP10 후보: {rsi_4h_under}")

        if rsi_4h_over:
            msg_4h_over = "📊 <b>4시간봉 RSI(14) 과매수 TOP10 (70~100)</b>\n\n"
            for symbol, _, _ in rsi_4h_over:
                m4h = rsi_dict[symbol].get('4h', {})
                
                rsi14_4h = m4h.get('rsi14')
                rsi7_4h = m4h.get('rsi7')

                rsi14_4h_str = f"{rsi14_4h:.2f}" if isinstance(rsi14_4h, (int, float)) else 'N/A'
                rsi7_4h_str = f"{rsi7_4h:.2f}" if isinstance(rsi7_4h, (int, float)) else 'N/A'
                
                update_time_4h = last_update_time_copy.get(f"{symbol}_4h")

                update_time_4h_str = update_time_4h.strftime('%H:%M:%S') if isinstance(update_time_4h, datetime) else 'N/A'
                
                msg_4h_over += f"<b>{symbol}</b>\n" \
                              f"  - 4h: (14)-{rsi14_4h_str} | (7)-{rsi7_4h_str} <i>(업데이트: {update_time_4h_str})</i>\n\n"
            messages.append(msg_4h_over)
        
        if rsi_4h_under:
            msg_4h_under = "📊 <b>4시간봉 RSI(14) 과매도 TOP10 (0~30)</b>\n\n"
            for symbol, _, _ in rsi_4h_under:
                m4h = rsi_dict[symbol].get('4h', {})

                rsi14_4h = m4h.get('rsi14')
                rsi7_4h = m4h.get('rsi7')

                rsi14_4h_str = f"{rsi14_4h:.2f}" if isinstance(rsi14_4h, (int, float)) else 'N/A'
                rsi7_4h_str = f"{rsi7_4h:.2f}" if isinstance(rsi7_4h, (int, float)) else 'N/A'

                update_time_4h = last_update_time_copy.get(f"{symbol}_4h")

                update_time_4h_str = update_time_4h.strftime('%H:%M:%S') if isinstance(update_time_4h, datetime) else 'N/A'

                msg_4h_under += f"<b>{symbol}</b>\n" \
                               f"  - 4h: (14)-{rsi14_4h_str} | (7)-{rsi7_4h_str} <i>(업데이트: {update_time_4h_str})</i>\n\n"
            messages.append(msg_4h_under)
            
        if not messages:
            messages.append("ℹ️ 현재 과매수/과매도 상태인 4시간봉 코인이 없습니다.")

        return messages

    def on_message(self, ws, message):
        """
        웹소켓 메시지를 수신하여 처리 큐에 넣습니다.
        """
        self.message_queue.put(message)

    def on_error(self, ws, error):
        if isinstance(error, Exception):
            logger.error(f"WebSocket error on {ws.url if ws else 'Unknown WebSocket'}: {error}", exc_info=True)
        else:
            logger.error(f"WebSocket error on {ws.url if ws else 'Unknown WebSocket'}: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        url = ws.url
        logger.warning(f"WebSocket connection closed: url='{url}' code={close_status_code}, msg={close_msg}")
        with self.lock:
            self.ws_should_run[url] = False # 해당 웹소켓을 중지 상태로 표시

    def on_open(self, ws):
        logger.info(f"WebSocket connection opened for {ws.url}. Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    def manage_websockets(self):
        """
        웹소켓 연결을 관리하고, 비정상 종료 시 재연결합니다.
        """
        logger.info("웹소켓 관리자 스레드 시작...")
        while True:
            time.sleep(30) # 30초마다 확인
            
            reconnect_targets = []
            with self.lock:
                for url, ws_thread in list(self.ws_threads.items()):
                    if not ws_thread.is_alive() or not self.ws_should_run.get(url, True):
                        logger.warning(f"웹소켓 연결이 비정상적으로 종료되었습니다: {url}. 재연결 목록에 추가합니다.")
                        reconnect_targets.append(url)

            if not reconnect_targets:
                continue

            # 락 외부에서 알림 및 재연결 처리
            for url in reconnect_targets:
                self.telegram_bot.send_message(f"🔌 웹소켓 연결이 끊어져 재연결을 시도합니다: {url}")
                
                # 기존 스레드와 웹소켓 앱 정리
                with self.lock:
                    ws_thread = self.ws_threads.pop(url, None)
                    ws_app = self.ws_apps.pop(url, None)
                
                if ws_thread and ws_thread.is_alive():
                    try:
                        if ws_app:
                            ws_app.close()
                    except Exception as e:
                        logger.error(f"웹소켓 종료 중 오류 발생: {e}")
                
                # 새 웹소켓 생성 및 시작
                new_ws = websocket.WebSocketApp(
                    url,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                    on_open=self.on_open
                )
                
                new_thread = threading.Thread(target=lambda: new_ws.run_forever(ping_interval=30, ping_timeout=10), daemon=True)
                
                with self.lock:
                    self.ws_apps[url] = new_ws
                    self.ws_should_run[url] = True
                    self.ws_threads[url] = new_thread
                
                new_thread.start()
                logger.info(f"웹소켓이 성공적으로 재연결되었습니다: {url}")
                self.telegram_bot.send_message(f"✅ 웹소켓이 성공적으로 재연결되었습니다: {url}")

    def _load_initial_data(self, symbols):
        """
        백그라운드에서 초기 데이터를 로드하고, 처리 큐로 전송합니다.
        """
        logger.info("백그라운드 데이터 로더 시작...")
        if not symbols:
            logger.warning("모니터링할 심볼이 없습니다.")
            return

        total_symbols = len(symbols)
        logger.info(f"총 {total_symbols}개 심볼의 초기 데이터 로드를 시작합니다.")

        for i, symbol in enumerate(symbols):
            progress = f"[{i + 1}/{total_symbols}]"
            logger.info(f"초기 데이터 로드 진행 중: {progress} {symbol}")
            time.sleep(0.1)  # API 요청 제한 방지

            # 4시간봉 데이터 로드
            initial_data_4h = self.get_historical_data(symbol, '4h', limit=self.data_length)
            if initial_data_4h:
                # 처리 큐에 초기 데이터 메시지 전송
                msg = {
                    "type": "initial_data",
                    "symbol": symbol,
                    "interval": "4h",
                    "data": initial_data_4h
                }
                self.message_queue.put(msg)

        logger.info("모든 심볼의 초기 데이터 요청이 큐로 전송되었습니다.")
        # 초기 RSI 상태 메시지 전송은 이제 _process_message_queue에서 처리 후 수행
        if self.telegram_bot:
            self.telegram_bot.send_message("초기 데이터 로드가 완료되어 곧 첫번째 RSI 요약이 전송됩니다.")

    def _process_message_queue(self):
        """
        메시지 큐를 지속적으로 확인하고, 모든 데이터 변경을 이 스레드에서 처리합니다.
        """
        while True:
            try:
                message = self.message_queue.get()

                # 웹소켓 메시지(문자열)와 내부 메시지(딕셔너리) 구분
                if isinstance(message, str):
                    data = json.loads(message)
                    stream_data = data.get('data', {})
                    if not stream_data: continue
                    
                    symbol = stream_data.get('s', '')
                    kline = stream_data.get('k', {})
                    interval = kline.get('i', '')
                    is_closed = kline.get('x', False)

                    if not symbol or not kline: continue
                    
                    # 실시간 데이터 처리
                    self._update_kline_data(symbol, interval, kline, is_closed)

                elif isinstance(message, dict) and message.get("type") == "initial_data":
                    # 초기 데이터 처리
                    symbol = message["symbol"]
                    interval = message["interval"]
                    initial_data = message["data"]
                    
                    logger.info(f"[큐 처리] {symbol} - {interval} 초기 데이터 처리 시작")
                    
                    with self.lock:
                        if interval == '4h':
                            self.kline_data_4h[symbol] = deque(initial_data, maxlen=self.data_length)
                        
                        # 초기 RSI 계산
                        self._calculate_and_update_rsi(symbol, interval)

            except json.JSONDecodeError:
                logger.error(f"웹소켓 메시지 JSON 디코딩 실패: {message}")
            except Exception as e:
                logger.error(f"메시지 처리 중 예상치 못한 오류 발생: {e}", exc_info=True)

    def _update_kline_data(self, symbol, interval, kline, is_closed):
        """
        단일 캔들 데이터를 기반으로 상태를 업데이트합니다. (락 내부에서 호출되어야 함)
        """
        kline_data_deque = None
        with self.lock:
            if interval == '4h':
                kline_data_deque = self.kline_data_4h.get(symbol)

            if kline_data_deque is None:
                return # 아직 초기 데이터가 로드되지 않음

            new_kline = [
                kline['t'], kline['o'], kline['h'], kline['l'], kline['c'], kline['v'],
                kline['T'], kline['q'], kline['n'], kline['V'], kline['Q'], kline['B']
            ]

            if is_closed:
                kline_data_deque.append(new_kline)
            else:
                if kline_data_deque:
                    kline_data_deque[-1] = new_kline
                else:
                    kline_data_deque.append(new_kline)
            
            # RSI 계산 및 업데이트
            self._calculate_and_update_rsi(symbol, interval)

    def _calculate_and_update_rsi(self, symbol, interval):
        """
        RSI를 계산하고 관련 상태를 업데이트합니다. (락 내부에서 호출되어야 함)
        """
        kline_data_deque = None
        if interval == '4h':
            kline_data_deque = self.kline_data_4h.get(symbol)

        if not kline_data_deque or len(kline_data_deque) < 14:
            return

        close_prices = [float(k[4]) for k in kline_data_deque]
        rsi_14 = calculate_rsi_binance(close_prices, period=14)
        rsi_7 = calculate_rsi_binance(close_prices, period=7)

        if interval == '4h':
            self.current_rsi_14_4h[symbol] = rsi_14
            self.current_rsi_7_4h[symbol] = rsi_7
            self.last_update_time[f"{symbol}_4h"] = datetime.now()
            
            # 알림 상태 업데이트
            if rsi_14 >= self.rsi_overbought: self.alerted_overbought_14_4h.add(symbol)
            else: self.alerted_overbought_14_4h.discard(symbol)
            if rsi_14 <= self.rsi_oversold: self.alerted_oversold_14_4h.add(symbol)
            else: self.alerted_oversold_14_4h.discard(symbol)

    def start_monitoring(self):
        if not self.telegram_bot:
            self.telegram_bot = TelegramBot(self)
            
        logging.info("모니터링 시작...")
        self.telegram_bot.send_message("🔔 RSI 모니터링을 시작합니다.")

        # 0. 메시지 처리 스레드 시작
        threading.Thread(target=self._process_message_queue, daemon=True).start()

        # 1. 모든 심볼 리스트 가져오기
        all_symbols = self.get_futures_usdt_symbols()
        if not all_symbols:
            logging.critical("모니터링할 심볼을 가져오지 못했습니다. 프로그램을 종료합니다.")
            self.telegram_bot.send_message("❌ 모니터링할 심볼을 가져오지 못해 프로그램을 종료합니다.")
            return
        logging.info(f"총 {len(all_symbols)}개의 심볼을 모니터링합니다.")
        self.telegram_bot.send_message(f"✅ 총 {len(all_symbols)}개 심볼에 대한 모니터링을 시작합니다.")

        # 2. 백그라운드에서 데이터 로드 시작
        threading.Thread(target=self._load_initial_data, args=(all_symbols,), daemon=True).start()

        # 3. 웹소켓 연결 시작
        logging.info(f"{len(all_symbols)}개 전체 심볼에 대한 실시간 스트림 연결을 시작합니다.")
        chunk_size = 25
        symbol_chunks = [all_symbols[i:i + chunk_size] for i in range(0, len(all_symbols), chunk_size)]
        
        with self.lock:
            for chunk in symbol_chunks:
                streams = [f"{s.lower()}@kline_4h" for s in chunk]
                ws_url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
                logging.info(f"Connecting to WebSocket for {len(chunk)} symbols: {ws_url}")
                
                ws = websocket.WebSocketApp(
                    ws_url,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                    on_open=self.on_open
                )
                self.ws_apps[ws_url] = ws
                self.ws_should_run[ws_url] = True
                
                wst = threading.Thread(target=lambda: ws.run_forever(ping_interval=30, ping_timeout=10), daemon=True)
                self.ws_threads[ws_url] = wst
                wst.start()

        # 4. 웹소켓 관리자 스레드 시작
        if not self.ws_manager_thread or not self.ws_manager_thread.is_alive():
            self.ws_manager_thread = threading.Thread(target=self.manage_websockets, daemon=True)
            self.ws_manager_thread.start()
            
        # 메인 스레드가 종료되지 않도록 유지 및 상태 로깅
        while True:
            time.sleep(60)
            active_threads = threading.active_count()
            queue_size = self.message_queue.qsize()
            logger.info(f"[상태] 활성 스레드: {active_threads}개, 메시지 큐 크기: {queue_size}")

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