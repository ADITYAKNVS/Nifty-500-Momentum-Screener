import json

# A basic manual map for the top NSE stocks to their sectors.
# For unmapped stocks we will use "General".
NSE_SECTORS = {
    "TCS": "IT", "INFY": "IT", "HCLTECH": "IT", "WIPRO": "IT", "TECHM": "IT", "LTIM": "IT",
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking", "KOTAKBANK": "Banking", "AXISBANK": "Banking",
    "RELIANCE": "Energy", "ONGC": "Energy", "POWERGRID": "Energy", "NTPC": "Energy", "COALINDIA": "Energy",
    "MARUTI": "Auto", "M&M": "Auto", "TATAMOTORS": "Auto", "BAJAJ-AUTO": "Auto", "HEROMOTOCO": "Auto",
    "TATASTEEL": "Metals", "HINDALCO": "Metals", "JSWSTEEL": "Metals", "VEDL": "Metals",
    "SUNPHARMA": "Pharma", "CIPLA": "Pharma", "DRREDDY": "Pharma", "DIVISLAB": "Pharma",
    "ITC": "FMCG", "HUL": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG", "TATACONSUM": "FMCG",
    "L&T": "Infrastructure",
    "BHARTIARTL": "Telecom"
}

def get_sector(ticker):
    return NSE_SECTORS.get(ticker, "General")

if __name__ == "__main__":
    pass
