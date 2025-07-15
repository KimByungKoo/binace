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
        # 12345
        
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
        self.price_data_1m = {}
        self.price_data_15m = {}
        self.price_data_4h = {}  # 4시간봉 가격 데이터
        self.volume_data_1m = {}
        self.volume_data_15m = {}
        self.volume_data_4h = {}  # 4시간봉 거래량 데이터
        self.current_rsi_14_1m = {}
        self.current_rsi_7_1m = {}
        self.current_rsi_14_15m = {}
        self.current_rsi_7_15m = {}
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
        self.alerted_strong_14 = set()  # 1m, 15m 동시 만족 강한 알림
        self.alerted_strong_7 = set()
        
        
        # SL/TP 관련 설정
        self.investment_amount = 10  # 투자금액 (USDT)
        self.leverage = 10  # 레버리지 배수
        self.position_size_usdt = self.investment_amount * self.leverage  # 실제 포지션 크기 (100 USDT)
        self.roi_threshold = 0.05  # ROI 5% 기준
        self.stop_loss_percent = 0.02  # 손절 2%
        self.take_profit_percent = 0.05  # 익절 5%
        self.active_positions = {}  # 활성 포지션 관리
        self.position_history = []  # 거래 이력
        
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
        심볼의 초기 데이터를 설정합니다.
        """
        print(f"\n{symbol} 초기 데이터 로드 시작...")
        prices_1m, volumes_1m = self.get_historical_data(symbol, interval='1m', limit=self.data_length)
        prices_15m, volumes_15m = self.get_historical_data(symbol, interval='15m', limit=self.data_length)
        prices_4h, volumes_4h = self.get_historical_data(symbol, interval='4h', limit=self.data_length)
        self.price_data_1m[symbol] = deque(prices_1m, maxlen=self.data_length)
        self.price_data_15m[symbol] = deque(prices_15m, maxlen=self.data_length)
        self.price_data_4h[symbol] = deque(prices_4h, maxlen=self.data_length)
        self.volume_data_1m[symbol] = deque(volumes_1m, maxlen=self.data_length)
        self.volume_data_15m[symbol] = deque(volumes_15m, maxlen=self.data_length)
        self.volume_data_4h[symbol] = deque(volumes_4h, maxlen=self.data_length)
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
        if len(prices_4h) >= self.data_length:
            rsi_14_4h = calculate_rsi_binance(list(prices_4h), period=14)
            rsi_7_4h = calculate_rsi_binance(list(prices_4h), period=7)
            self.current_rsi_14_4h[symbol] = rsi_14_4h
            self.current_rsi_7_4h[symbol] = rsi_7_4h
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
        
    def check_buy_conditions(self, symbol, price, rsi_14_1m, rsi_7_1m, rsi_14_15m, rsi_7_15m, rsi_14_4h, rsi_7_4h):
        conditions_met = []
        # 4시간봉 RSI 과매도 조건
        if self.buy_conditions.get('rsi_4h_oversold', True):
            if (rsi_14_4h is not None and rsi_14_4h <= self.rsi_oversold) or \
               (rsi_7_4h is not None and rsi_7_4h <= self.rsi_oversold):
                conditions_met.append('4시간봉 RSI 과매도')
        # 15분봉 RSI 과매도 조건
        if self.buy_conditions['rsi_15m_oversold']:
            if (rsi_14_15m is not None and rsi_14_15m <= self.rsi_oversold) or \
               (rsi_7_15m is not None and rsi_7_15m <= self.rsi_oversold):
                conditions_met.append('15분봉 RSI 과매도')
        # 1분봉 RSI 과매도 조건
        if self.buy_conditions['rsi_1m_oversold']:
            if (rsi_14_1m is not None and rsi_14_1m <= self.rsi_oversold) or \
               (rsi_7_1m is not None and rsi_7_1m <= self.rsi_oversold):
                conditions_met.append('1분봉 RSI 과매도')
        # 거래량 스파이크 조건 (필수)
        if self.buy_conditions['volume_spike']:
            volume_spike_15m, volume_ratio_15m = self.check_volume_spike(symbol, '15m')
            volume_spike_1m, volume_ratio_1m = self.check_volume_spike(symbol, '1m')
            if volume_spike_15m or volume_spike_1m:
                max_ratio = max(volume_ratio_15m, volume_ratio_1m)
            else:
                return False, []
        # 가격 하락 조건 (최근 10개 캔들 기준)
        if self.buy_conditions['price_drop'] > 0:
            if len(self.price_data_15m.get(symbol, [])) >= 10:
                recent_prices = list(self.price_data_15m[symbol])[-10:]
                price_drop = (recent_prices[0] - recent_prices[-1]) / recent_prices[0]
        return len(conditions_met) >= 2, conditions_met
    
    def calculate_position_size(self, price):
        """
        투자금액 대비 ROI 5% 기준으로 매수 수량을 계산합니다.
        """
        # 실제 잔고 확인
        available_balance = self.get_balance('USDT')
        if available_balance < self.min_order_amount:
            return 0, f"잔고 부족: {available_balance:.2f} USDT"
        
        # 투자 가능 금액 계산 (최대 포지션 수 고려)
        max_investment = min(self.investment_amount, available_balance / self.max_positions)
        
        # 레버리지를 고려한 실제 포지션 크기
        position_value = max_investment * self.leverage
        
        # ROI 기준으로 목표 수익 계산
        target_profit_usdt = position_value * self.roi_threshold
        
        # 레버리지를 고려한 SL/TP 계산
        # 예: 100$ 투자, 10배 레버리지 = 1000$ 포지션
        # 5% ROI = 50$ 수익 (1000$ * 5%)
        # 가격 변동 0.5% = 50$ 수익 (1000$ * 0.5%)
        price_change_for_target = self.roi_threshold / self.leverage
        
        # 매수 수량 계산
        position_size = position_value / price
        
        # 최소 주문 금액 확인
        if position_size * price < self.min_order_amount:
            position_size = self.min_order_amount / price
        
        return position_size, "계산 완료"
    
    def calculate_sl_tp_prices(self, entry_price, position_value, position_type='LONG'):
        """
        ROI 기준으로 SL/TP 가격을 계산합니다. (롱/숏 구분)
        """
        price_change_for_target = self.roi_threshold / self.leverage
        if position_type == 'LONG':
            take_profit_price = entry_price * (1 + price_change_for_target)
            stop_loss_price = entry_price * (1 - (self.stop_loss_percent / self.leverage))
        else:  # SHORT
            take_profit_price = entry_price * (1 - price_change_for_target)
            stop_loss_price = entry_price * (1 + (self.stop_loss_percent / self.leverage))
        return stop_loss_price, take_profit_price
    
    def open_position(self, symbol, price, conditions_met, position_type='LONG'):
        """
        포지션을 오픈합니다.
        """
        if symbol in self.active_positions:
            return False, "이미 활성 포지션이 있습니다."
        if len(self.active_positions) >= self.max_positions:
            return False, f"최대 포지션 수({self.max_positions})에 도달했습니다."
        # 매수 수량 계산
        position_size, message = self.calculate_position_size(price)
        if position_size == 0:
            return False, message
        # 레버리지 설정 (실제 거래 시)
        if not self.simulation_mode and self.trading_type == 'FUTURES':
            leverage_result = self.set_leverage(symbol, self.leverage)
            if not leverage_result:
                print(f"레버리지 설정 실패: {symbol}")
        # 실제 주문 실행 (롱: BUY, 숏: SELL)
        order_side = 'BUY' if position_type == 'LONG' else 'SELL'
        order_result = self.place_order(symbol, order_side, position_size, price, 'MARKET')
        if not order_result:
            return False, "주문 실행 실패"
        if order_result.get('status') != 'FILLED':
            return False, f"주문 미체결: {order_result.get('status')}"
        executed_price = float(order_result.get('price', price))
        executed_quantity = float(order_result.get('executedQty', position_size))
        position_value = executed_quantity * executed_price
        # SL/TP 계산 (롱/숏 구분)
        stop_loss_price, take_profit_price = self.calculate_sl_tp_prices(executed_price, position_value, position_type)
        position = {
            'symbol': symbol,
            'entry_price': executed_price,
            'position_size': executed_quantity,
            'position_value': position_value,
            'investment_amount': self.investment_amount,
            'leverage': self.leverage,
            'entry_time': datetime.now(),
            'stop_loss': stop_loss_price,
            'take_profit': take_profit_price,
            'conditions_met': conditions_met,
            'order_id': order_result.get('orderId'),
            'position_type': position_type
        }
        self.active_positions[symbol] = position
        # 알림
        mode_text = "시뮬레이션" if self.simulation_mode else "실제 거래"
        margin_text = "선물" if self.trading_type == 'FUTURES' else "마진"
        pos_text = "롱" if position_type == 'LONG' else "숏"
        message = f"💰 <b>{pos_text} 신호 ({mode_text} {margin_text}) - {symbol}</b>\n\n" \
                  f"투자금액: {self.investment_amount} USDT\n" \
                  f"레버리지: {self.leverage}배\n" \
                  f"포지션 크기: {position_value:.2f} USDT\n" \
                  f"진입가: {executed_price:.8f} USDT\n" \
                  f"수량: {executed_quantity:.6f}\n" \
                  f"손절가: {stop_loss_price:.8f} USDT\n" \
                  f"익절가: {take_profit_price:.8f} USDT\n" \
                  f"조건: {', '.join(conditions_met)}"
        self.telegram_bot.send_message(message)
        print(f"포지션 오픈: {symbol} - {pos_text}, 진입가: {executed_price:.8f}, 수량: {executed_quantity:.6f}, 레버리지: {self.leverage}배")
        return True, "포지션 오픈 완료"
    
    def check_sl_tp(self, symbol, current_price):
        """
        손절/익절 조건을 확인합니다.
        """
        if symbol not in self.active_positions:
            return
        
        position = self.active_positions[symbol]
        entry_price = position['entry_price']
        
        # 손절 확인
        if current_price <= position['stop_loss']:
            self.close_position(symbol, current_price, '손절')
            return
        
        # 익절 확인
        if current_price >= position['take_profit']:
            self.close_position(symbol, current_price, '익절')
            return
    
    def close_position(self, symbol, exit_price, reason):
        """
        포지션을 종료합니다.
        """
        if symbol not in self.active_positions:
            return
        position = self.active_positions[symbol]
        entry_price = position['entry_price']
        position_size = position['position_size']
        position_value = position['position_value']
        investment_amount = position['investment_amount']
        leverage = position['leverage']
        position_type = position.get('position_type', 'LONG')
        # 실제 주문 실행 (롱: SELL, 숏: BUY)
        order_side = 'SELL' if position_type == 'LONG' else 'BUY'
        order_result = self.place_order(symbol, order_side, position_size, exit_price, 'MARKET')
        if not order_result:
            print(f"청산 주문 실패: {symbol}")
            return
        if order_result.get('status') != 'FILLED':
            print(f"청산 주문 미체결: {symbol} - {order_result.get('status')}")
            return
        executed_price = float(order_result.get('price', exit_price))
        executed_quantity = float(order_result.get('executedQty', position_size))
        # 손익 계산 (롱/숏 구분)
        if position_type == 'LONG':
            price_change_percent = (executed_price - entry_price) / entry_price
        else:
            price_change_percent = (entry_price - executed_price) / entry_price
        roi_percent = price_change_percent * leverage
        pnl = investment_amount * roi_percent
        trade_record = {
            'symbol': symbol,
            'entry_price': entry_price,
            'exit_price': executed_price,
            'position_size': executed_quantity,
            'position_value': position_value,
            'investment_amount': investment_amount,
            'leverage': leverage,
            'entry_time': position['entry_time'],
            'exit_time': datetime.now(),
            'reason': reason,
            'pnl': pnl,
            'pnl_percent': roi_percent,
            'price_change_percent': price_change_percent,
            'conditions_met': position['conditions_met'],
            'order_id': order_result.get('orderId'),
            'position_type': position_type
        }
        self.position_history.append(trade_record)
        del self.active_positions[symbol]
        mode_text = "시뮬레이션" if self.simulation_mode else "실제 거래"
        margin_text = "선물" if self.trading_type == 'FUTURES' else "마진"
        pos_text = "롱" if position_type == 'LONG' else "숏"
        emoji = "🔴" if reason == '손절' else "🟢"
        message = f"{emoji} <b>{reason} ({mode_text} {margin_text} {pos_text}) - {symbol}</b>\n\n" \
                  f"투자금액: {investment_amount} USDT\n" \
                  f"레버리지: {leverage}배\n" \
                  f"진입가: {entry_price:.8f} USDT\n" \
                  f"청산가: {executed_price:.8f} USDT\n" \
                  f"가격변동: {price_change_percent:.3%}\n" \
                  f"수량: {executed_quantity:.6f}\n" \
                  f"ROI: {roi_percent:.2%}\n" \
                  f"손익: {pnl:.2f} USDT\n" \
                  f"보유 시간: {trade_record['exit_time'] - trade_record['entry_time']}"
        self.telegram_bot.send_message(message)
        print(f"포지션 종료: {symbol} - {reason}, {pos_text}, ROI: {roi_percent:.2%}, 손익: {pnl:.2f} USDT")
    
    def get_position_summary(self):
        """
        현재 포지션 요약을 반환합니다.
        """
        if not self.active_positions:
            return "현재 활성 포지션이 없습니다."
        
        summary = "📊 <b>현재 포지션 요약</b>\n\n"
        total_invested = 0
        
        for symbol, position in self.active_positions.items():
            current_price = self.get_current_price(symbol)
            if current_price:
                pnl = (current_price - position['entry_price']) * position['position_size']
                pnl_percent = (current_price - position['entry_price']) / position['entry_price']
                total_invested += position['position_value']
                
                summary += f"<b>{symbol}</b>\n"
                summary += f"진입가: {position['entry_price']:.8f}\n"
                summary += f"현재가: {current_price:.8f}\n"
                summary += f"손익: {pnl:.2f} USDT ({pnl_percent:.2%})\n"
                summary += f"손절가: {position['stop_loss']:.8f}\n"
                summary += f"익절가: {position['take_profit']:.8f}\n\n"
        
        summary += f"총 투자금액: {total_invested:.2f} USDT"
        return summary
    
    def get_current_price(self, symbol):
        """
        현재 가격을 가져옵니다.
        """
        try:
            url = "https://api.binance.com/api/v3/ticker/price"
            params = {'symbol': symbol}
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                return float(data['price'])
        except Exception as e:
            print(f"Error getting current price for {symbol}: {e}")
        return None

    def get_current_rsi(self):
        """
        현재 모든 심볼의 1분봉/15분봉 RSI 값을 반환합니다.
        """
        print("\n=== 현재 RSI 상태 ===")
        result = {}
        for symbol in set(list(self.current_rsi_14_1m.keys()) + list(self.current_rsi_14_15m.keys()) + list(self.current_rsi_14_4h.keys())):
            result[symbol] = {
                '1m': {
                    'rsi14': self.current_rsi_14_1m.get(symbol),
                    'rsi7': self.current_rsi_7_1m.get(symbol)
                },
                '15m': {
                    'rsi14': self.current_rsi_14_15m.get(symbol),
                    'rsi7': self.current_rsi_7_15m.get(symbol)
                },
                '4h': {
                    'rsi14': self.current_rsi_14_4h.get(symbol),
                    'rsi7': self.current_rsi_7_4h.get(symbol)
                }
            }
            print(f"{symbol}:")
            print(f"  1분봉 RSI(14) = {result[symbol]['1m']['rsi14']}")
            print(f"  1분봉 RSI(7) = {result[symbol]['1m']['rsi7']}")
            print(f"  15분봉 RSI(14) = {result[symbol]['15m']['rsi14']}")
            print(f"  15분봉 RSI(7) = {result[symbol]['15m']['rsi7']}")
            print(f"  4시간봉 RSI(14) = {result[symbol]['4h']['rsi14']}")
            print(f"  4시간봉 RSI(7) = {result[symbol]['4h']['rsi7']}")
        print("===================\n")
        return result
    
    def get_rsi_summary_messages(self):
        """
        RSI 요약 메시지들을 생성하여 반환합니다.
        소켓 오픈 시와 /rsi 명령어 시 모두 사용하는 공통 함수입니다.
        """
        rsi_dict = self.get_current_rsi()
        messages = []
        
        if not rsi_dict:
            return ["⚠️ RSI 데이터가 없습니다."]
        
        # 1분봉 과매수/과매도 TOP10 (30 이내만)
        rsi_1m_list = [(symbol, v['1m']['rsi14']) for symbol, v in rsi_dict.items() if v['1m']['rsi14'] is not None]
        rsi_1m_over = [x for x in rsi_1m_list if x[1] >= 70]
        rsi_1m_over = sorted(rsi_1m_over, key=lambda x: x[1], reverse=True)[:10]
        rsi_1m_under = [x for x in rsi_1m_list if x[1] <= 30]
        rsi_1m_under = sorted(rsi_1m_under, key=lambda x: x[1])[:10]
        
        msg_1m_over = "📊 <b>1분봉 RSI(14) 과매수 TOP10 (70~100)</b>\n\n"
        for symbol, rsi in rsi_1m_over:
            m1 = rsi_dict[symbol]['1m']
            msg_1m_over += f"<b>{symbol}</b>\n  RSI(14): {m1['rsi14']:.2f}\n  RSI(7): {m1['rsi7']:.2f}\n\n"
        messages.append(msg_1m_over)
        
        msg_1m_under = "📊 <b>1분봉 RSI(14) 과매도 TOP10 (0~30)</b>\n\n"
        for symbol, rsi in rsi_1m_under:
            m1 = rsi_dict[symbol]['1m']
            msg_1m_under += f"<b>{symbol}</b>\n  RSI(14): {m1['rsi14']:.2f}\n  RSI(7): {m1['rsi7']:.2f}\n\n"
        messages.append(msg_1m_under)
        
        # 15분봉 과매수/과매도 TOP10 (30 이내만)
        rsi_15m_list = [(symbol, v['15m']['rsi14']) for symbol, v in rsi_dict.items() if v['15m']['rsi14'] is not None]
        rsi_15m_over = [x for x in rsi_15m_list if x[1] >= 70]
        rsi_15m_over = sorted(rsi_15m_over, key=lambda x: x[1], reverse=True)[:10]
        rsi_15m_under = [x for x in rsi_15m_list if x[1] <= 30]
        rsi_15m_under = sorted(rsi_15m_under, key=lambda x: x[1])[:10]
        
        msg_15m_over = "📊 <b>15분봉 RSI(14) 과매수 TOP10 (70~100)</b>\n\n"
        for symbol, rsi in rsi_15m_over:
            m15 = rsi_dict[symbol]['15m']
            msg_15m_over += f"<b>{symbol}</b>\n  RSI(14): {m15['rsi14']:.2f}\n  RSI(7): {m15['rsi7']:.2f}\n\n"
        messages.append(msg_15m_over)
        
        msg_15m_under = "📊 <b>15분봉 RSI(14) 과매도 TOP10 (0~30)</b>\n\n"
        for symbol, rsi in rsi_15m_under:
            m15 = rsi_dict[symbol]['15m']
            msg_15m_under += f"<b>{symbol}</b>\n  RSI(14): {m15['rsi14']:.2f}\n  RSI(7): {m15['rsi7']:.2f}\n\n"
        messages.append(msg_15m_under)
        
        # 4시간봉 과매수/과매도 TOP10 (30 이내만)
        rsi_4h_list = [(symbol, v['4h']['rsi14']) for symbol, v in rsi_dict.items() if v['4h']['rsi14'] is not None]
        rsi_4h_over = [x for x in rsi_4h_list if x[1] >= 70]
        rsi_4h_over = sorted(rsi_4h_over, key=lambda x: x[1], reverse=True)[:10]
        rsi_4h_under = [x for x in rsi_4h_list if x[1] <= 30]
        rsi_4h_under = sorted(rsi_4h_under, key=lambda x: x[1])[:10]
        
        msg_4h_over = "📊 <b>4시간봉 RSI(14) 과매수 TOP10 (70~100)</b>\n\n"
        for symbol, rsi in rsi_4h_over:
            m4h = rsi_dict[symbol]['4h']
            msg_4h_over += f"<b>{symbol}</b>\n  RSI(14): {m4h['rsi14']:.2f}\n  RSI(7): {m4h['rsi7']:.2f}\n\n"
        messages.append(msg_4h_over)
        
        msg_4h_under = "📊 <b>4시간봉 RSI(14) 과매도 TOP10 (0~30)</b>\n\n"
        for symbol, rsi in rsi_4h_under:
            m4h = rsi_dict[symbol]['4h']
            msg_4h_under += f"<b>{symbol}</b>\n  RSI(14): {m4h['rsi14']:.2f}\n  RSI(7): {m4h['rsi7']:.2f}\n\n"
        messages.append(msg_4h_under)
        
        return messages

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
            volume = float(kline.get('v', 0))
            is_closed = kline.get('x', False)
            if not symbol or price == 0:
                return
            if symbol not in self.price_data_1m or symbol not in self.price_data_15m or symbol not in self.price_data_4h:
                self.initialize_symbol_data(symbol)

            # 실시간 RSI 계산: 진행 중인 캔들 가격을 price_data에 임시로 반영
            if interval == '1m':
                if is_closed:
                    # 봉 마감: deque에 append
                    self.price_data_1m[symbol].append(price)
                    self.volume_data_1m[symbol].append(volume)
                    # 봉 마감 후 RSI 계산
                    if len(self.price_data_1m[symbol]) >= self.data_length:
                        price_list = list(self.price_data_1m[symbol])
                        rsi_14 = calculate_rsi_binance(price_list, period=14)
                        rsi_7 = calculate_rsi_binance(price_list, period=7)
                        self.current_rsi_14_1m[symbol] = rsi_14
                        self.current_rsi_7_1m[symbol] = rsi_7
                else:
                    # 봉 진행 중: 현재 가격을 포함한 새로운 가격 리스트 생성
                    price_list = list(self.price_data_1m[symbol])
                    if price_list:
                        # 마지막 봉의 가격을 현재 가격으로 교체
                        price_list[-1] = price
                    else:
                        price_list = [price]
                    
                    # 실시간 RSI 계산
                    if len(price_list) >= self.data_length:
                        rsi_14 = calculate_rsi_binance(price_list, period=14)
                        rsi_7 = calculate_rsi_binance(price_list, period=7)
                        self.current_rsi_14_1m[symbol] = rsi_14
                        self.current_rsi_7_1m[symbol] = rsi_7
            
            if interval == '15m':
                if is_closed:
                    self.price_data_15m[symbol].append(price)
                    self.volume_data_15m[symbol].append(volume)
                    # 봉 마감 후 RSI 계산
                    if len(self.price_data_15m[symbol]) >= self.data_length:
                        price_list = list(self.price_data_15m[symbol])
                        rsi_14 = calculate_rsi_binance(price_list, period=14)
                        rsi_7 = calculate_rsi_binance(price_list, period=7)
                        self.current_rsi_14_15m[symbol] = rsi_14
                        self.current_rsi_7_15m[symbol] = rsi_7
                else:
                    # 봉 진행 중: 현재 가격을 포함한 새로운 가격 리스트 생성
                    price_list = list(self.price_data_15m[symbol])
                    if price_list:
                        # 마지막 봉의 가격을 현재 가격으로 교체
                        price_list[-1] = price
                    else:
                        price_list = [price]
                    
                    # 실시간 RSI 계산
                    if len(price_list) >= self.data_length:
                        rsi_14 = calculate_rsi_binance(price_list, period=14)
                        rsi_7 = calculate_rsi_binance(price_list, period=7)
                        self.current_rsi_14_15m[symbol] = rsi_14
                        self.current_rsi_7_15m[symbol] = rsi_7
            
            if interval == '4h':
                if is_closed:
                    self.price_data_4h[symbol].append(price)
                    self.volume_data_4h[symbol].append(volume)
                    # 봉 마감 후 RSI 계산
                    if len(self.price_data_4h[symbol]) >= self.data_length:
                        price_list = list(self.price_data_4h[symbol])
                        rsi_14 = calculate_rsi_binance(price_list, period=14)
                        rsi_7 = calculate_rsi_binance(price_list, period=7)
                        self.current_rsi_14_4h[symbol] = rsi_14
                        self.current_rsi_7_4h[symbol] = rsi_7
                else:
                    # 봉 진행 중: 현재 가격을 포함한 새로운 가격 리스트 생성
                    price_list = list(self.price_data_4h[symbol])
                    if price_list:
                        # 마지막 봉의 가격을 현재 가격으로 교체
                        price_list[-1] = price
                    else:
                        price_list = [price]
                    
                    # 실시간 RSI 계산
                    if len(price_list) >= self.data_length:
                        rsi_14 = calculate_rsi_binance(price_list, period=14)
                        rsi_7 = calculate_rsi_binance(price_list, period=7)
                        self.current_rsi_14_4h[symbol] = rsi_14
                        self.current_rsi_7_4h[symbol] = rsi_7
            # --- 항상 dict에서 값을 꺼내서 지역변수로 사용 ---
            rsi_14_1m = self.current_rsi_14_1m.get(symbol)
            rsi_7_1m = self.current_rsi_7_1m.get(symbol)
            rsi_14_15m = self.current_rsi_14_15m.get(symbol)
            rsi_7_15m = self.current_rsi_7_15m.get(symbol)
            rsi_14_4h = self.current_rsi_14_4h.get(symbol)
            rsi_7_4h = self.current_rsi_7_4h.get(symbol)
            # SL/TP 체크 (모든 가격 업데이트에서)
            self.check_sl_tp(symbol, price)
            
            # RSI 알림 로직 추가
            # 4시간봉 RSI 알림
            if rsi_14_4h is not None and rsi_7_4h is not None:
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
            
            # 15분봉 RSI 알림
            if rsi_14_15m is not None and rsi_7_15m is not None:
                # 15분봉 RSI(14) 과매수 알림
                if rsi_14_15m >= self.rsi_overbought and symbol not in self.alerted_overbought_14:
                    msg = f"🔴 <b>15분봉 RSI(14) 과매수 알림 - {symbol}</b>\n\n" \
                          f"RSI(14): {rsi_14_15m:.2f}\n" \
                          f"RSI(7): {rsi_7_15m:.2f}\n" \
                          f"현재가: {price:.8f} USDT"
                    self.telegram_bot.send_message(msg)
                    self.alerted_overbought_14.add(symbol)
                    print(f"15분봉 RSI(14) 과매수 알림: {symbol} - RSI: {rsi_14_15m:.2f}")
                
                # 15분봉 RSI(14) 과매도 알림
                elif rsi_14_15m <= self.rsi_oversold and symbol not in self.alerted_oversold_14:
                    msg = f"🟢 <b>15분봉 RSI(14) 과매도 알림 - {symbol}</b>\n\n" \
                          f"RSI(14): {rsi_14_15m:.2f}\n" \
                          f"RSI(7): {rsi_7_15m:.2f}\n" \
                          f"현재가: {price:.8f} USDT"
                    self.telegram_bot.send_message(msg)
                    self.alerted_oversold_14.add(symbol)
                    print(f"15분봉 RSI(14) 과매도 알림: {symbol} - RSI: {rsi_14_15m:.2f}")
                
                # 15분봉 RSI(7) 과매수 알림
                if rsi_7_15m >= self.rsi_overbought and symbol not in self.alerted_overbought_7:
                    msg = f"🔴 <b>15분봉 RSI(7) 과매수 알림 - {symbol}</b>\n\n" \
                          f"RSI(14): {rsi_14_15m:.2f}\n" \
                          f"RSI(7): {rsi_7_15m:.2f}\n" \
                          f"현재가: {price:.8f} USDT"
                    self.telegram_bot.send_message(msg)
                    self.alerted_overbought_7.add(symbol)
                    print(f"15분봉 RSI(7) 과매수 알림: {symbol} - RSI: {rsi_7_15m:.2f}")
                
                # 15분봉 RSI(7) 과매도 알림
                elif rsi_7_15m <= self.rsi_oversold and symbol not in self.alerted_oversold_7:
                    msg = f"🟢 <b>15분봉 RSI(7) 과매도 알림 - {symbol}</b>\n\n" \
                          f"RSI(14): {rsi_14_15m:.2f}\n" \
                          f"RSI(7): {rsi_7_15m:.2f}\n" \
                          f"현재가: {price:.8f} USDT"
                    self.telegram_bot.send_message(msg)
                    self.alerted_oversold_7.add(symbol)
                    print(f"15분봉 RSI(7) 과매도 알림: {symbol} - RSI: {rsi_7_15m:.2f}")
                
                # 15분봉 RSI 주의 알림 (과매수/과매도 구간에서 벗어났을 때)
                if rsi_14_15m < self.rsi_overbought and symbol in self.alerted_overbought_14:
                    self.alerted_overbought_14.remove(symbol)
                if rsi_14_15m > self.rsi_oversold and symbol in self.alerted_oversold_14:
                    self.alerted_oversold_14.remove(symbol)
                if rsi_7_15m < self.rsi_overbought and symbol in self.alerted_overbought_7:
                    self.alerted_overbought_7.remove(symbol)
                if rsi_7_15m > self.rsi_oversold and symbol in self.alerted_oversold_7:
                    self.alerted_oversold_7.remove(symbol)
            
            # 매수/매도 조건 확인 (15분봉 완료 시에만)
            if (interval == '15m') and rsi_14_1m is not None and rsi_7_1m is not None and rsi_14_15m is not None and rsi_7_15m is not None and rsi_14_4h is not None and rsi_7_4h is not None:
                # 롱 조건
                long_signal, long_conditions = self.check_buy_conditions(symbol, price, rsi_14_1m, rsi_7_1m, rsi_14_15m, rsi_7_15m, rsi_14_4h, rsi_7_4h)
                # 숏 조건
                short_signal, short_conditions = self.check_short_conditions(symbol, price, rsi_14_1m, rsi_7_1m, rsi_14_15m, rsi_7_15m, rsi_14_4h, rsi_7_4h)
                # 롱 진입
                if long_signal and symbol not in self.active_positions:
                    if self.auto_trading:
                        success, message = self.open_position(symbol, price, long_conditions, position_type='LONG')
                        if success:
                            print(f"롱 신호 감지: {symbol} - 조건: {long_conditions}")
                        else:
                            print(f"롱 진입 실패: {symbol} - {message}")
                    else:
                        msg = f"[자동주문 OFF] 롱 신호 감지: {symbol} - 조건: {', '.join(long_conditions)}"
                        print(msg)
                        self.telegram_bot.send_message(msg)
                # 숏 진입
                if short_signal and symbol not in self.active_positions:
                    if self.auto_trading:
                        success, message = self.open_position(symbol, price, short_conditions, position_type='SHORT')
                        if success:
                            print(f"숏 신호 감지: {symbol} - 조건: {short_conditions}")
                        else:
                            print(f"숏 진입 실패: {symbol} - {message}")
                    else:
                        msg = f"[자동주문 OFF] 숏 신호 감지: {symbol} - 조건: {', '.join(short_conditions)}"
                        print(msg)
                        self.telegram_bot.send_message(msg)
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
        futures_symbols = set(self.get_futures_usdt_symbols())
        symbols = [s for s in get_top_coins(30) if s in futures_symbols]
        for symbol in symbols:
            self.initialize_symbol_data(symbol)
        # 초기 RSI 상태 메시지 전송 (각 봉별 극단치 TOP10)
        if self.current_rsi_14_1m or self.current_rsi_14_15m or self.current_rsi_14_4h:
            rsi_messages = self.get_rsi_summary_messages()
            for message in rsi_messages:
                self.telegram_bot.send_message(message)
    
    def start_monitoring(self):
        """
        모니터링 시작
        """
        futures_symbols = set(self.get_futures_usdt_symbols())
        symbols = [s for s in get_top_coins(30) if s in futures_symbols]
        if not symbols:
            print("Failed to get top coins")
            return
        print(f"Monitoring symbols: {symbols}")
        streams = [f"{symbol.lower()}@kline_1m" for symbol in symbols] + [f"{symbol.lower()}@kline_15m" for symbol in symbols] + [f"{symbol.lower()}@kline_4h" for symbol in symbols]
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
    
    def get_account_info(self):
        """
        계정 정보를 가져옵니다.
        """
        if self.simulation_mode:
            return {
                'balances': [
                    {'asset': 'USDT', 'free': '1000.00', 'locked': '0.00'},
                    {'asset': 'BTC', 'free': '0.00000000', 'locked': '0.00000000'}
                ]
            }
        
        if self.trading_type == 'FUTURES':
            return self._make_request('GET', '/fapi/v1/account', signed=True)
        else:
            return self._make_request('GET', '/api/v3/account', signed=True)
    
    def get_margin_account_info(self):
        """
        선물 계정 정보를 가져옵니다.
        """
        if self.simulation_mode:
            return {
                'totalWalletBalance': '1000.00',
                'totalUnrealizedProfit': '0.00',
                'totalMarginBalance': '1000.00',
                'totalPositionInitialMargin': '0.00',
                'totalOpenOrderInitialMargin': '0.00',
                'totalCrossWalletBalance': '1000.00',
                'totalCrossUnPnl': '0.00',
                'availableBalance': '1000.00',
                'maxWithdrawAmount': '1000.00',
                'assets': [
                    {
                        'asset': 'USDT',
                        'walletBalance': '1000.00',
                        'unrealizedProfit': '0.00',
                        'marginBalance': '1000.00',
                        'maintMargin': '0.00',
                        'initialMargin': '0.00',
                        'positionInitialMargin': '0.00',
                        'openOrderInitialMargin': '0.00',
                        'crossWalletBalance': '1000.00',
                        'crossUnPnl': '0.00',
                        'availableBalance': '1000.00',
                        'maxWithdrawAmount': '1000.00'
                    }
                ]
            }
        
        return self._make_request('GET', '/fapi/v1/account', signed=True)
    
    def set_leverage(self, symbol, leverage):
        """
        레버리지를 설정합니다.
        """
        if self.simulation_mode:
            print(f"시뮬레이션 레버리지 설정: {symbol} - {leverage}배")
            return {'leverage': leverage}
        
        params = {
            'symbol': symbol,
            'leverage': leverage
        }
        
        return self._make_request('POST', '/fapi/v1/leverage', params, signed=True)
    
    def get_symbol_info(self, symbol):
        """
        심볼 정보를 가져옵니다.
        """
        params = {'symbol': symbol}
        if self.trading_type == 'FUTURES':
            return self._make_request('GET', '/fapi/v1/exchangeInfo', params)
        else:
            return self._make_request('GET', '/api/v3/exchangeInfo', params)
    
    def get_balance(self, asset='USDT'):
        """
        특정 자산의 잔고를 가져옵니다.
        """
        if self.trading_type == 'FUTURES':
            account_info = self.get_margin_account_info()
        else:
            account_info = self.get_account_info()
            
        if not account_info:
            return 0.0
        
        if self.trading_type == 'FUTURES':
            for balance in account_info.get('assets', []):
                if balance['asset'] == asset:
                    return float(balance['availableBalance'])
        else:
            for balance in account_info.get('balances', []):
                if balance['asset'] == asset:
                    return float(balance['free'])
        return 0.0
    
    def place_futures_order(self, symbol, side, quantity, price=None, order_type='MARKET'):
        """
        선물 주문을 실행합니다.
        """
        if self.simulation_mode:
            # 시뮬레이션 모드
            order_id = f"sim_{int(time.time() * 1000)}"
            executed_price = price if price else self.get_current_price(symbol)
            
            print(f"시뮬레이션 선물 주문: {side} {quantity} {symbol} @ {executed_price}")
            
            return {
                'orderId': order_id,
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'price': executed_price,
                'status': 'FILLED'
            }
        
        # 실제 선물 주문
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': quantity
        }
        
        if price and order_type == 'LIMIT':
            params['price'] = price
            params['timeInForce'] = 'GTC'
        
        return self._make_request('POST', '/fapi/v1/order', params, signed=True)
    
    def place_order(self, symbol, side, quantity, price=None, order_type='MARKET'):
        """
        주문을 실행합니다.
        """
        if self.trading_type == 'FUTURES':
            return self.place_futures_order(symbol, side, quantity, price, order_type)
        
        if self.simulation_mode:
            # 시뮬레이션 모드
            order_id = f"sim_{int(time.time() * 1000)}"
            executed_price = price if price else self.get_current_price(symbol)
            
            print(f"시뮬레이션 주문: {side} {quantity} {symbol} @ {executed_price}")
            
            return {
                'orderId': order_id,
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'price': executed_price,
                'status': 'FILLED'
            }
        
        # 실제 주문
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': quantity
        }
        
        if price and order_type == 'LIMIT':
            params['price'] = price
            params['timeInForce'] = 'GTC'
        
        return self._make_request('POST', '/api/v3/order', params, signed=True)
    
    def cancel_order(self, symbol, order_id):
        """
        주문을 취소합니다.
        """
        if self.simulation_mode:
            print(f"시뮬레이션 주문 취소: {order_id}")
            return {'status': 'CANCELED'}
        
        params = {
            'symbol': symbol,
            'orderId': order_id
        }
        
        if self.trading_type == 'FUTURES':
            return self._make_request('DELETE', '/fapi/v1/order', params, signed=True)
        else:
            return self._make_request('DELETE', '/api/v3/order', params, signed=True)
    
    def get_order_status(self, symbol, order_id):
        """
        주문 상태를 확인합니다.
        """
        if self.simulation_mode:
            return {'status': 'FILLED'}
        
        params = {
            'symbol': symbol,
            'orderId': order_id
        }
        
        if self.trading_type == 'FUTURES':
            return self._make_request('GET', '/fapi/v1/order', params, signed=True)
        else:
            return self._make_request('GET', '/api/v3/order', params, signed=True)

    def check_short_conditions(self, symbol, price, rsi_14_1m, rsi_7_1m, rsi_14_15m, rsi_7_15m, rsi_14_4h, rsi_7_4h):
        conditions_met = []
        # 4시간봉 RSI 과매수 조건
        if self.buy_conditions.get('rsi_4h_oversold', True):
            if (rsi_14_4h is not None and rsi_14_4h >= self.rsi_overbought) or \
               (rsi_7_4h is not None and rsi_7_4h >= self.rsi_overbought):
                conditions_met.append('4시간봉 RSI 과매수')
        # 15분봉 RSI 과매수 조건
        if self.buy_conditions['rsi_15m_oversold']:
            if (rsi_14_15m is not None and rsi_14_15m >= self.rsi_overbought) or \
               (rsi_7_15m is not None and rsi_7_15m >= self.rsi_overbought):
                conditions_met.append('15분봉 RSI 과매수')
        # 1분봉 RSI 과매수 조건
        if self.buy_conditions['rsi_1m_oversold']:
            if (rsi_14_1m is not None and rsi_14_1m >= self.rsi_overbought) or \
               (rsi_7_1m is not None and rsi_7_1m >= self.rsi_overbought):
                conditions_met.append('1분봉 RSI 과매수')
        # 거래량 스파이크 조건 (필수)
        if self.buy_conditions['volume_spike']:
            volume_spike_15m, volume_ratio_15m = self.check_volume_spike(symbol, '15m')
            volume_spike_1m, volume_ratio_1m = self.check_volume_spike(symbol, '1m')
            if volume_spike_15m or volume_spike_1m:
                max_ratio = max(volume_ratio_15m, volume_ratio_1m)
            else:
                return False, []
        # 가격 하락 조건 (최근 10개 캔들 기준)
        if self.buy_conditions['price_drop'] > 0:
            if len(self.price_data_15m.get(symbol, [])) >= 10:
                recent_prices = list(self.price_data_15m[symbol])[-10:]
                price_drop = (recent_prices[0] - recent_prices[-1]) / recent_prices[0]
        return len(conditions_met) >= 2, conditions_met

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
        symbols = self.get_futures_usdt_symbols()
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