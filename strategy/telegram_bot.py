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
                rsi_dict = self.rsi_monitor.get_current_rsi()
                market_cap_order = get_top_coins(30)
                message = "📊 <b>현재 RSI 상태 (1분/15분봉)</b>\n\n"
                for symbol in market_cap_order:
                    if symbol in rsi_dict:
                        m1 = rsi_dict[symbol]['1m']
                        m15 = rsi_dict[symbol]['15m']
                        message += f"<b>{symbol}</b>\n"
                        message += f"  1분봉 RSI(14): {m1['rsi14'] if m1['rsi14'] is not None else '-'}\n"
                        message += f"  1분봉 RSI(7): {m1['rsi7'] if m1['rsi7'] is not None else '-'}\n"
                        message += f"  15분봉 RSI(14): {m15['rsi14'] if m15['rsi14'] is not None else '-'}\n"
                        message += f"  15분봉 RSI(7): {m15['rsi7'] if m15['rsi7'] is not None else '-'}\n\n"
                print("메시지 전송 시도...")
                self.send_message(message)
                print("메시지 전송 완료")
            except Exception as e:
                print(f"Error handling status command: {e}")
                self.send_message("⚠️ RSI 데이터를 가져오는 중 오류가 발생했습니다.")
        
        elif command == '/help':
            message = "🤖 <b>RSI 모니터링 봇 명령어</b>\n\n" \
                     "/status 또는 /rsi - 현재 RSI 상태 확인 (1분/15분봉)\n" \
                     "/help - 도움말 보기"
            self.send_message(message)
    
    def stop(self):
        """
        봇을 중지합니다.
        """
        self.running = False
        self.command_thread.join() 