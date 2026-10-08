# 新闻视频批量生成工具 · 开源准备版

把本地新闻批量转换为独立文字片段、时间轴草稿、字幕和可直接打开的离线预览。默认不联网、不需要账号、模型 API、剪映或付费服务。钉钉来源、豆包模型和明文剪映草稿是显式选择的接入能力。

**当前交付是草稿生产工具，不会渲染 MP4。** 离线示例能验证读取新闻 → 填充槽位 → 规则校验 → 逐片段输出 → 保存后核验；不能据此判断新闻事实准确、视频视觉效果或某个剪映版本兼容。仓库保持私有，代码及原创示例已按 MIT 做分发准备，改为公开需要仓库所有者另行决定。

## 1. 第一次运行（Windows PowerShell）

准备 Python **3.11–3.13**，解压源码包或克隆本仓库，然后进入含 `pyproject.toml` 的目录。开发机器实际测试版本见 [验证记录](docs/validation.md)。不提供捆绑 Python、剪映安装包、业务素材或账号。

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m news_video_batch doctor
.\.venv\Scripts\python.exe -m news_video_batch demo --output outputs/demo
.\.venv\Scripts\python.exe -m news_video_batch verify outputs/demo
```

无需激活虚拟环境，避免 PowerShell 执行策略问题。安装阶段可能需要下载已固定的构建工具；**演示运行完全离线**。在虚拟环境已激活时，也可将 `python -m news_video_batch` 简写成 `nvbatch`。

只有 Python、完全断网的电脑可直接从已解压源码运行，无需 pip 安装：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m news_video_batch doctor
python -m news_video_batch demo --output outputs/offline-demo
python -m news_video_batch verify outputs/offline-demo
```

Linux 的安装和命令相同，将虚拟环境解释器路径换为 `.venv/bin/python`；完全离线时用 `PYTHONPATH=src python -m news_video_batch demo --output outputs/demo`。macOS 尚未单独验证，不宣称已适配。

成功后会看到 `PASS`，并得到两条**原创虚构新闻**，每条九个文字槽位。直接双击 `outputs/demo/demo-library/preview.html` 即可拖动时间轴或播放文字预览，不需要启动服务器。

| 输出 | 用途 |
| --- | --- |
| 每条新闻的 `preview.html` | 离线文字和时间预览；不是剪映画面复刻 |
| `draft.json` | 本项目的可读草稿格式；不是剪映原生草稿 |
| `texts.json` | 固定内容与生成内容的最终映射 |
| `captions.srt` | 只导出声明了 `sequence` 的连续字幕 |
| 整批 `manifest.json` | 模式、数量、验证范围及各文件 SHA256 |

同名输出目录不会覆盖。重跑请用新名称，如 `outputs/demo-2`。整批中任何新闻不合格时，命令失败，清除本次临时批次，不留下看似成功的半批结果。`verify` 检查保存文件的完整性，不代表真实性或业务验收。

## 2. 换成自己的新闻和模板

先把随安装包提供的原创示例复制到新的本地目录：

```powershell
.\.venv\Scripts\python.exe -m news_video_batch init --directory local
# 编辑 local/news.json、local/template.json；保留原始示例便于对照。
.\.venv\Scripts\python.exe -m news_video_batch doctor --news local/news.json --template local/template.json
.\.venv\Scripts\python.exe -m news_video_batch run --news local/news.json --template local/template.json --output outputs/my-batch
```

新闻文件是 UTF-8 JSON 数组，每条必填 `id`、`title`、`summary`、`source`、`date`；`date` 为 `YYYY-MM-DD`，`id` 只能用英文字母、数字、下划线或连字符，且整批唯一。可选 `url` 用于记录来源，不自动抓取网页。单批最多 1000 条，文件最多 8 MiB。

```json
[
  {
    "id": "my-news-001",
    "title": "请填写有来源的标题",
    "summary": "请填写已确认的事实摘要。不要把占位文字当真实新闻运行。",
    "source": "请填写来源",
    "date": "2026-01-01"
  }
]
```

离线模型是**确定性替身**：演示的 `demo_texts` 是人工编写的全部生成槽位内容，便于重复验证，并非真实 AI 输出。自有新闻可以提供 `demo_texts` 来试排自己写的文案；没有它时，离线模型按槽位顺序逐句摘录摘要，特殊用途 `title`/`headline`/`标题`、`source`/`来源`、`date`/`日期`分别使用对应字段。它不润色、不自动换行、不为了满足长度而截断事实；句子不足或不符合模板限制会报错。需要改写时显式接入豆包或实现自己的 `generate(news, template)` 模型。

## 3. 文字槽位规则

每个槽位只对应一个 `(track, segment)`，索引从 0 开始；剪映中 `track` 只统计文字轨道。所有槽位 `id` 唯一，`order` 必须从 1 连续排列，明确文案生成和预览顺序，不能把整条轨道合并成一个文字字段。

| 字段 | 规则 |
| --- | --- |
| `purpose` | 说明用途，例如前屏事件、后屏进展、连续字幕第几句 |
| `mode` | `fixed` 直接用 `text`；`generated` 必须由文案模型返回 |
| `allow_repeat` | 只有重复双方都设为 `true` 才允许相同文字；品牌首尾可重复，正文默认不可重复 |
| `max_chars` | 总字数上限，换行不计入；按 Unicode 码点计数，不等于视觉宽度 |
| `max_lines` / `exact_lines` | 最大行数 / 可选的精确行数 |
| `max_chars_per_line` | 每行字数上限；不进行自动截断或偷偷重排 |
| `start_ms` / `duration_ms` | 非负起点、正时长，以毫秒计，同轨道片段不得重叠 |
| `sequence` / `sequence_index` | 连续字幕组及组内从 1 开始的序号；同轨道相邻片段、时间无间隙、顺序递增 |

生成字段不能改变固定字段。正文重复比较忽略空白和大小写；规则只能识别文字重复，不能证明语义衔接或事实准确。JSON 中写 `\n` 表示实际换行，不能提供双重转义的字面 `\\n`。示例用固定品牌首尾重复、两段不同正文和三句连续字幕覆盖核心场景。

模板和示例在唯一有效代码目录 `src/news_video_batch/` 中随包安装；没有 `_v2`、引擎副本或业务版依赖。原业务版的 9/13/6 字段规模仅用于合成回归测试，原始业务模板、媒体和历史草稿未复制。

## 4. 接入钉钉、豆包和剪映

`init` 生成的 `config.example.json` 里凭据、账号标识和模型标识全空。需要在线能力时，将其复制为 `local/config.local.json`，只填写自己的配置。支持环境变量覆盖，配置读取优先级为默认值 → 显式 `--config` → 支持的环境变量。不会自动寻找旧项目或当前目录下的 `config.json`。

```powershell
.\.venv\Scripts\python.exe -m news_video_batch doctor --config local/config.local.json --source dingtalk --model doubao
.\.venv\Scripts\python.exe -m news_video_batch run --config local/config.local.json --source dingtalk --model doubao --template local/template.json --output outputs/online-batch
```

`doctor` 只检查本地格式及选定接入的必填项，不验证服务授权或余额。上面的 `run` 会读取真实钉钉数据，并把新闻和模板要求发送给豆包；需自行准备服务权限及可能产生的用量费用。本次验收没有使用真实账号或付费请求。

- [新闻来源与模型配置](docs/integrations.md)：支持的钉钉 AI 表格列类型、字段映射、分页上限、豆包端点和全部环境变量。
- [剪映接入说明与限制](docs/jianying.md)：只支持用户自有、明文、受限结构的模板；不支持加密或富文本复杂模板。不调用剪映程序、不自动写入安装目录、不提供视频渲染。保存后的 JSON 核验与剪映内打开播放是不同验收步骤。

```powershell
.\.venv\Scripts\python.exe -m news_video_batch run --news local/news.json --template local/template.json --export jianying --jianying-template local/my-plaintext-template --output outputs/jianying-trial
```

这条命令将受支持的 `draft_content.json` 与引用素材复制到新的输出目录，再逐片段写入。必须匹配用户模板的完整文字覆盖和原始时间，拒绝外部素材绝对路径和不支持的样式。**目前没有任何真实剪映版本的 GUI 兼容认证**；即使结构校验通过，仍需在自己的合法授权模板和实际剪映版本中试开、播放、核查资源、保存并导出一条样片。

## 5. 常见排错

| 现象 | 处理 |
| --- | --- |
| 找不到 Python / 模块 | 核对 3.11–3.13、当前源码目录与虚拟环境解释器；断网方式确认 `PYTHONPATH` 指向 `src` |
| pip 下载失败 | 离线示例可直接用上面的 `PYTHONPATH` 方法；不要为此关闭 TLS 验证 |
| 输出目录已存在 | 指定新目录；程序不会覆盖旧结果 |
| 文案字段、字数、行数或重复错误 | 对照 `template.json` 和 `demo_texts`，修正文案或明确调整自己的模板规则 |
| 钉钉字段不是纯文本或日期无效 | 按接入文档修正列映射和日期；富文本/人员/链接对象需要先转换，不进行猜测 |
| HTTP 401/403/429、超时或重定向 | 核查自己的账号权限、限额、网络与官方端点；错误信息不打印响应正文和凭据 |
| 剪映模板被拒绝或打不开 | 先看明文结构、完整槽位映射和本地素材限制；结构通过仍不等于该版本可打开 |
| 中途失败 | 本次临时批次会清理；修正输入后换新目录重跑，无定时任务或后台无限重试 |

反馈请按[贡献指南](CONTRIBUTING.md)附操作步骤、版本及已脱敏的最小输入；不要提交真实配置、账号标识、业务新闻或私人模板。

## 6. 开发、测试和安全分发

运行时依赖仅为 Python 标准库；构建工具固定版本见 `pyproject.toml` 和 [第三方说明](THIRD_PARTY_NOTICES.md)。在源码根目录运行：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m unittest discover -s tests -v
python tools/check_public.py
python tools/build_package.py --output outputs/news-video-batch-open-source.zip
```

公开准备包采用文件允许清单与内容扫描，默认不包含真实配置、历史数据、输出、缓存、虚拟环境或大二进制。`.gitignore` 是第一层保护，打包器不会仅依赖它。只有显式选择内部附加目录才会打内部包，详见[发布说明](docs/release.md)。内部包不能用于公开发布，安全扫描也不能替代人工确认来源与授权。

CI 在 Windows/Linux、Python 3.11/3.13 上执行测试、安装、离线示例、安全扫描和分发检查。已完成的实际结果与未验证项见[验证记录](docs/validation.md)。

代码入口为 `cli.py`，业务约束在 `domain.py`，来源/模型在 `providers.py`，批次控制在 `pipeline.py`，输出在 `exporters.py`。扩展来源实现 `load() -> list[dict]`，扩展模型实现 `generate(news, template) -> dict[str,str]`，输出适配器必须保存后逐槽位核验，返回验证范围；所有输出必须继续经过公共约束验证。

本项目采用 [MIT License](LICENSE)，原创示例授权详见包内 `data/ASSETS.txt`。剪映、钉钉和豆包是各自所有者的产品，本项目不包含其软件或素材，不代表官方授权或合作。旧业务版中无法确认完整来源版本的第三方副本已排除，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
