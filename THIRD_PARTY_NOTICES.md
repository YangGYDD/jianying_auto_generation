# 来源与第三方说明

核查日期：2026-10-08。这里区分实际使用的组件与只用于来源核查的旧组件。

## 本仓库分发的内容

本仓库程序、文档、虚构示例新闻、模板结构与 SVG 图形为本次独立实现/创作，按根目录 [MIT LICENSE](LICENSE) 分发。样例不是转载新闻，不包含旧业务模板、商标、音视频、字体、账号配置或历史数据。第三方产品名称仅用于说明接入对象。示例资产说明见包内 `data/ASSETS.txt`。

运行依赖为 Python 标准库；不复制、内嵌第三方 Python 包，也不分发 Python 解释器。Python 3.11–3.13 适用其 [PSF 许可及组件声明](https://docs.python.org/3.11/license.html)，安装者自行从可信来源安装。

## 构建与 CI 工具

| 组件 | 固定版本/引用 | 上游许可证据 | 使用方式 |
| --- | --- | --- | --- |
| setuptools | 80.9.0 | [该版本 LICENSE（MIT 条款）](https://github.com/pypa/setuptools/blob/v80.9.0/LICENSE) | Python 构建后端；由 pip 安装，不随源码 ZIP 分发 |
| wheel | 0.45.1 | [该版本 MIT LICENSE](https://github.com/pypa/wheel/blob/0.45.1/LICENSE.txt) | 本地/CI 构建辅助；不随源码 ZIP 分发 |
| actions/checkout | v4.2.2 / `11bd71901bbe5b1630ceea73d27597364c9af683` | [MIT LICENSE](https://github.com/actions/checkout/blob/v4.2.2/LICENSE) | GitHub 托管执行，不内嵌 |
| actions/setup-python | v5.6.0 / `a26af69be951a213d495a4c3e4e4022e16d87065` | [MIT LICENSE](https://github.com/actions/setup-python/blob/v5.6.0/LICENSE) | GitHub 托管执行，不内嵌 |

pip 使用所选 Python 环境自带版本，作为安装器并非运行依赖；其 [MIT 许可及 vendored 依赖说明](https://github.com/pypa/pip/blob/main/LICENSE.txt) 随 pip 自身分发。构建工具可能包含各自 vendored 依赖，安装后保留它们的许可文件；本仓库的 MIT 不覆盖它们。

## 旧业务代码的来源核查与排除决定

旧目录只读检查显示有 `pyJianYingDraft` 源码目录与独立 `jycrypto.py`。未把它们或旧模板/素材复制进本仓库。

- **pyJianYingDraft**：核实上游 GuanYixuan/pyJianYingDraft 的 v0.3.0 对应提交 `60227250c90b2a3b4cb97051300ad780ae8fd62a`，其 [LICENSE 为 Apache-2.0](https://github.com/GuanYixuan/pyJianYingDraft/blob/60227250c90b2a3b4cb97051300ad780ae8fd62a/LICENSE)。但旧本地副本内未找到 LICENSE、发行元数据或可靠版本标识，没有逐文件建立该副本与上游提交及本地修改的对应关系；因此**不能用上游许可推定整份旧副本可以再分发**。本项目不依赖它。
- **jycrypto.py / jy-draftc**：旧文件注释引用 wenshui330/jy-draftc，这只是来源线索。另行核实上游提交 `d1c8a7dcb79c2f17f96ab95013a079e777fc236e` 的 [LICENSE](https://github.com/wenshui330/jy-draftc/blob/d1c8a7dcb79c2f17f96ab95013a079e777fc236e/LICENSE) 为 MIT，版权声明为 2026 wenshui330。该上游主体是 C++ 实现，不能据此证明旧 Python 文件的作者、移植授权、修改历史和版本。本项目不分发或加载该 Python 文件、解密器及剪映 DLL。
- **旧业务模板/媒体**：没有取得逐资产来源与再分发授权证明，全部排除。默认 9 槽、其他模板 13/6 槽只作为行为回归需求参考，测试使用新构造的数据。

这些未解决的来源映射阻碍的是**直接公开旧代码与旧资产**，不影响本仓库使用原创示例、标准库和独立明文草稿适配器。后续如引入第三方实现，需重新固定精确版本、核对源码和许可、保存必要通知并增加测试；不要把旧注释当成审计结论。

剪映、钉钉及豆包均为外部服务/产品，其账号、软件许可、内容和服务条款由相应提供方管理。这里的 MIT 不授予外部账号、媒体、商标、字体或模型服务使用权。
