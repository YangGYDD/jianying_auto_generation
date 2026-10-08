# -*- coding: utf-8 -*-
# Project Python adaptation of the jy-draftc runtime calling convention.
# Reference: wenshui330/jy-draftc d1c8a7dcb79c2f17f96ab95013a079e777fc236e (MIT).
# Upstream copyright (c) 2026 wenshui330; see licenses/jy-draftc-MIT.txt.
# Existing Python implementation preserved from project baseline a10e701.
"""剪映草稿加解密引擎 (供流水线内部使用)

原理与开源工具 jy-draftc (MIT, wenshui330) 一致:
加载剪映安装目录下的 videoeditor.dll, 调用其导出函数
lvve::EncryptUtils::decrypt / encrypt / enable 完成加解密。

适配版本: 剪映 10.3 ~ 10.6.5 (v2 草稿加密方案)。
"""
import ctypes
import json
import os
from ctypes import Union, c_bool, c_char_p, c_uint64, c_void_p, POINTER, Structure

DECRYPT_SYM = b"?decrypt@EncryptUtils@lvve@@QEAA?AV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV34@0AEA_N@Z"
ENCRYPT_SYM = b"?encrypt@EncryptUtils@lvve@@QEAA?AV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV34@@Z"
ENABLE_SYM = b"?enable@EncryptUtils@lvve@@QEAAX_N@Z"


class _MsvcStringUnion(Union):
    _fields_ = [
        ("small", ctypes.c_char * 16),
        ("ptr", c_void_p),
    ]


class MsvcString(Structure):
    """内存布局与 MSVC std::string 一致"""
    _fields_ = [
        ("u", _MsvcStringUnion),
        ("size", c_uint64),
        ("capacity", c_uint64),
    ]


def _make_str_arg(text: bytes):
    s = MsvcString()
    s.size = len(text)
    if len(text) < 16:
        s.capacity = 15
        s.u.small = text.ljust(16, b"\0")
    else:
        buf = ctypes.create_string_buffer(text, len(text) + 1)
        s.capacity = len(text)
        s.u.ptr = ctypes.cast(buf, c_void_p).value
        s._buf = buf
    return s


def _read_msvc_string(s: MsvcString) -> bytes:
    if s.capacity < 16:
        return bytes(s.u.small)[: s.size]
    return ctypes.string_at(s.u.ptr, s.size)


class JianyingCrypto:
    """绑定一个剪映安装目录的加解密器"""

    def __init__(self, jy_dir: str):
        dll_path = os.path.join(jy_dir, "videoeditor.dll")
        if not os.path.isfile(dll_path):
            raise FileNotFoundError(f"剪映目录中未找到 videoeditor.dll: {jy_dir}")

        kernel32 = ctypes.windll.kernel32
        kernel32.LoadLibraryExW.restype = c_void_p
        kernel32.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, c_void_p, ctypes.c_uint32]
        kernel32.GetProcAddress.restype = c_void_p
        kernel32.GetProcAddress.argtypes = [c_void_p, c_char_p]
        kernel32.SetErrorMode(1 | 0x8000)

        old_cwd = os.getcwd()
        try:
            os.chdir(jy_dir)
            os.add_dll_directory(jy_dir)
            h = kernel32.LoadLibraryExW(dll_path, None, 0x8)
        finally:
            os.chdir(old_cwd)
        if not h:
            raise OSError(f"加载 videoeditor.dll 失败, 错误码 {kernel32.GetLastError()}")

        dec_addr = kernel32.GetProcAddress(h, DECRYPT_SYM)
        enc_addr = kernel32.GetProcAddress(h, ENCRYPT_SYM)
        enable_addr = kernel32.GetProcAddress(h, ENABLE_SYM)
        missing = [n for n, a in [("decrypt", dec_addr), ("encrypt", enc_addr), ("enable", enable_addr)] if not a]
        if missing:
            raise RuntimeError(f"当前剪映版本缺少加解密导出符号 {missing}, 请使用剪映 10.3~10.6.5")

        self._dec = ctypes.CFUNCTYPE(POINTER(MsvcString), c_void_p, POINTER(MsvcString),
                                     POINTER(MsvcString), POINTER(MsvcString), POINTER(c_bool))(dec_addr)
        self._enc = ctypes.CFUNCTYPE(POINTER(MsvcString), c_void_p, POINTER(MsvcString),
                                     POINTER(MsvcString))(enc_addr)
        self._enable = ctypes.CFUNCTYPE(None, c_void_p, c_bool)(enable_addr)

    def decrypt(self, data: bytes) -> bytes:
        # 剪映空间下载的草稿可能已是明文 JSON，无需再交给 DLL 解密。
        try:
            plain = data.decode("utf-8-sig")
            if isinstance(json.loads(plain), dict):
                return plain.encode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass

        out = MsvcString()
        out.capacity = 15
        inp = _make_str_arg(data)
        param = _make_str_arg(b"{}")
        ok = c_bool(False)
        self._dec(None, ctypes.byref(out), ctypes.byref(inp), ctypes.byref(param), ctypes.byref(ok))
        if not ok.value:
            raise RuntimeError("解密失败: 剪映无法识别该加密内容 (可能是更高版本剪映加密的文件)")
        result = _read_msvc_string(out)
        if not result:
            raise RuntimeError("解密失败: 输出为空")
        return result

    def encrypt(self, data: bytes) -> bytes:
        self._enable(None, True)
        out = MsvcString()
        out.capacity = 15
        inp = _make_str_arg(data)
        self._enc(None, ctypes.byref(out), ctypes.byref(inp))
        result = _read_msvc_string(out)
        if not result:
            raise RuntimeError("加密失败: 输出为空")
        if self.decrypt(result) != data:
            raise RuntimeError("加密回环校验失败")
        return result


def find_jianying_dir() -> str:
    """自动定位剪映安装目录 (取版本号最新且包含 videoeditor.dll 的)"""
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "JianyingPro", "Apps")
    if os.path.isdir(base):
        for v in sorted(os.listdir(base), reverse=True):
            p = os.path.join(base, v)
            if os.path.isfile(os.path.join(p, "videoeditor.dll")):
                return p
    raise FileNotFoundError("未找到剪映安装目录, 请确认已安装剪映专业版")
