# 新闻来源、离线文案和在线模型

默认 `local + offline + demo` 完全离线。模型和来源由命令行显式选择；配置中出现凭据不会自动联网。`doctor` 只检查本机文件、格式和所选模式需要的配置，不会验证账号、权限、余额或外部服务可用性。

## 配置与环境变量

运行 `nvbatch init --directory local` 得到可编辑示例；把其中的 `config.example.json` 复制为 `local/config.local.json` 后修改。运行时必须显式传入 `--config local/config.local.json`，程序不查找当前目录、旧项目目录、用户目录或 `.env`，也不迁移旧配置。

示例里的凭据、账号标识、表格标识和模型 ID 均为空。字段映射、超时、分页上限、官方 URL 等是通用程序默认值。配置顶层仅允许 `schema_version`、`dingtalk` 和 `doubao`。未填写的已知字段采用默认值；未知字段、重复 JSON 键、错误类型、控制字符和超出范围的值会报错。

| 配置项 | 用途 / 默认值 | 可覆盖的环境变量 |
|---|---|---|
| `dingtalk.app_key` | 企业内部应用 AppKey，空 | `NVB_DINGTALK_APP_KEY` |
| `dingtalk.app_secret` | 企业内部应用 AppSecret，空 | `NVB_DINGTALK_APP_SECRET` |
| `dingtalk.base_id` | 自己的 AI 表格 baseId，空 | `NVB_DINGTALK_BASE_ID` |
| `dingtalk.sheet_id` | 数据表 ID 或名称，空 | `NVB_DINGTALK_SHEET_ID` |
| `dingtalk.operator_id` | 有权读取表格的操作人 unionId，空 | `NVB_DINGTALK_OPERATOR_ID` |
| `dingtalk.field_mapping` | 下文的字段名映射 | — |
| `dingtalk.page_size` | 每页 100 条，可设 1–100 | — |
| `dingtalk.max_pages` | 最多 20 页，可设 1–100 | — |
| `dingtalk.timeout_seconds` | 单次请求超时 30 秒，可设 1–120 | — |
| `doubao.api_key` | 自己的火山方舟 API Key，空 | `NVB_DOUBAO_API_KEY` |
| `doubao.model` | 已开通的 Model ID 或 Endpoint ID，空 | `NVB_DOUBAO_MODEL` |
| `doubao.endpoint` | 官方北京 Chat Completions URL | — |
| `doubao.timeout_seconds` | 单次请求超时 60 秒，可设 1–120 | — |
| `doubao.max_tokens` | 输出 token 上限 4096，可设 1–16384 | — |

环境变量优先于本地文件；显式空字符串会清空文件中的相应值。只识别表中列出的环境变量，不读取其他产品使用的通用变量。操作系统允许同一用户及子进程读取环境变量，应使用个人受控运行环境。不要把凭据放进截图、问题反馈或命令行参数。

Windows PowerShell 可用隐藏输入临时设置 API Key，避免直接写入命令历史：

```powershell
$nvbSecret = Read-Host '火山方舟 API Key' -AsSecureString
$env:NVB_DOUBAO_API_KEY = [System.Net.NetworkCredential]::new('', $nvbSecret).Password
$env:NVB_DOUBAO_MODEL = Read-Host '已开通的 Model ID 或 Endpoint ID'
nvbatch doctor --config local/config.local.json --model doubao
```

任务结束后可执行 `Remove-Item Env:NVB_DOUBAO_API_KEY`。本地配置仅用于自己的环境，不属于公开包；默认打包采用发布白名单。配置校验和在线异常不会显示配置值或原始服务响应。

## 本地新闻

新闻文件是 UTF-8 JSON 数组，每条包含 `id`、`title`、`summary`、`source`、`date`，可带 `url`。ID 使用 1–64 个 ASCII 字母、数字、下划线或连字符，避免 Windows 设备名；日期为 `YYYY-MM-DD`。单批最多 1000 条，ID 忽略大小写后也必须唯一。新闻的事实、版权和来源由输入提供者确认。

```json
[
  {
    "id": "fictional-library",
    "title": "虚构图书馆开放",
    "summary": "这是虚构示例。图书馆向读者开放。",
    "source": "原创虚构示例",
    "date": "2026-01-01"
  }
]
```

## 离线文案的两种方式

1. **人工示例映射**：新闻中有 `demo_texts` 时，直接使用 `{生成槽位ID: "人工编写文本"}`，必须刚好包含模板的全部 `generated` 槽位，不能带 `fixed` 或其他键。内置演示使用这种方式，证明配置、约束校验、逐片段替换和保存核验，不证明 AI 的事实性或文案质量。
2. **确定性原文摘录**：未提供 `demo_texts` 时，`purpose` 为 `title/headline/标题` 使用标题，`source/来源` 使用来源，`date/日期` 使用日期；其他生成槽位按 `order` 依次使用摘要中不同的句子。句子按中英文句末标点及换行分隔，正文句子不足就报错，不填充、不复用、不截短。该简单拆分不适合含缩写、小数或复杂标点的稿件，可改用人工映射或在线模型。

所有文案最终仍通过模板长度、行数、固定内容和重复规则校验。摘录结果过长时，请编辑输入/人工映射或调整自己模板的约束；程序不为了通过校验而悄悄截断事实。`demo_texts` 只用于离线模式，在线模型不会收到这份人工答案。

## 钉钉 AI 表格读取

适配范围是钉钉 **AI 表格 / notable v1.0** 的企业内部应用，只读；普通电子表格、钉钉消息、机器人推送、附件和富文本不是这一适配器的输入格式。

先创建自己的企业内部应用，申请相应表格读取权限，并让操作人及应用按钉钉要求获得目标表格访问权。账号及租户规则可能不同，权限状态以钉钉控制台和官方文档为准。

默认映射如下。映射值可替换成自己表格的字段名或字段 ID，默认名称没有绑定任何业务表：

```json
"field_mapping": {
  "id": "",
  "title": "title",
  "summary": "summary",
  "source": "source",
  "date": "date",
  "url": ""
}
```

`id` 为空时使用记录自身 ID，也可配置专门的新闻 ID 文本列。`url` 为空表示不读取链接；映射后的可选链接列允许空值。其余列必须为非空纯文本。请把日期准备为 `YYYY-MM-DD` 文本列；日期时间戳、附件、人员、选择项和富文本数组不会被猜测转换。

适配器先以 AppKey/AppSecret 获取 accessToken，再分页读取记录；它使用 `operatorId` 查询参数与 `x-acs-dingtalk-access-token` 请求头。分页用 `hasMore/nextToken`；游标缺失、重复记录、达到 `max_pages` 但仍有数据、超过单批 1000 条或响应形状异常，都会中止整批。不会把前几页误当完整结果。没有自动重试或写回表格。

```powershell
nvbatch doctor --source dingtalk --config local/config.local.json
nvbatch run --source dingtalk --model offline --template local/template.json --config local/config.local.json --output outputs/my-table-demo
```

这条运行命令会读取真实表格。若摘要不够分配所有槽位，请先调整自己的数据和模板，或显式选用 `--model doubao`。

协议核对时间：2026-10-08。来源为[钉钉企业应用令牌文档](https://open.dingtalk.com/document/orgapp/obtain-orgapp-token)、[钉钉官方 SDK 的令牌协议定义](https://github.com/alibabacloud-go/dingtalk/blob/master/oauth2_1_0/client.go)和[官方 SDK 的 ListRecords 协议定义](https://github.com/alibabacloud-go/dingtalk/blob/master/notable_1_0/client.go)。官方网页部分内容依赖脚本，本项目以可读的官方协议定义交叉核对字段和路径；没有复制或依赖 SDK 实现。

## 豆包 / 火山方舟

创建自己的火山方舟 API Key，并填入控制台中实际已开通的 Model ID 或 Endpoint ID。程序不会默认选购、开通或猜测模型。运行 `--model doubao` 会把新闻标题、摘要、来源、日期、可选链接及模板规则发送到火山方舟，可能产生服务费用。

```powershell
nvbatch run --news local/news.json --template local/template.json --model doubao --config local/config.local.json --output outputs/my-model-demo
```

当前只接受 `https://ark.cn-beijing.volces.com/api/v3/chat/completions`，采用 Bearer API Key、非流式 Chat Completions。模型需支持文本 Chat Completions 及本工具使用的 `max_tokens` 参数；不同模型参数和服务限制以控制台文档为准，不承诺所有豆包模型兼容。返回必须是生成槽位 ID 到字符串的纯 JSON 对象，且 `finish_reason` 为 `stop`。缺字段、多字段、修改固定槽位、Markdown 包裹、内容截断或违反槽位约束都会报错，不自动补齐。

接口和认证已按[火山方舟官方 Chat API 文档](https://docs.volcengine.com/docs/ark/chat-api?lang=zh)及[官方 API Explorer](https://api.volcengine.com/api-explorer/?action=ChatCompletions&serviceCode=ark&version=2024-01-01)核对（2026-10-08）。本次交付只做模拟响应测试，未调用真实账号/付费接口；实际权限、具体模型输出质量和当前租户连通性仍需使用者自行小样本验证。

## 连接边界与排错

所有在线请求使用 HTTPS、证书校验和配置的单次超时，每个响应上限 4 MiB；系统/环境配置的代理可能被 Python 标准库使用。所有 HTTP 重定向都拒绝，避免把凭据转发到新地址。超时是单次连接/读取操作的超时，并非整批任务的硬截止；多页读取会累积耗时。

| 现象 | 处理 |
|---|---|
| `configuration is missing` | 按选定模式补齐本地值/环境变量；离线运行无需在线配置 |
| `HTTP 401/403` | 检查自己的密钥、应用权限、操作人和目标资源权限；错误消息不回显服务原文 |
| `HTTP 429` | 查看服务配额/限流，待服务恢复后手动重跑；没有自动重试风暴 |
| `connection failed or timed out` | 检查网络、受控代理和超时；不关闭 TLS 校验 |
| `max_pages reached` | 缩小表格范围或显式增大分页上限；仍受 1000 条批次限制 |
| `mapped columns must contain ... plain text` | 使用文本列或自己先导出为本地 JSON，确认字段名/ID |
| `invalid structured copy` / 槽位校验失败 | 检查模型和模板约束，查看自己的输入；不要把凭据贴到反馈中 |

新增来源实现 `load() -> list[dict]`，新增模型实现 `generate(news, template) -> dict[str,str]`，只返回生成槽位。复用 `domain.validate_news` 和管线的 `validate_texts`，通过现有测试后再添加显式命令行选项。不要直接放宽官方服务域名检查来发送已有密钥给另一个服务。
