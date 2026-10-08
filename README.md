# 新闻视频批量生成：原版整理版

沿用原版 v2.1.1 的剪映草稿流程，新增已确认的入口：**输入一段文字 → 用户配置的模型 API → 按模板生成独立文案 → 创建剪映草稿**。

保留模板注册/选择/管理、素材池取用、批量成功失败报告和文字回读核验。只创建草稿，不自动导出 MP4 或发布。仓库默认私有；源码公开准备不等于已经公开。

## Windows 首次配置

本次本机完整测试使用 Windows、Python 3.11.9、剪映专业版 **10.5.0.13988**。其他剪映版本需要自行验证，不沿用旧注释中的范围作为本次验收结论。需要自行安装剪映并准备有权使用的模板及素材。

在项目目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

源码包不附 Python、剪映、业务模板、媒体或账号配置。首次安装依赖需要联网。原版自带 runtime 的内部副本仍可用；启动脚本优先选本目录 `.venv`，其次选本目录 `runtime`。

## 输入文字生成草稿

1. 双击 `模板管理.bat`，注册你自己剪映中的可用模板，记住注册名称。原有模板注册与本地化逻辑保留。
2. 将 `examples/model_api.example.json` 复制到项目根目录并命名为 `model_api.local.json`；填写完整 HTTPS Chat Completions 地址、API Key 和模型名称。模型标识按服务商要求填写，不固定为豆包。
3. 把原始材料保存成 UTF-8 文本文件。可使用 `examples/输入材料.txt` 测试；它是虚构材料。
4. 双击 `输入文字生成草稿.bat`，按提示输入文件路径、模板名称与配置路径。
5. 到剪映逐条检查文字、媒体、播放和编辑，再决定是否导出。

也可用命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 引擎/text_input.py --text-file examples/输入材料.txt --api-config model_api.local.json --template 默认 --generate-drafts
```

将 `默认` 换成你的注册模板名称；含空格时加双引号。`--text "一段材料"` 可替代 `--text-file`。去掉 `--generate-drafts` 只生成原版 `info.txt` 输入文件。每次运行仅处理这次新生成的输入，重复运行会新建草稿。

API 使用你自己的账户与额度。支持 Bearer 认证、非流式 Chat Completions 和文字响应；不承诺所有服务商都兼容，不支持 Responses 接口。输入文字上限 30000 字符。没有网络自动重试；原版重复文案会重试一次，因此可能多一次调用。豆包官方北京接口保留关闭深度思考参数，其余地址不带该参数。

可用 `NVB_API_ENDPOINT`、`NVB_API_MODEL`、`NVB_API_API_KEY` 环境变量覆盖配置；程序不显示密钥，不自动读取别的项目配置。正文的字数、行数和连续片段要求沿用原版提示与核验；没有新增完整视觉排版或事实核验，仍需检查成稿。

## 素材

素材池按原版在 `素材库/锂电行业`、`素材库/电池`、`素材库/新能源`、`素材库/默认` 取用。素材不足时可能保留模板原画面；短视频素材可能留空，具体看生成报告。

## 不调用 API 的原创示例

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/demo.py --output outputs/original-demo
```

通过保留的原版草稿写入器生成两条原创虚构、纯文字、连续两段的明文草稿，并逐槽位回读核验。不会启动剪映、不调用 DLL、不写剪映草稿目录、不调用 API。它用于验证安装和文字写入，不能代替剪映内验收，也不包含业务模板样式。

## 验证与分发

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s 引擎/tests
.\.venv\Scripts\python.exe -X utf8 tools/check_public.py
.\.venv\Scripts\python.exe -X utf8 tools/build_package.py --output outputs/news-video-batch-source.zip
```

公开包只选择明确允许的源码、示例、文档和许可证；拒绝符号链接/目录联接、异常大文件及匹配到的敏感内容。会回读 ZIP 检查每个文件的哈希。真实配置、模板库、素材库、runtime、历史输入、报告、状态库和本机输出不打包。扫描不是资产授权证明。

同名输出不覆盖。完整验收范围见 [验证记录](docs/validation.md)，原版与当前变化见 [改动清单](docs/changes.md)。

## 许可和来源

项目自身代码采用 [MIT](LICENSE)。保留的 `pyJianYingDraft` 来自固定上游提交，44 个代码/JSON文件与原版逐文件一致，按其 [Apache-2.0](引擎/pyJianYingDraft/LICENSE) 分发。剪映 DLL 不分发。详见 [第三方说明](THIRD_PARTY_NOTICES.md)。

旧业务模板、媒体、账号、历史数据不会因为代码开源而获得再分发授权。你需要自行提供可使用的素材。软件名称仅说明接入对象，不代表官方授权或合作。
