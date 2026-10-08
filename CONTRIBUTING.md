# 贡献指南

先阅读 README 和对应 `docs/` 接入说明。问题反馈请使用仓库 Issue 模板，提供 Python/系统版本、最小复现步骤、期望与实际结果；剪映问题同时记录精确版本及是否完成 GUI 人工验收。

## 开发与检查

在 Python 3.11–3.13 虚拟环境中运行：

```text
python -m pip install -r requirements-dev.txt
python -m pip install --no-build-isolation --no-deps -e .
python -m unittest discover -s tests -v
python tools/check_public.py
nvbatch doctor
nvbatch demo --output outputs/contribution-demo
python tools/build_package.py --output outputs/contribution-public.zip
```

示例输出目录必须是新目录。正式提交前暂存具体源文件，再运行 `python tools/check_public.py --tracked`；检查范围包括测试 fixture，不能以“仅用于测试”为由提交真实凭据或真实业务数据。

变更应保持新闻来源、文案模型、草稿输出的分离；新增接入优先注入/模拟网络响应，不让 CI 调用真实账号或付费接口。为有业务含义的失败和回归写测试，包括同一轨道多段文字、共享文本素材、重复与连续字幕规则，以及失败后不留下半成品。

Pull request 说明问题、最终行为、实际验证与尚未验证部分。不要把 JSON 回读核验描述为剪映打开/渲染通过。新素材须附来源、作者、许可和修改说明；不接受来源不明的旧模板、解密器、软件 DLL 或媒体。提交贡献即表示你有权按本仓库 MIT 许可提供该贡献；第三方内容仍须保留其许可。

安全问题请遵循 [SECURITY.md](SECURITY.md)，不要公开凭据或内部链接。
