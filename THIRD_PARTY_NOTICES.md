# 第三方来源与分发说明

核查日期：2026-10-08。当前项目已恢复原版引擎，不再使用先前独立重写的运行时适配器。

## pyJianYingDraft

上游：GuanYixuan/pyJianYingDraft，固定提交 `60227250c90b2a3b4cb97051300ad780ae8fd62a`，setup.py 版本 0.3.0。

原版内 42 个 Python 文件和 2 个结构 JSON 与该提交相同（比较前仅统一文本换行/BOM）；当前保留这些文件不作行为修改。逐文件哈希见 [来源映射](docs/pyjianying-origin-map.json)。新增缺失的 LICENSE，保留上游 `Copyright 2024 Gary Guan` 和完整 Apache-2.0 许可。固定上游未包含需要随此代码复制的独立 NOTICE 文件。

- 上游代码：https://github.com/GuanYixuan/pyJianYingDraft/tree/60227250c90b2a3b4cb97051300ad780ae8fd62a
- 许可：https://github.com/GuanYixuan/pyJianYingDraft/blob/60227250c90b2a3b4cb97051300ad780ae8fd62a/LICENSE

未复制上游演示音视频、图片或说明书截图，只分发上述代码和空白结构数据。

## jycrypto.py 与 jy-draftc

保留本项目原版 Python `jycrypto.py`，来源基线为本项目本地提交 `a10e701`，文件在初始快照 `73942ba` 已存在。它不是声称来自上游的 Python发行包；本地文件注释明确引用 jy-draftc。

已逐项对照上游 C++ 的 MSVC string 布局、三个导出符号、参数传递和加解密调用约定。上游固定提交为 `d1c8a7dcb79c2f17f96ab95013a079e777fc236e`，MIT，`Copyright (c) 2026 wenshui330`。完整 MIT 归属在 [licenses/jy-draftc-MIT.txt](licenses/jy-draftc-MIT.txt)，并在Python文件顶部注明参考来源及项目适配身份。当前只补归属注释，不更换已验证的实现。

- 来源：https://github.com/wenshui330/jy-draftc/blob/d1c8a7dcb79c2f17f96ab95013a079e777fc236e/src/jy-draftc.cpp
- 许可：https://github.com/wenshui330/jy-draftc/blob/d1c8a7dcb79c2f17f96ab95013a079e777fc236e/LICENSE

软件从用户本机加载剪映 `videoeditor.dll`，不分发 DLL、安装包或密钥。上游 MIT 不覆盖剪映本身。

## 安装依赖

源码包不内嵌解释器、wheel 或第三方 DLL，由用户按 requirements.txt 安装。当前固定 ImageIO 2.37.4、pymediainfo 7.0.1、uiautomation 2.0.29、numpy 2.4.6、pillow 12.3.0、comtypes 1.4.17。前五项从既有环境及新环境核验，comtypes 使用新环境实际安装版本。

安装元数据分别声明 ImageIO BSD-2-Clause、pymediainfo MIT、uiautomation Apache-2.0、numpy 多许可证组合、pillow MIT-CMU、comtypes MIT；它们的完整通知由对应发行包携带，本项目根MIT不覆盖这些依赖。pymediainfo附带的MediaInfo、numpy/pillow等二进制的条款必须随原发行包保留。本次不制作捆绑二进制的离线安装包。

## 项目示例和内部资产

原创示例文本及 demo.py 的两段纯文字场景由本项目创作，按根MIT分发，不是真实新闻。结构序列化由上面的Apache-2.0库完成。业务版模板、媒体、字体缓存、商标图、配置、新闻输入和历史报告全部排除。

CI固定使用actions/checkout和actions/setup-python的MIT版本，不复制它们到产品。各服务的账号、软件许可和服务条款由对应提供方管理；代码许可不授予媒体或商标使用权。
