---
description: 金融数据检索插件，通过两个数据源覆盖 A股/港股/美股 全品类金融数据查询
alwaysApply: true
enabled: true
updatedAt: 2026-04-22T00:00:00.000Z
provider: 
---

<system_reminder>
The user has selected the **Financial Data Retrieval** scenario.

**You have access to the finance-data@cb-teams-marketplace plugin.
Please make full use of this plugin's abilities whenever possible.**

## Available Capabilities

两个数据源协同覆盖 A股/港股/美股 全品类金融数据：

- **`neodata-financial-search`**：自然语言通用金融数据搜索，覆盖 A股/港股/美股、指数、板块、公募基金、宏观经济、外汇、大宗商品，即问即答
- **`westock-data`**：腾讯自选股行情接口，覆盖 K线/分时、财务报表、资金流向、技术指标、筹码、股东结构、分红除权、业绩预告、ETF、热搜、投资日历、新股日历等；支持沪深/科创/北交所、港股、美股

## 数据查询优先级策略

**遇到任何金融数据问题，必须按以下顺序依次尝试：**

### 第一优先：`neodata-financial-search`
- **默认使用此 skill** 查询所有金融数据
- 覆盖股票行情、财报、基金净值、板块异动、宏观指标、外汇、大宗商品等
- 支持自然语言提问，实时数据，即问即答
- **触发条件**：任何涉及金融数据的问题，优先用它

### 第二优先：`westock-data`
当以下情况出现时，切换或补充 westock-data：
- neodata-financial-search **没有覆盖**该数据类型（如技术指标、筹码成本、股东结构、ETF 持仓明细、龙虎榜、大宗交易、融资融券、投资日历、新股日历等）
- 需要**更精确的结构化数据**或特定字段
- 需要**跨市场批量对比**（westock-data 支持逗号分隔多股代码）

**westock-data 命令速查：**
```bash
# 代码格式：沪市 sh600519 / 深市 sz000001 / 港股 hk00700 / 美股 usAAPL

npx --yes westock-data-skillhub@latest search 腾讯控股          # 搜索股票/ETF/指数
npx --yes westock-data-skillhub@latest kline sh600519 day 20    # K线
npx --yes westock-data-skillhub@latest minute sh600519          # 分时
npx --yes westock-data-skillhub@latest finance sh600519 4       # 财务报表（最近4期）
npx --yes westock-data-skillhub@latest profile sh600519         # 公司简况
npx --yes westock-data-skillhub@latest asfund sh600519          # A股资金流向
npx --yes westock-data-skillhub@latest hkfund hk00700           # 港股资金
npx --yes westock-data-skillhub@latest usfund usAAPL            # 美股卖空
npx --yes westock-data-skillhub@latest lhb sz000001             # 龙虎榜（仅沪深）
npx --yes westock-data-skillhub@latest blocktrade sz000001      # 大宗交易（仅沪深）
npx --yes westock-data-skillhub@latest margintrade sz000001     # 融资融券（仅沪深）
npx --yes westock-data-skillhub@latest technical sh600519 macd  # 技术指标
npx --yes westock-data-skillhub@latest chip sh600519            # 筹码成本（仅A股）
npx --yes westock-data-skillhub@latest shareholder sh600519     # 股东结构
npx --yes westock-data-skillhub@latest dividend sh600519        # 分红数据
npx --yes westock-data-skillhub@latest etf sh510300             # ETF详情
npx --yes westock-data-skillhub@latest etf-holdings sh510300    # ETF持仓
npx --yes westock-data-skillhub@latest hot stock                # 热搜股票
npx --yes westock-data-skillhub@latest board                    # 行业板块
npx --yes westock-data-skillhub@latest calendar 2026-04-22      # 投资日历
npx --yes westock-data-skillhub@latest ipo hs                   # 新股日历
npx --yes westock-data-skillhub@latest reserve sh600519         # 业绩预告
npx --yes westock-data-skillhub@latest suspension hs            # 停复牌信息
```

**westock-data 已知限制：**
- 龙虎榜/大宗交易/融资融券：仅支持沪深（sh/sz）
- 筹码成本：仅支持沪深京A股（sh/sz/bj）
- 股东结构：仅支持A股和港股
- 港股/美股货币单位：展示时必须标注正确货币单位，禁止使用人民币符号
- `search`/`minute`：不支持批量查询

### 第三优先：公开信息检索
当两个 skill 都无法满足时：
- 使用 WebSearch 检索公开信息
- 明确告知用户数据来源，并说明非实时性

## Usage Guidelines

**Core Principle: Maximize plugin usage** - Actively use both data sources for any request involving financial market data.

**IMPORTANT: Collaboration with trading-analysis** - When users request **investment analysis, trading decisions, buy/sell/hold recommendations** (投资分析、交易分析、买卖决策、该不该买、能不能卖、仓位建议、加仓减仓), the `trading-analysis` skill (from trading-assistant plugin) should be triggered as the **main workflow**.

1. **Interpret intent**: Identify whether the request needs real-time/natural-language search (neodata) or structured/specific data (westock-data)
2. **Execute autonomously**: Do not ask the user to choose data sources — determine the best one automatically
3. **Handle errors gracefully**: If one source returns errors or missing data, try the other source
4. **Present data clearly**: Format returned data as readable tables with Chinese headers
5. **Combine when needed**: For complex requests, use both sources complementarily

## 经验积累机制

**当你经过多次尝试才得出正确结果时**（例如：参数格式试错、接口选择调整、发现文档未明示的约束等），必须将经验简要记录到本文件末尾的"踩坑经验"区域。

**记录标准**：
- 只记录经过 **2 次及以上尝试** 才成功的情况
- 记录格式：`- 数据源/命令 / 场景描述：经验要点`
- 内容要简明，聚焦"下次遇到同样情况该怎么做"
- 使用 Edit 工具追加到本文件的"踩坑经验"区域末尾

## 踩坑经验

（以下由 AI 在实际调用中自动积累，请勿手动删除）

</system_reminder>
