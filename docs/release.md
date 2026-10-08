# 检查与打包

本项目仍以私有仓库交付；“public-ready”只表示包采用公开分发候选清单，不会改变 GitHub 可见性，也不替代人工发布审查。

```text
python tools/check_public.py
python -m unittest discover -s tests -v
python tools/build_package.py --output outputs/news-video-batch-open-source.zip
```

默认包只收录根目录明确列出的文档/构建配置、`src/`、`tests/`、`tools/`、`docs/`、`examples/` 和 `.github/` 中允许的文本类型。示例数据位于唯一程序包的 `data/` 目录。真实 `config.json`、`.env`、工作目录、历史、生成物、虚拟环境、媒体、压缩包、二进制、符号链接/目录连接及大文件不进入候选包。源码区域出现未许可的文件类型会令检查失败；用户本地目录在允许列表外，可以保留在工作副本中。

扫描包括 fixture 的 JSON 和源码字面量；测试凭据须明确以 `dummy-`、`fake-`、`test-`、`example-` 等标明人工值。所有 `config.example.json` 的敏感字段必须空白。错误只说明字段/文件，不输出命中的值。自动模式检查不能识别一切商业秘密，因此仍需核对暂存文件：

```text
git diff --cached --stat
git diff --cached
python tools/check_public.py --tracked
```

`--tracked` 在 Git 仓库中检查已跟踪文件（包含已暂存新文件）也属于公开允许列表，防止压缩包检查通过但 Git 提交携带额外文件。

包内 `PACKAGE_MANIFEST.json` 记录每个成员的大小与 SHA256，写完 ZIP 后全部回读验证，包外 `.zip.sha256` 是最终 ZIP 摘要。摘要证明字节一致，不是新闻正确性、外部接入、GUI 效果或业务验收证明。已有输出及校验文件不会被覆盖。

## 显式内部包

只有主动指定参数才加入内部附加内容：

```text
python tools/build_package.py --internal-dir local/internal-notes --output outputs/news-video-private.zip
```

目录由使用者另外准备；本项目从不自动读取旧业务目录。文件名必须含 `private`，manifest 标记 `private-internal`，附加文件置于 `PRIVATE_INTERNAL/` 并附私有说明。附加内容限定为小型 UTF-8 `.md/.txt/.json/.csv`，仍执行敏感内容检查，不承载真实凭据、二进制或历史业务包。此模式仅供另行审核的内部说明等材料；它不产生公开授权。

## Python 分发包与 CI

构建后端固定 `setuptools==80.9.0`，开发辅助 `wheel==0.45.1`，通过 `python -m pip install -r requirements-dev.txt` 安装，运行依赖为空。`MANIFEST.in` 将开发文档、测试、发布工具和 CI 纳入 sdist，避免仅包含测试却缺少其依赖工具；发布时仍须检查每个实际构建产物。来源许可见 [第三方说明](../THIRD_PARTY_NOTICES.md)。在安装这两个构建工具后，可直接调用后端，无需额外构建框架：

```text
python -c "from setuptools.build_meta import build_wheel, build_sdist; build_wheel('dist'); build_sdist('dist')"
python tools/check_public.py --distribution dist/news_video_batch-0.1.0-py3-none-any.whl
python tools/check_public.py --distribution dist/news_video_batch-0.1.0.tar.gz
```

版本变更后使用实际产物名。分发检查读取归档但不解压；拒绝目录穿越、链接、重复/超大条目和未经扫描的文件，程序/示例成员必须与已审查源码逐字节一致，仅允许已知构建元数据。源码 ZIP 是包含开发说明与测试的完整交付，wheel 是运行时安装包。

GitHub Actions 配置 Windows/Linux × Python 3.11/3.13，进行安装、单元测试、环境检查、离线示例及其 manifest 核验、安全检查、源码 ZIP 及 wheel/sdist 检查。独立命令分别作为步骤执行，前一步失败即停止后续步骤；wheel 安装后还会在源码目录外运行示例并核验保存结果。配置存在不等于四个环境已经验证；实际结果以对应提交的 Actions 运行记录为准。CI 不调用钉钉、豆包或剪映，也不自动发布或更改仓库可见性。
