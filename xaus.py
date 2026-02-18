# 这个脚本的目标：
# 1) 从 Bitget 拉取 3 个黄金相关永续合约的价格
# 2) 计算它们之间的价差
# 3) 把价差画成曲线，方便观察是否有规律

import argparse
import logging
import os
import time
from typing import Dict

import ccxt
from ccxt.base.errors import ExchangeError, NetworkError, RequestTimeout
import matplotlib.pyplot as plt
import pandas as pd

# 默认代理：在受限网络环境下，默认就走本地代理。
# 你也可以通过环境变量 BITGET_PROXY 覆盖它。
DEFAULT_PROXY = os.getenv("BITGET_PROXY", "http://127.0.0.1:7890")
DEFAULT_TIMEFRAME = "1h"
DEFAULT_LIMIT = 500

# 这里定义我们要分析的 3 个交易对：
# key 是我们自己的简称，value 是 ccxt 识别的标准 symbol
DEFAULT_SYMBOLS: Dict[str, str] = {
    "XAU": "XAU/USDT:USDT",
    "XAUT": "XAUT/USDT:USDT",
    "PAXG": "PAXG/USDT:USDT",
}


# 解析命令行参数（运行 python xaus.py --help 可以看到这些参数）
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Bitget perpetual prices and plot gold spread series."
    )

    # K 线周期，例如 1m、5m、1h、1d
    parser.add_argument(
        "--timeframe",
        default=DEFAULT_TIMEFRAME,
        help=f"OHLCV timeframe, default: {DEFAULT_TIMEFRAME}. e.g. 1m/5m/1h/4h/1d",
    )

    # 一次拉取多少根 K 线
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Number of OHLCV candles to fetch, default: {DEFAULT_LIMIT}",
    )

    # 单次请求超时（毫秒）
    parser.add_argument("--timeout-ms", type=int, default=30000, help="Exchange request timeout in milliseconds")

    # 网络抖动时最多重试次数
    parser.add_argument("--retries", type=int, default=3, help="Retries for transient API failures")

    # 每次重试前等待多久（秒）
    parser.add_argument("--retry-delay", type=float, default=2.0, help="Seconds to wait between retries")

    # 代理地址。优先级：命令行 --proxy > 环境变量 BITGET_PROXY > 默认 127.0.0.1:7890
    # 如果你临时不想使用代理，可以传：--proxy ""
    parser.add_argument(
        "--proxy",
        default=DEFAULT_PROXY,
        help="HTTP(S) proxy URL. Default: http://127.0.0.1:7890",
    )

    # 如果不想弹出图表窗口，可以加 --no-plot
    parser.add_argument("--no-plot", action="store_true", help="Do not show matplotlib chart")

    return parser.parse_args()


# 创建交易所客户端对象（这里只配置 Bitget + swap 永续）
def create_exchange(timeout_ms: int, proxy: str) -> ccxt.bitget:
    config = {
        # 让 ccxt 自动做请求频率控制，减少被限流概率
        "enableRateLimit": True,
        "timeout": timeout_ms,
        "options": {
            # 指定默认使用永续/合约市场
            "defaultType": "swap",
            # 某些网络环境下拉 currencies 可能不稳定，关闭可减少初始化失败
            "fetchCurrencies": False,
        },
    }

    # 只有你传了 proxy 才设置代理，避免硬编码
    if proxy:
        config["proxies"] = {"http": proxy, "https": proxy}

    exchange = ccxt.bitget(config)

    # 双保险：不同版本 ccxt 对该选项的读取路径可能不同。
    # 显式设置可以最大限度避免 load_markets 时请求 currencies 接口。
    exchange.options["defaultType"] = "swap"
    exchange.options["fetchCurrencies"] = False
    if isinstance(exchange.has, dict):
        exchange.has["fetchCurrencies"] = False

    return exchange


# 通用重试函数：把任何“可能暂时失败”的操作包一层重试
# func: 要执行的函数
# retries: 最多尝试几次
# retry_delay: 两次尝试间隔
# action_name: 日志里显示的动作名，便于排查

def call_with_retry(func, retries: int, retry_delay: float, action_name: str):
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            return func()
        except (NetworkError, RequestTimeout, ExchangeError) as err:
            last_error = err
            logging.warning("%s failed (%d/%d): %s", action_name, attempt, retries, err)

            # 还没到最后一次就等待再试
            if attempt < retries:
                time.sleep(retry_delay)

    # 全部失败后抛出统一错误
    raise RuntimeError(f"{action_name} failed after {retries} attempts") from last_error


# 加载市场信息（symbol 列表、精度等），并带重试
def load_markets_with_retry(exchange: ccxt.bitget, retries: int, retry_delay: float) -> None:
    # 强制只加载 swap 市场，避免触发 spot market 的接口请求。
    # 在某些网络环境里，spot/public/symbols 更容易连接失败。
    def _load_swap_markets():
        return exchange.load_markets(
            reload=True,
            params={
                "type": "swap",
                "productType": "USDT-FUTURES",
            },
        )

    call_with_retry(
        func=_load_swap_markets,
        retries=retries,
        retry_delay=retry_delay,
        action_name="load_markets",
    )


# 校验我们想要的 symbol 是否真的存在于当前交易所市场中
def validate_symbols(exchange: ccxt.bitget, symbols: Dict[str, str]) -> None:
    missing = [symbol for symbol in symbols.values() if symbol not in exchange.markets]
    if missing:
        raise ValueError(f"Symbols not available on Bitget swap market: {missing}")


# 拉取单个交易对的收盘价序列
# 返回值是 pandas Series，索引是时间，值是 close

def fetch_close_series(
    exchange: ccxt.bitget,
    symbol: str,
    timeframe: str,
    limit: int,
    retries: int,
    retry_delay: float,
) -> pd.Series:
    # 把“怎么拉取 K 线”定义成一个小函数，方便传给重试器
    def _fetch_ohlcv():
        return exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    ohlcv = call_with_retry(
        func=_fetch_ohlcv,
        retries=retries,
        retry_delay=retry_delay,
        action_name=f"fetch_ohlcv({symbol})",
    )

    # 交易所返回空数据时直接报错，避免后续静默算错
    if not ohlcv:
        raise ValueError(f"No OHLCV data returned for {symbol}")

    # ccxt 返回结构：[timestamp, open, high, low, close, volume]
    df = pd.DataFrame(
        ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )

    # 时间戳单位是毫秒，转成 UTC 时间，避免时区混乱
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

    # 设置时间为索引，后面多个交易对按时间对齐会更方便
    df.set_index("timestamp", inplace=True)

    # 这里只做价差分析，所以只返回 close 列
    return df["close"]


# 拉取全部交易对并按时间对齐，得到一个总表
# 表结构大概是：index=timestamp，columns=[XAU, XAUT, PAXG]
def build_price_df(
    exchange: ccxt.bitget,
    symbols: Dict[str, str],
    timeframe: str,
    limit: int,
    retries: int,
    retry_delay: float,
) -> pd.DataFrame:
    series_list = []

    for alias, symbol in symbols.items():
        close_series = fetch_close_series(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            retries=retries,
            retry_delay=retry_delay,
        )

        # 给每列命名为 XAU / XAUT / PAXG
        close_series.name = alias
        series_list.append(close_series)

    # join="inner"：只保留三者都有数据的时间点，保证比较公平
    price_df = pd.concat(series_list, axis=1, join="inner")

    if price_df.empty:
        raise ValueError("Joined price dataframe is empty. Check symbols/timeframe/limit.")

    return price_df


# 在价格表中新增 3 列“价差”
def add_spreads(price_df: pd.DataFrame) -> pd.DataFrame:
    price_df["XAU_minus_XAUT"] = price_df["XAU"] - price_df["XAUT"]
    price_df["XAU_minus_PAXG"] = price_df["XAU"] - price_df["PAXG"]
    price_df["PAXG_minus_XAUT"] = price_df["PAXG"] - price_df["XAUT"]
    return price_df


# 绘制价差曲线
def plot_spreads(price_df: pd.DataFrame) -> None:
    plt.figure(figsize=(14, 8))

    # 每条线表示一组价差
    plt.plot(price_df.index, price_df["XAU_minus_XAUT"], label="XAU - XAUT")
    plt.plot(price_df.index, price_df["XAU_minus_PAXG"], label="XAU - PAXG")
    plt.plot(price_df.index, price_df["PAXG_minus_XAUT"], label="PAXG - XAUT")

    # y=0 参考线：方便你看价差是正还是负
    plt.axhline(0, linestyle="--", alpha=0.5)

    plt.title("Bitget Gold Perpetual Spreads")
    plt.xlabel("Time (UTC)")
    plt.ylabel("Price Difference (USDT)")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()


# 主流程函数：串起“解析参数 -> 拉数据 -> 算价差 -> 画图”
def main() -> int:
    args = parse_args()

    # 设置日志格式，便于查看运行过程和报错
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    logging.info("Program running")
    logging.info("timeframe=%s limit=%s", args.timeframe, args.limit)

    # 创建交易所对象
    exchange = create_exchange(timeout_ms=args.timeout_ms, proxy=args.proxy)

    # 初始化市场信息并校验交易对
    load_markets_with_retry(exchange, retries=args.retries, retry_delay=args.retry_delay)
    validate_symbols(exchange, DEFAULT_SYMBOLS)

    # 拉取价格并计算价差
    price_df = build_price_df(
        exchange=exchange,
        symbols=DEFAULT_SYMBOLS,
        timeframe=args.timeframe,
        limit=args.limit,
        retries=args.retries,
        retry_delay=args.retry_delay,
    )
    price_df = add_spreads(price_df)

    # 打印一些结果，让你不画图也能看到数据
    logging.info("Fetched %d aligned rows", len(price_df))
    logging.info("Latest row:\n%s", price_df.tail(1).to_string())

    # 默认画图；传 --no-plot 则跳过
    if not args.no_plot:
        plot_spreads(price_df)

    return 0


# 只有“直接运行这个文件”时，才执行 main()
# 如果这个文件被别的文件 import，不会自动跑，便于复用和测试
if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as err:
        # 捕获未处理异常并打印堆栈日志
        logging.exception("Fatal error: %s", err)
        raise SystemExit(1)
