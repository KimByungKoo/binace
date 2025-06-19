import requests

def get_top_coins(top_n=10):
    """
    바이낸스 24시간 거래대금(USDT 기준) 상위 top_n 코인 심볼 리스트 반환
    """
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            # USDT 마켓만 필터링 (선물/현물 구분 없이 USDT 페어)
            usdt_pairs = [item for item in data if item['symbol'].endswith('USDT') and not item['symbol'].endswith('BUSDUSDT')]
            # 거래대금(quoteVolume, USDT 기준) 내림차순 정렬
            sorted_pairs = sorted(usdt_pairs, key=lambda x: float(x['quoteVolume']), reverse=True)
            # 상위 top_n개 심볼 반환
            top_symbols = [item['symbol'] for item in sorted_pairs[:top_n]]
            return top_symbols
        else:
            print(f"Error fetching 24hr ticker data: {response.text}")
            return []
    except Exception as e:
        print(f"Error fetching top coins by volume: {e}")
        return []

if __name__ == "__main__":
    print(get_top_coins(30)) 