# 共享编排步骤

> 引用方：commands/project.md、commands/diff.md

---

## 1. 条件规则加载

按技术栈加载框架安全知识（未检测到的不加载）：

| 触发条件 | 知识文件 |
|--------|---------|
| Java + Spring | `${CODEBUDDY_PLUGIN_ROOT}/resource/knowledge/spring-security.yaml` |
| Java + Spring Actuator | `${CODEBUDDY_PLUGIN_ROOT}/resource/knowledge/actuator-exposure.yaml` |
| Java + MyBatis | `${CODEBUDDY_PLUGIN_ROOT}/resource/knowledge/mybatis-injection.yaml` |
| Python + Flask/Django/FastAPI | `${CODEBUDDY_PLUGIN_ROOT}/resource/knowledge/python-web.yaml` |
| Node.js + Express/Koa/NestJS | `${CODEBUDDY_PLUGIN_ROOT}/resource/knowledge/nodejs-web.yaml` |
| Go + Gin/Echo/Fiber | `${CODEBUDDY_PLUGIN_ROOT}/resource/knowledge/go-web.yaml` |
| 存在认证/鉴权入口 | `${CODEBUDDY_PLUGIN_ROOT}/resource/knowledge/authentication-bypass.yaml` |
| hasPaymentLogic = true | `${CODEBUDDY_PLUGIN_ROOT}/resource/knowledge/payment-logic-rules.yaml` |

知识文件路径记录到 `stage1-context.json > frameworkKnowledge[]`。Agent 按需 Read 相关章节。

**推理优先原则**：知识文件是参考资料，Agent 分析能力不受限于知识文件中列出的风险类型。

---

## 2. 漏洞链检测

合并后分析 `merged-scan.json` 中的跨文件漏洞链：
- 识别多文件攻击路径
- 将同一路径的发现关联为 `vulnerabilityChain` 条目，提升严重级别

---

## 3. WebSearch 情报增强（条件执行）

跳过条件：无 `webSearchCandidate: true` 的 CVE 条目且无 `auditDimension: "C7.7"` 的条目。

**场景一：CVE 实时验证（最多 3 次 WebSearch）**

触发条件：CVE 推理产出为 `severity: "critical"` 或组件主版本落后 >=3。

```
WebSearch: "{component} {version} CVE vulnerability security advisory"
```

结果处理：
- 命中已知 CVE 且版本匹配 -> 提升 severity，补充 CVE 编号
- 发现新 CVE -> 新建 finding，`source: "websearch_validated"`
- 无结果 -> 保持原始推理结果

**场景二：0day 情报感知（最多 2 次 WebSearch）**

触发条件：red-team 在 Q1（自造轮子）发现自定义序列化/加密/过时认证方案。

```
WebSearch: "{framework/library} {version} 0day exploit vulnerability 2025 2026"
```

结果处理：
- 发现相关漏洞 -> 升级 severity，补充 `threatIntelligence` 字段
- 发现在野利用 -> 升级到 `critical`，设置 `activeExploitation: true`
- 无情报 -> 保持 `severity: "info"` + `humanReviewRequired: true`

**预算控制**：合计最多 5 次 WebSearch。优先级：critical CVE > 活跃利用信号 > 高风险组件 > high CVE > C7.7 查询。

**降级策略**：WebSearch 工具不可用或达到配额时，跳过增强，使用纯静态分析。

---

## 4. 覆盖率评估（条件执行）

跳过条件（满足任一）：
- `totalFindings >= 10`
- `fileCount <= 50`
- 扫描 Agent 均为 `status: "completed"` 且 `totalFindings >= 5`

覆盖率维度：C1 注入类 / C2 凭证 / C3 认证授权 / C4 配置 / C5 文件操作 / C6 SSRF/反序列化 / C7 业务逻辑 / C8 依赖 / C9 云安全 / C10 加密

---

## 5. 跨仓库分析（条件执行）

当 `crossRepoDependencies` 非空且含高/严重级别时触发。
通过 AskUserQuestion 获取用户确认后，浅克隆到 `.tmp-cross-repo/` 分析，完成后清理。
