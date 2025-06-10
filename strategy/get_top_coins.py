import requests
import pandas as pd

def get_top_coins(limit=10):
    """
    시가총액 기준 상위 코인 목록을 가져옵니다.
    """
    try:
        # Binance API를 통해 시가총액 정보 가져오기
        url = "https://api.binance.com/api/v3/ticker/24hr"
        response = requests.get(url)
        data = response.json()
        
        # DataFrame으로 변환
        df = pd.DataFrame(data)
        
        # USDT 마켓만 필터링
        df = df[df['symbol'].str.endswith('USDT')]
        
        # 시가총액 계산 (가격 * 거래량)
        df['marketCap'] = df['quoteVolume'].astype(float)
        
        # 시가총액 기준 정렬 및 상위 코인 선택
        top_coins = df.nlargest(limit, 'marketCap')
        
        return top_coins['symbol'].tolist()
    except Exception as e:
        print(f"Error getting top coins: {e}")
        return [] 