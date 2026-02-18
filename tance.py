import ccxt

exchange = ccxt.bitget({
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap",
    },
    "proxies": {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }
})

exchange.load_markets()

symbols = [s for s in exchange.symbols if "XAU" in s or "XAUT" in s or "PAXG" in s]
print(symbols)
