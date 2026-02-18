# xaus — Bitget 黄金永续价差可视化工具

**简介**
- **用途**: 从 Bitget 拉取三个与黄金相关的永续合约（XAU、XAUT、PAXG）的历史价格，计算两两之间的价差并绘制时间序列图，便于观察价差行为与异常。
- **入口文件**: [xaus.py](xaus.py)

**依赖**
- **Python**: 3.8+
- **第三方库**: `ccxt`, `pandas`, `matplotlib`

安装依赖示例：

```bash
pip install ccxt pandas matplotlib
```

**快速开始**

运行默认配置（使用默认代理 `http://127.0.0.1:7890`，周期 `1h`，拉取 500 根 K 线）：

```bash
python xaus.py
```

常用选项示例：

- 使用 1 小时周期并拉取 1000 根 K 线：

```bash
python xaus.py --timeframe 1h --limit 1000
```

- 不使用代理（覆盖默认代理为空字符串）：

```bash
python xaus.py --proxy ""
```

- 不弹出图表（只打印数据摘要）：

```bash
python xaus.py --no-plot
```

更多可用参数请运行：

```bash
python xaus.py --help
```

**环境变量**
- `BITGET_PROXY`: 可选，设置默认 HTTP(S) 代理地址（脚本默认使用 `http://127.0.0.1:7890`，可用 `--proxy` 覆盖）。

**脚本行为说明**
- 会创建一个 ccxt 的 `bitget` 客户端（以 swap/永续市场为目标）。
- 拉取 OHLCV 数据后按时间对齐（仅保留三者都有数据的时间点），并计算三组价差：
  - `XAU_minus_XAUT`
  - `XAU_minus_PAXG`
  - `PAXG_minus_XAUT`
- 默认会用 `matplotlib` 绘图显示价差曲线；如需仅获取数据可使用 `--no-plot`。

**注意事项 & 排错**
- 本脚本只使用公共行情接口，不需要 API Key。
- 如果遇到网络或请求失败，脚本内置有限次数重试（可通过 `--retries` 与 `--retry-delay` 调整）。
- 若你的网络需要代理，请设置 `BITGET_PROXY` 或使用 `--proxy` 参数。要禁用代理，请传入空字符串 `""`。
- 如果拉取不到数据，请检查交易对是否在 Bitget swap 市场可用，或调整 `timeframe` 与 `limit`。

**文件**
- 主脚本：[xaus.py](xaus.py)

---

如果你希望我：生成 `requirements.txt`、把绘图改为保存图片而非弹窗，或把功能封装成函数并写单元测试，请告诉我下一步要做什么。
