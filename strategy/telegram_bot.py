import requests
import os
from dotenv import load_dotenv
import threading
import time
from get_top_coins import get_top_coins

load_dotenv()

class TelegramBot:
    def __init__(self, rsi_monitor=None):
        self.token = os.getenv('TELEGRAM_TOKEN')  # 기존 설정 사용
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')  # 기존 설정 사용
        
        # 설정 확인
        if not self.token:
            print("Error: TELEGRAM_TOKEN is not set in .env file")
            return
        if not self.chat_id:
            print("Error: TELEGRAM_CHAT_ID is not set in .env file")
            return
            
        print(f"Telegram Bot initialized with token: {self.token[:5]}...")
        print(f"Chat ID: {self.chat_id}")
        
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.rsi_monitor = rsi_monitor
        self.last_update_id = 0
        self.running = True
        
        # 봇 연결 테스트
        self._test_connection()
        
        # 명령어 처리 스레드 시작
        self.command_thread = threading.Thread(target=self.process_commands)
        self.command_thread.daemon = True
        self.command_thread.start()
    
    def _test_connection(self):
        """
        텔레그램 봇 연결을 테스트합니다.
        """
        try:
            url = f"{self.base_url}/getMe"
            response = requests.get(url)
            if response.status_code == 200:
                bot_info = response.json()
                if bot_info.get('ok'):
                    print(f"Successfully connected to bot: {bot_info['result']['username']}")
                    # 테스트 메시지 전송
                    self.send_message("🤖 RSI 모니터링 봇이 시작되었습니다.")
                else:
                    print("Error: Failed to get bot information")
            else:
                print(f"Error: Failed to connect to bot (Status code: {response.status_code})")
        except Exception as e:
            print(f"Error testing bot connection: {e}")
    
    def send_message(self, message):
        """
        텔레그램으로 메시지를 전송합니다.
        """
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            response = requests.post(url, data=data)
            if response.status_code != 200:
                print(f"Error sending message: {response.text}")
            return response.json()
        except Exception as e:
            print(f"Error sending telegram message: {e}")
            return None
    
    def process_commands(self):
        """
        텔레그램 명령어를 처리합니다.
        """
        while self.running:
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                params = {
                    "offset": self.last_update_id + 1,
                    "timeout": 30
                }
                response = requests.get(url, params=params)
                
                if response.status_code == 200:
                    updates = response.json()
                    if updates.get('ok'):
                        for update in updates.get('result', []):
                            self.last_update_id = update['update_id']
                            if 'message' in update and 'text' in update['message']:
                                command = update['message']['text']
                                print(f"수신된 명령어: {command}")  # 디버그 로그 추가
                                self.handle_command(command)
                else:
                    print(f"Error getting updates: {response.text}")
                    time.sleep(5)
                    
            except Exception as e:
                print(f"Error processing updates: {e}")
                time.sleep(5)
    
    def handle_command(self, command):
        """
        텔레그램 명령어를 처리합니다.
        """
        print(f"명령어 처리 시작: {command}")
        
        if command in ['/status', '/rsi']:
            try:
                print("RSI 데이터 요청 중...")
                self.send_message("RSI 데이터 요청 중...")
                rsi_dict = self.rsi_monitor.get_current_rsi()
                # 1분봉 과매수/과매도 TOP10 (20 이내만)
                rsi_1m_list = [(symbol, v['1m']['rsi14']) for symbol, v in rsi_dict.items() if v['1m']['rsi14'] is not None]
                rsi_1m_over = [x for x in rsi_1m_list if x[1] >= 80]
                rsi_1m_over = sorted(rsi_1m_over, key=lambda x: x[1], reverse=True)[:10]
                rsi_1m_under = [x for x in rsi_1m_list if x[1] <= 20]
                rsi_1m_under = sorted(rsi_1m_under, key=lambda x: x[1])[:10]
                msg_1m_over = "📊 <b>1분봉 RSI(14) 과매수 TOP10 (80~100)</b>\n\n"
                for symbol, rsi in rsi_1m_over:
                    m1 = rsi_dict[symbol]['1m']
                    msg_1m_over += f"<b>{symbol}</b>\n  RSI(14): {m1['rsi14']}\n  RSI(7): {m1['rsi7']}\n\n"
                msg_1m_under = "📊 <b>1분봉 RSI(14) 과매도 TOP10 (0~20)</b>\n\n"
                for symbol, rsi in rsi_1m_under:
                    m1 = rsi_dict[symbol]['1m']
                    msg_1m_under += f"<b>{symbol}</b>\n  RSI(14): {m1['rsi14']}\n  RSI(7): {m1['rsi7']}\n\n"
                self.send_message(msg_1m_over)
                self.send_message(msg_1m_under)
                # 15분봉 과매수/과매도 TOP10 (20 이내만)
                rsi_15m_list = [(symbol, v['15m']['rsi14']) for symbol, v in rsi_dict.items() if v['15m']['rsi14'] is not None]
                rsi_15m_over = [x for x in rsi_15m_list if x[1] >= 80]
                rsi_15m_over = sorted(rsi_15m_over, key=lambda x: x[1], reverse=True)[:10]
                rsi_15m_under = [x for x in rsi_15m_list if x[1] <= 20]
                rsi_15m_under = sorted(rsi_15m_under, key=lambda x: x[1])[:10]
                msg_15m_over = "📊 <b>15분봉 RSI(14) 과매수 TOP10 (80~100)</b>\n\n"
                for symbol, rsi in rsi_15m_over:
                    m15 = rsi_dict[symbol]['15m']
                    msg_15m_over += f"<b>{symbol}</b>\n  RSI(14): {m15['rsi14']}\n  RSI(7): {m15['rsi7']}\n\n"
                msg_15m_under = "📊 <b>15분봉 RSI(14) 과매도 TOP10 (0~20)</b>\n\n"
                for symbol, rsi in rsi_15m_under:
                    m15 = rsi_dict[symbol]['15m']
                    msg_15m_under += f"<b>{symbol}</b>\n  RSI(14): {m15['rsi14']}\n  RSI(7): {m15['rsi7']}\n\n"
                self.send_message(msg_15m_over)
                self.send_message(msg_15m_under)
                # 4시간봉 과매수/과매도 TOP10 (20 이내만)
                rsi_4h_list = [(symbol, v['4h']['rsi14']) for symbol, v in rsi_dict.items() if v['4h']['rsi14'] is not None]
                rsi_4h_over = [x for x in rsi_4h_list if x[1] >= 80]
                rsi_4h_over = sorted(rsi_4h_over, key=lambda x: x[1], reverse=True)[:10]
                rsi_4h_under = [x for x in rsi_4h_list if x[1] <= 20]
                rsi_4h_under = sorted(rsi_4h_under, key=lambda x: x[1])[:10]
                msg_4h_over = "📊 <b>4시간봉 RSI(14) 과매수 TOP10 (80~100)</b>\n\n"
                for symbol, rsi in rsi_4h_over:
                    m4h = rsi_dict[symbol]['4h']
                    msg_4h_over += f"<b>{symbol}</b>\n  RSI(14): {m4h['rsi14']}\n  RSI(7): {m4h['rsi7']}\n\n"
                msg_4h_under = "📊 <b>4시간봉 RSI(14) 과매도 TOP10 (0~20)</b>\n\n"
                for symbol, rsi in rsi_4h_under:
                    m4h = rsi_dict[symbol]['4h']
                    msg_4h_under += f"<b>{symbol}</b>\n  RSI(14): {m4h['rsi14']}\n  RSI(7): {m4h['rsi7']}\n\n"
                self.send_message(msg_4h_over)
                self.send_message(msg_4h_under)
                print("메시지 전송 완료")
            except Exception as e:
                print(f"Error handling status command: {e}")
                self.send_message("⚠️ RSI 데이터를 가져오는 중 오류가 발생했습니다.")
        
        elif command == '/help':
            message = "🤖 <b>RSI 모니터링 봇 명령어</b>\n\n" \
                     "/status 또는 /rsi - 현재 RSI 상태 확인 (1분/15분봉, 극단치 TOP10)\n" \
                     "/position - 현재 포지션 요약\n" \
                     "/history - 거래 이력 확인\n" \
                     "/settings - 현재 설정 확인\n" \
                     "/balance - 잔고 정보 확인\n" \
                     "/cancel - 모든 활성 포지션 취소\n" \
                     "/testnet - 현재 모드 확인\n" \
                     "/help - 도움말 보기"
            self.send_message(message)
        
        elif command == '/position':
            try:
                summary = self.rsi_monitor.get_position_summary()
                self.send_message(summary)
            except Exception as e:
                print(f"Error handling position command: {e}")
                self.send_message("⚠️ 포지션 정보를 가져오는 중 오류가 발생했습니다.")
        
        elif command == '/history':
            try:
                history = self.rsi_monitor.position_history
                if not history:
                    self.send_message("📊 <b>거래 이력</b>\n\n아직 거래 이력이 없습니다.")
                    return
                
                # 최근 10개 거래만 표시
                recent_trades = history[-10:]
                message = "📊 <b>최근 거래 이력 (최근 10개)</b>\n\n"
                
                total_pnl = 0
                win_count = 0
                
                for trade in recent_trades:
                    emoji = "🟢" if trade['pnl'] > 0 else "🔴"
                    message += f"{emoji} <b>{trade['symbol']}</b> - {trade['reason']}\n"
                    message += f"진입: {trade['entry_price']:.8f} → 청산: {trade['exit_price']:.8f}\n"
                    message += f"손익: {trade['pnl']:.2f} USDT ({trade['pnl_percent']:.2%})\n"
                    message += f"보유시간: {trade['exit_time'] - trade['entry_time']}\n\n"
                    
                    total_pnl += trade['pnl']
                    if trade['pnl'] > 0:
                        win_count += 1
                
                win_rate = (win_count / len(recent_trades)) * 100
                message += f"<b>요약:</b>\n"
                message += f"총 손익: {total_pnl:.2f} USDT\n"
                message += f"승률: {win_rate:.1f}% ({win_count}/{len(recent_trades)})"
                
                self.send_message(message)
            except Exception as e:
                print(f"Error handling history command: {e}")
                self.send_message("⚠️ 거래 이력을 가져오는 중 오류가 발생했습니다.")
        
        elif command == '/settings':
            try:
                settings = self.rsi_monitor
                margin_text = "선물" if settings.trading_type == 'FUTURES' else "마진"
                auto_text = "ON" if settings.auto_trading else "OFF"
                message = "⚙️ <b>현재 설정</b>\n\n" \
                         f"거래 타입: {margin_text}\n" \
                         f"자동주문: {auto_text}\n" \
                         f"투자금액: {settings.investment_amount} USDT\n" \
                         f"레버리지: {settings.leverage}배\n" \
                         f"포지션 크기: {settings.position_size_usdt} USDT\n" \
                         f"ROI 기준: {settings.roi_threshold:.1%}\n" \
                         f"손절: {settings.stop_loss_percent:.1%}\n" \
                         f"익절: {settings.take_profit_percent:.1%}\n\n" \
                         f"<b>매수 조건:</b>\n" \
                         f"• 15분봉 RSI 과매도: {'활성화' if settings.buy_conditions['rsi_15m_oversold'] else '비활성화'}\n" \
                         f"• 1분봉 RSI 과매도: {'활성화' if settings.buy_conditions['rsi_1m_oversold'] else '비활성화'}\n" \
                         f"• 거래량 스파이크: {'활성화' if settings.buy_conditions['volume_spike'] else '비활성화'} (필수)\n" \
                         f"• 거래량 임계값: {settings.volume_spike_threshold:.1f}배\n" \
                         f"• 가격 하락 기준: {settings.buy_conditions['price_drop']:.1%}\n\n" \
                         f"<b>RSI 설정:</b>\n" \
                         f"• 과매수: {settings.rsi_overbought}\n" \
                         f"• 과매도: {settings.rsi_oversold}\n" \
                         f"• 주의 상단: {settings.rsi_warning_high}\n" \
                         f"• 주의 하단: {settings.rsi_warning_low}"
                
                self.send_message(message)
            except Exception as e:
                print(f"Error handling settings command: {e}")
                self.send_message("⚠️ 설정 정보를 가져오는 중 오류가 발생했습니다.")
        
        elif command == '/auto_on':
            self.rsi_monitor.auto_trading = True
            self.send_message("✅ 자동주문이 활성화되었습니다.")
        elif command == '/auto_off':
            self.rsi_monitor.auto_trading = False
            self.send_message("⏸️ 자동주문이 비활성화되었습니다.")
        
        elif command == '/balance':
            try:
                usdt_balance = self.rsi_monitor.get_balance('USDT')
                mode_text = "시뮬레이션" if self.rsi_monitor.simulation_mode else "실제 거래"
                message = f"💰 <b>잔고 정보 ({mode_text})</b>\n\n" \
                         f"USDT 잔고: {usdt_balance:.2f} USDT\n" \
                         f"활성 포지션: {len(self.rsi_monitor.active_positions)}개\n" \
                         f"최대 포지션: {self.rsi_monitor.max_positions}개"
                
                self.send_message(message)
            except Exception as e:
                print(f"Error handling balance command: {e}")
                self.send_message("⚠️ 잔고 정보를 가져오는 중 오류가 발생했습니다.")
        
        elif command == '/cancel':
            try:
                if not self.rsi_monitor.active_positions:
                    self.send_message("❌ 취소할 활성 포지션이 없습니다.")
                    return
                
                # 모든 활성 포지션 취소
                canceled_count = 0
                for symbol, position in list(self.rsi_monitor.active_positions.items()):
                    if 'order_id' in position:
                        result = self.rsi_monitor.cancel_order(symbol, position['order_id'])
                        if result and result.get('status') == 'CANCELED':
                            del self.rsi_monitor.active_positions[symbol]
                            canceled_count += 1
                
                mode_text = "시뮬레이션" if self.rsi_monitor.simulation_mode else "실제 거래"
                self.send_message(f"✅ {canceled_count}개 포지션 취소 완료 ({mode_text})")
            except Exception as e:
                print(f"Error handling cancel command: {e}")
                self.send_message("⚠️ 포지션 취소 중 오류가 발생했습니다.")
        
        elif command == '/testnet':
            try:
                if self.rsi_monitor.simulation_mode:
                    self.send_message("ℹ️ 현재 시뮬레이션 모드입니다. API 키를 설정해주세요.")
                    return
                
                if self.rsi_monitor.testnet:
                    self.send_message("🔧 현재 테스트넷 모드입니다.")
                else:
                    self.send_message("🚀 현재 실제 거래 모드입니다.")
            except Exception as e:
                print(f"Error handling testnet command: {e}")
                self.send_message("⚠️ 모드 확인 중 오류가 발생했습니다.")
        
        elif command == '/321':
            try:
                self.send_message("4시간봉 321EMA 이격률 계산 중...")
                result = self.rsi_monitor.get_ema_321_proximity()
                if not result:
                    self.send_message("데이터가 부족하거나 계산에 실패했습니다.")
                    return
                message = "📊 <b>4시간봉 321EMA 근접 TOP10</b>\n\n"
                for symbol, price, ema, diff in result:
                    message += f"<b>{symbol}</b>\n현재가: {price:.4f}\n321EMA: {ema:.4f}\n이격률: {diff:.3f}%\n\n"
                self.send_message(message)
            except Exception as e:
                print(f"Error handling /321 command: {e}")
                self.send_message("⚠️ 321EMA 계산 중 오류가 발생했습니다.")
    
    def stop(self):
        """
        봇을 중지합니다.
        """
        self.running = False
        self.command_thread.join() 