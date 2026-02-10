import requests

url = "https://api.elections.kalshi.com/trade-api/v2/markets/KXMETEOR-30"

response = requests.get(url)

print(response.text)