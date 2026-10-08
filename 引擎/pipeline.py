# -*- coding: utf-8 -*-
"""新闻视频批量生成流水线 (主程序, 统一或随机模板版)

用法: 由 automation.py 调用, 或:
    python pipeline.py [工具根目录]

流程: 扫描 输入/ 下的每条新闻文件夹(支持 输入/<类型>/<新闻>/ 两级) ->
      读取该新闻记录的模板 -> 复制模板草稿 -> 替换文字 ->
      素材三级取用: ①info.txt 手工指定 ②文件夹内文件名带槽位名 ③类型素材池
      (按使用次数最少优先, 循环复用) -> 重新加密 -> 保存到剪映草稿目录
"""
import argparse
import datetime
import json
import os
import shutil
import sys
import traceback

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE_DIR)

import pyJianYingDraft as draft  # noqa: E402
from jycrypto import JianyingCrypto, find_jianying_dir  # noqa: E402
import template_registry as reg  # noqa: E402
from template_health import preflight_templates, validate_slots  # noqa: E402

VIDEO_EXTS = reg.VIDEO_EXTS
IMAGE_EXTS = reg.IMAGE_EXTS
MEDIA_EXTS = reg.MEDIA_EXTS


class DraftVerificationError(RuntimeError):
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


def read_info_txt(path: str) -> dict:
    """读取 info.txt, 兼容 UTF-8(带/不带BOM) 与 GBK 编码, 返回 {键: 值}"""
    for enc in ("utf-8-sig", "gbk"):
        try:
            with open(path, "r", encoding=enc) as f:
                lines = f.readlines()
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("info.txt 编码无法识别, 请另存为 UTF-8 或 ANSI 编码")

    info = {}
    for ln, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"info.txt 第{ln}行格式不正确(应为 键=值): {line}")
        key, value = line.split("=", 1)
        info[key.strip()] = value.strip().replace("\\n", "\n")
    return info


def read_single_line(path: str, default: str = "") -> str:
    if not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read().strip() or default


def find_drafts_dir() -> str:
    p = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "JianyingPro", "User Data", "Projects", "com.lveditor.draft")
    if not os.path.isdir(p):
        raise FileNotFoundError(f"未找到剪映草稿目录: {p}")
    return p


class BatchRunner:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.input_dir = os.path.join(self.root, "输入")
        self.report_dir = os.path.join(self.root, "报告")

        self.registry = reg.load_registry(self.root)
        if not self.registry:
            raise RuntimeError("模板库为空: 模板库/模板清单.json 不存在或没有模板")
        self.use_records = reg.load_use_records(self.root)

        self.drafts_dir = find_drafts_dir()
        log(f"剪映草稿目录: {self.drafts_dir}")
        log("正在加载剪映加解密引擎 (首次约需10秒) ...")
        self.crypto = JianyingCrypto(find_jianying_dir())
        log("引擎就绪")

        self._plain_cache = {}   # 模板名 -> 解密后的明文草稿
        self.last_results = []
        self.last_report_path = ""

        self.template_health = preflight_templates(
            self.root, self.crypto, registry=self.registry, repair=True
        )
        self.registry = self.template_health["registry"]
        for item in self.template_health["repaired"]:
            groups = "、".join(item["groups"])
            log(f"模板自动修复: [{item['name']}] {groups}")
        for item in self.template_health["disabled"]:
            log(f"模板已自动停用: [{item['name']}] {item['reason']}")
        if not reg.enabled_entries(self.registry):
            raise RuntimeError("模板体检后没有可用模板, 请查看上方停用原因")

    # ---------- 模板加载 ----------
    def template_plain(self, tpl_name: str) -> str:
        if tpl_name in self._plain_cache:
            return self._plain_cache[tpl_name]
        tpl_draft = reg.template_draft_dir(self.root, tpl_name)
        content = os.path.join(tpl_draft, "draft_content.json")
        if not os.path.isfile(content):
            raise FileNotFoundError(f"模板 [{tpl_name}] 的草稿文件不存在: {tpl_draft}")
        with open(content, "rb") as f:
            plain = self.crypto.decrypt(f.read()).decode("utf-8")
        self._plain_cache[tpl_name] = plain
        return plain

    # ---------- 发现待处理新闻 ----------
    def discover_episodes(self) -> list:
        eps = []
        if not os.path.isdir(self.input_dir):
            return eps
        for name in sorted(os.listdir(self.input_dir)):
            p = os.path.join(self.input_dir, name)
            if not os.path.isdir(p):
                continue
            if os.path.isfile(os.path.join(p, "info.txt")):
                eps.append(p)                       # 一级: 输入/<新闻>/
            else:
                for sub in sorted(os.listdir(p)):   # 二级: 输入/<类型>/<新闻>/
                    sp = os.path.join(p, sub)
                    if os.path.isdir(sp) and os.path.isfile(os.path.join(sp, "info.txt")):
                        eps.append(sp)
        return eps

    # ---------- 单条视频处理 ----------
    def process_one(self, ep_dir: str) -> list:
        ep_name = os.path.basename(ep_dir)
        info = read_info_txt(os.path.join(ep_dir, "info.txt"))

        tpl_name = read_single_line(os.path.join(ep_dir, "模板.txt"), reg.DEFAULT_TYPE)
        template_entry = reg.find_entry(self.registry, tpl_name)
        if template_entry is None:
            raise RuntimeError(f"新闻记录的模板 [{tpl_name}] 不在模板库中")
        if not reg.is_enabled(template_entry):
            reason = template_entry.get("停用原因") or "模板体检未通过"
            raise RuntimeError(f"新闻记录的模板 [{tpl_name}] 已停用: {reason}")
        news_type = read_single_line(os.path.join(ep_dir, "类型.txt"), "")
        slots = reg.load_slots(self.root, tpl_name)

        target = os.path.join(self.drafts_dir, ep_name)
        if os.path.exists(target):
            raise FileExistsError(f"剪映草稿目录中已存在同名草稿 [{ep_name}], 请先删除或改名后重试")

        # 1) 复制模板草稿文件夹
        shutil.copytree(reg.template_draft_dir(self.root, tpl_name), target)
        try:
            warnings = self._fill_draft(ep_dir, info, target, slots, news_type)
        except DraftVerificationError as exc:
            self._disable_template(tpl_name, f"生成后核验失败: {exc}")
            shutil.rmtree(target, ignore_errors=True)
            raise RuntimeError(f"模板 [{tpl_name}] 已自动停用: {exc}") from exc
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        warnings.insert(0, f"使用模板: {tpl_name}")
        return warnings

    def _collect_materials(self, ep_dir: str, info: dict, slots: dict, news_type: str):
        """为素材槽位分配文件, 三级优先:
        ① info.txt 手工指定 -> ② 文件夹内文件名含槽位名 -> ③ 类型素材池
        返回 {槽位键名: 文件绝对路径}, 报告行列表"""
        mat_slots = [s["键名"] for s in slots.get("素材槽位", [])]
        assigned = {}
        notes = []

        # ① info.txt 手工指定
        for key in mat_slots:
            if key in info and info[key]:
                src = os.path.join(ep_dir, info[key])
                if not os.path.isfile(src):
                    raise FileNotFoundError(f"素材槽位[{key}]指定的文件不存在: {info[key]}")
                assigned[key] = src
                notes.append(f"素材[{key}]: 手工指定 {info[key]}")

        # ② 文件名打标: 文件夹内文件名包含槽位名
        ep_files = sorted(
            f for f in os.listdir(ep_dir)
            if os.path.isfile(os.path.join(ep_dir, f))
            and os.path.splitext(f)[1].lower() in MEDIA_EXTS
        )
        used_files = {os.path.basename(p) for p in assigned.values()}
        for key in mat_slots:
            if key in assigned:
                continue
            for f in ep_files:
                if f in used_files:
                    continue
                if key in os.path.splitext(f)[0]:
                    assigned[key] = os.path.join(ep_dir, f)
                    used_files.add(f)
                    notes.append(f"素材[{key}]: 文件名识别 {f}")
                    break

        # ③ 类型素材池 (用最少优先, 循环复用)
        remaining = [k for k in mat_slots if k not in assigned]
        if remaining:
            pool_type = news_type or reg.DEFAULT_TYPE
            picked = reg.pick_from_pool(self.root, pool_type, len(remaining), self.use_records)
            if picked:
                actual_type = pool_type if reg.list_pool_files(self.root, pool_type) else reg.DEFAULT_TYPE
                for key, src in zip(remaining, picked):
                    assigned[key] = src
                    notes.append(f"素材[{key}]: 素材池({actual_type}) {os.path.basename(src)}")
                if len(picked) < len(remaining):
                    notes.append(f"警告: 素材池[{pool_type}]素材不足, "
                                 f"{len(remaining) - len(picked)} 个槽位保留模板原画面")
            else:
                notes.append(f"提示: 素材池[{pool_type}]为空, "
                             f"{len(remaining)} 个槽位保留模板原画面")
        return assigned, notes

    def _disable_template(self, template_name: str, reason: str) -> None:
        registry = reg.load_registry(self.root)
        entry = reg.find_entry(registry, template_name)
        if entry is not None:
            entry["启用"] = False
            entry["停用原因"] = str(reason)[:300]
            reg.save_registry(self.root, registry)
        self.registry = registry

    @staticmethod
    def _normalized_path(path: str) -> str:
        return os.path.normcase(os.path.abspath(os.path.normpath(path)))

    def _verify_written_draft(self, target: str, slots: dict, replacements: dict,
                              text_info: dict = None) -> str:
        """反向读取最终草稿，确认每个已分配槽位真实引用了复制后的素材。"""
        content_path = os.path.join(target, "draft_content.json")
        try:
            with open(content_path, "rb") as handle:
                plain_bytes = self.crypto.decrypt(handle.read())
            data = json.loads(plain_bytes.decode("utf-8"))
        except Exception as exc:
            raise DraftVerificationError(f"最终草稿无法解密读取: {exc}") from exc

        slot_errors = validate_slots(slots, data)
        if slot_errors:
            raise DraftVerificationError("最终草稿轨道结构异常: " + "；".join(slot_errors))

        video_tracks = [track for track in data.get("tracks", [])
                        if isinstance(track, dict) and track.get("type") == "video"]
        material_by_id = {}
        materials = data.get("materials", {})
        if isinstance(materials, dict):
            for bucket in materials.values():
                if not isinstance(bucket, list):
                    continue
                for material in bucket:
                    if isinstance(material, dict) and material.get("id"):
                        material_by_id[material["id"]] = material

        for key, expected in replacements.items():
            slot = expected["slot"]
            try:
                segment = video_tracks[slot["轨道序号"]]["segments"][slot["片段"]]
            except (IndexError, KeyError, TypeError) as exc:
                raise DraftVerificationError(f"素材[{key}]的目标片段不存在") from exc
            material = material_by_id.get(segment.get("material_id"))
            if material is None:
                raise DraftVerificationError(f"素材[{key}]替换后没有对应素材记录")
            actual_path = material.get("path")
            expected_path = expected["path"]
            if not isinstance(actual_path, str) or (
                    self._normalized_path(actual_path) != self._normalized_path(expected_path)):
                raise DraftVerificationError(f"素材[{key}]仍未指向新素材")
            if not os.path.isfile(expected_path):
                raise DraftVerificationError(f"素材[{key}]复制后的文件不存在")

        if text_info is not None:
            text_tracks = [track for track in data.get("tracks", [])
                           if isinstance(track, dict) and track.get("type") == "text"]
            for slot in slots.get("文字槽位", []):
                key = slot["键名"]
                expected = text_info.get(key)
                if not isinstance(expected, str) or not expected.strip():
                    raise DraftVerificationError(f"文字槽位[{key}]缺少有效文案，请重新生成输入")
                for index in slot["片段"]:
                    segment = text_tracks[slot["轨道序号"]]["segments"][index]
                    material = material_by_id.get(segment.get("material_id"), {})
                    if "text_info_resources" in material:
                        resources = material["text_info_resources"]
                        material = (material_by_id.get(resources[0].get("text_material_id"), {})
                                    if resources else {})
                    try:
                        actual = json.loads(material.get("content", "{}"))["text"]
                    except (ValueError, TypeError, KeyError) as exc:
                        raise DraftVerificationError(f"文字槽位[{key}]无法读取最终文字") from exc
                    if actual != expected:
                        raise DraftVerificationError(
                            f"文字槽位[{key}]片段{index}与输入文案不一致")

        if replacements:
            return f"素材核验通过: {len(replacements)} 个已分配槽位均已替换"
        return "草稿结构核验通过: 本条没有分配新素材"

    def _fill_draft(self, ep_dir: str, info: dict, target: str,
                    slots: dict, news_type: str) -> list:
        warnings = []
        tpl_name = read_single_line(os.path.join(ep_dir, "模板.txt"), reg.DEFAULT_TYPE)

        # 2) 加载模板明文
        tmp_plain = os.path.join(target, "__plain_tmp.json")
        with open(tmp_plain, "w", encoding="utf-8") as f:
            f.write(self.template_plain(tpl_name))
        script = draft.ScriptFile._load_template(tmp_plain)

        # 3) 替换文字
        for slot in slots.get("文字槽位", []):
            key = slot["键名"]
            if not isinstance(info.get(key), str) or not info[key].strip():
                raise ValueError(f"文字槽位[{key}]缺少有效文案，请重新生成输入")
            track = script.get_imported_track(draft.TrackType.text, index=slot["轨道序号"])
            for seg_idx in slot["片段"]:
                if seg_idx < len(track):
                    script.replace_text(track, seg_idx, info[key])
                else:
                    warnings.append(f"文字槽位[{key}]的片段{seg_idx}不存在, 已跳过")

        # 4) 替换视频/图片素材
        assigned, notes = self._collect_materials(ep_dir, info, slots, news_type)
        warnings.extend(notes)
        mat_dst_dir = os.path.join(target, "materials", "video")
        os.makedirs(mat_dst_dir, exist_ok=True)
        slot_by_key = {s["键名"]: s for s in slots.get("素材槽位", [])}
        replacements = {}
        for key, src in assigned.items():
            slot = slot_by_key[key]
            dst = os.path.join(mat_dst_dir, f"{key}_{os.path.basename(src)}")
            shutil.copy2(src, dst)
            track = script.get_imported_track(draft.TrackType.video, index=slot["轨道序号"])
            seg = track.segments[slot["片段"]]
            material = draft.VideoMaterial(dst)
            ext = os.path.splitext(src)[1].lower()
            if material.duration < seg.duration and ext in VIDEO_EXTS:
                warnings.append(
                    f"素材[{key}]比槽位短 {round((seg.duration - material.duration)/1e6, 1)} 秒, "
                    f"尾部将留空")
            script.replace_material_by_seg(track, slot["片段"], material)
            replacements[key] = {"slot": slot, "path": dst}

        # 5) 保存明文 -> 重新加密 -> 写回
        script.save()
        with open(tmp_plain, "rb") as f:
            encrypted = self.crypto.encrypt(f.read())
        os.remove(tmp_plain)
        with open(os.path.join(target, "draft_content.json"), "wb") as f:
            f.write(encrypted)
        warnings.append(self._verify_written_draft(target, slots, replacements, info))
        warnings.append(f"文字核验通过: {len(slots.get('文字槽位', []))} 个槽位与输入一致")
        return warnings

    # ---------- 批量入口 ----------
    def run(self, episode_dirs=None) -> int:
        """批量生成草稿; episode_dirs 用于自动化流程只处理本次新生成的新闻。"""
        episodes = list(episode_dirs) if episode_dirs is not None else self.discover_episodes()
        log("")
        if not episodes:
            log("!! 输入/ 文件夹里没有待生成的新闻，请先运行自动化生成文案")
            self.last_results = []
            return 0
        log(f"共发现 {len(episodes)} 条待生成视频")
        log("")

        results = []
        for i, ep_dir in enumerate(episodes, 1):
            ep = os.path.basename(ep_dir)
            log(f"[{i}/{len(episodes)}] 正在生成: {ep}")
            try:
                warns = self.process_one(ep_dir)
                results.append((ep, "成功", warns))
                log(f"    -> 成功, 草稿已创建: {ep}")
                for w in warns:
                    log(f"    [明细] {w}")
            except Exception as e:
                results.append((ep, f"失败: {e}", []))
                log(f"    -> 失败: {e}")
                traceback.print_exc()

        # 素材使用计数落盘
        reg.save_use_records(self.root, self.use_records)

        # 汇总报告
        os.makedirs(self.report_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(self.report_dir, f"生成报告_{stamp}.txt")
        self.last_results = results
        self.last_report_path = report_path
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"生成时间: {datetime.datetime.now()}\n")
            f.write("=" * 50 + "\n")
            for ep, status, warns in results:
                f.write(f"[{ep}] {status}\n")
                for w in warns:
                    f.write(f"    - {w}\n")
            ok = sum(1 for _, s, _ in results if s == "成功")
            f.write("=" * 50 + "\n")
            f.write(f"共 {len(results)} 条, 成功 {ok} 条, 失败 {len(results) - ok} 条\n")
            f.write("成功的草稿已放入剪映草稿目录, 打开剪映即可查看。\n")

        log("")
        ok = sum(1 for _, s, _ in results if s == "成功")
        log(f"全部完成: 成功 {ok} 条 / 共 {len(results)} 条")
        log(f"报告已保存: {report_path}")
        log("现在可以打开剪映, 在草稿列表查看生成结果。")
        return 0 if ok == len(results) else 1


def main():
    parser = argparse.ArgumentParser(description="批量生成剪映草稿")
    parser.add_argument("--root", default=os.path.dirname(ENGINE_DIR),
                        help="工具根目录")
    parser.add_argument("--count", type=int, default=None,
                        help="本次最多生成的草稿数量 (1-100)")
    args = parser.parse_args()
    if args.count is not None and not 1 <= args.count <= 100:
        parser.error("--count 必须是 1 到 100 之间的整数")
    root = os.path.abspath(args.root)
    log("=" * 52)
    log("        新闻视频批量生成工具")
    log("=" * 52)
    try:
        runner = BatchRunner(root)
        episodes = runner.discover_episodes()
        if args.count is not None:
            episodes = episodes[:args.count]
        code = runner.run(episodes)
    except Exception as e:
        log(f"\n发生错误: {e}")
        traceback.print_exc()
        code = 2
    return code


if __name__ == "__main__":
    sys.exit(main())
