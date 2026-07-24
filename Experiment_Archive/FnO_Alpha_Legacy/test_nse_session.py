import requests

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Connection': 'keep-alive'
})

print("Hitting homepage to seed cookies...")
try:
    session.get("https://www.nseindia.com", timeout=10)
    print("Cookies:", session.cookies.get_dict())
except Exception as e:
    print("Error getting cookies:", e)

# March 27, 2026 was a Friday. 
url = "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/2026/MAR/fo27MAR2026bhav.csv.zip"
print(f"Requesting {url}")
r = session.get(url, timeout=10)
print(f"Status: {r.status_code}")
