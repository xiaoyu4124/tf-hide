#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
tf_hide.py —— 在 SD / TF 卡上造“真隐藏”目录树（FAT 尾点长名 + HIDDEN/SYSTEM + .nomedia）

为什么 App 里做不到：
  1. Android 的 FUSE / vfat 会把尾点名字规范化，mkdir "X.." 实际落盘成 "X"；
  2. 普通应用没有接口给目录写 DOS 的 HIDDEN / SYSTEM 属性；
  3. 名字不带 "." 前缀，任何文件管理器都会列出来。
  所以生成只能在 Windows 侧做，并且必须走 \\?\ 设备路径绕过 Win32 规范化。

三层一起才藏得住：
  · 尾点长名：FAT 上属非法长名，Android FUSE 在 readdir 与 lookup 两层都过滤，
    列不出来、按名字也打不开（但 8.3 短名是合法名，能当入口 —— 见 verify 输出）
  · HIDDEN|SYSTEM：Windows 资源管理器直接跳过
  · .nomedia：挡住 Android 媒体扫描与相册聚合

用法（只支持 Windows）：
  python tf_hide.py info
  python tf_hide.py deploy --drive E
  python tf_hide.py deploy --drive E --src "D:\Recordings\001-西雀新.mp3" --pad 8
  python tf_hide.py verify --drive E
  python tf_hide.py clean  --drive E
  python tf_hide.py selftest
"""

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile

TEMPLATE = (
    "RECYCLER88",
    "MICROSOFT-7701091-6666888-16826688..",
    "$$$",
    "com8.{21EC2020-3AEA-1069-A2DD-08002B30309D}",
    "su-heng",
    "local",
    "4124",
)

ATTR_DIR = 0x10
ATTR_HIDDEN = 0x02
ATTR_SYSTEM = 0x04
ATTR_NORMAL = 0x80
ATTR_REPARSE = 0x400

DRIVE_TYPES = {0: "未知", 1: "无效", 2: "可移动", 3: "本地磁盘", 4: "网络", 5: "光驱", 6: "内存盘"}

if os.name != "nt":
    sys.exit("只能在 Windows 上运行：需要 \\\\?\\ 设备路径与 SetFileAttributesW。")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
k32.SetFileAttributesW.restype = ctypes.c_int
k32.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
k32.GetFileAttributesW.restype = ctypes.c_uint32
k32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
k32.GetDriveTypeW.restype = ctypes.c_uint32
k32.GetVolumeInformationW.argtypes = [
    ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
    ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p, ctypes.c_uint32,
]
k32.GetVolumeInformationW.restype = ctypes.c_int


def lp(path):
    r"""把普通路径转成 \\?\ 设备路径；已经是的不动。"""
    path = str(path)
    return path if path.startswith("\\\\?\\") else "\\\\?\\" + path


def join(base, name):
    return base.rstrip("\\") + "\\" + name


def set_attrs(path, attrs):
    if not k32.SetFileAttributesW(lp(path), attrs):
        raise OSError("SetFileAttributesW 失败 err=%d path=%s" % (ctypes.get_last_error(), path))


def get_attrs(path):
    return k32.GetFileAttributesW(lp(path))


def attrs_text(v):
    if v == 0xFFFFFFFF:
        return "(不存在/无权限)"
    marks = []
    if v & ATTR_DIR:
        marks.append("D")
    if v & ATTR_HIDDEN:
        marks.append("H")
    if v & ATTR_SYSTEM:
        marks.append("S")
    return "0x%02X%s" % (v, (" [" + "+".join(marks) + "]") if marks else "")


def drive_root(letter):
    return letter.strip().rstrip(":").upper() + ":\\"


def get_fs(root):
    fs = ctypes.create_unicode_buffer(64)
    vol = ctypes.create_unicode_buffer(64)
    serial = ctypes.c_uint32(0)
    maxlen = ctypes.c_uint32(0)
    flags = ctypes.c_uint32(0)
    ok = k32.GetVolumeInformationW(root, vol, 64, ctypes.byref(serial),
                                   ctypes.byref(maxlen), ctypes.byref(flags), fs, 64)
    return (fs.value, vol.value) if ok else ("?", "?")


def build_chain(root):
    r"""从 root 逐级建 TEMPLATE，返回最深一级（\\?\ 路径）。"""
    cur = lp(root.rstrip("\\"))
    for part in TEMPLATE:
        cur = join(cur, part)
        if not os.path.isdir(cur):
            os.mkdir(cur)
        set_attrs(cur, ATTR_DIR | ATTR_HIDDEN | ATTR_SYSTEM)
        yield cur


def put_file(deepest, src, attrs=ATTR_HIDDEN):
    src = os.path.abspath(src)
    if not os.path.isfile(lp(src)):
        raise SystemExit("源文件不存在：" + src)
    dst = join(deepest, os.path.basename(src))
    shutil.copyfile(lp(src), lp(dst))
    set_attrs(dst, attrs)
    return dst


def make_nomedia(deepest):
    p = join(deepest, ".nomedia")
    with open(lp(p), "wb"):
        pass
    set_attrs(p, ATTR_HIDDEN)
    return p


def make_pad(deepest, mb):
    if mb <= 0:
        return None
    p = join(deepest, "0000.dat")
    chunk = b"\0" * (1 << 20)
    with open(lp(p), "wb") as fh:
        for _ in range(int(mb)):
            fh.write(chunk)
    set_attrs(p, ATTR_HIDDEN | ATTR_SYSTEM)
    return p


def dir_short_names(path):
    r"""读取 8.3 短名（用 cmd 的 dir /x，只对第一级普通名有效）。"""
    try:
        out = subprocess.run(["cmd", "/c", "dir", "/x", "/a", path],
                             capture_output=True, text=True, encoding="mbcs")
    except Exception as exc:
        return "读取失败: %s" % exc
    rows = [ln.rstrip() for ln in out.stdout.splitlines()
            if "<DIR>" in ln.upper() or "<目录>" in ln]
    return "\n        ".join(rows) if rows else "(无短名记录)"


def rm_tree(path):
    for name in os.listdir(path):
        child = join(path, name)
        a = get_attrs(child)
        if (a & ATTR_DIR) and not (a & ATTR_REPARSE):
            rm_tree(child)
        else:
            set_attrs(child, ATTR_NORMAL)
            os.remove(child)
    set_attrs(path, ATTR_NORMAL)
    os.rmdir(path)


def cmd_info(_args):
    print("盘符  类型       文件系统  卷标          可用/总容量")
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = letter + ":\\"
        if not os.path.exists(root):
            continue
        t = k32.GetDriveTypeW(root)
        fs, label = get_fs(root)
        try:
            usage = shutil.disk_usage(root)
            cap = "%.1f/%.1f GB" % (usage.free / 2**30, usage.total / 2**30)
        except OSError:
            cap = "-"
        print("%-5s %-11s %-9s %-13s %s" % (letter + ":", DRIVE_TYPES.get(t, "?"), fs, label, cap))
    print("\n提示：目标是「可移动 + FAT32/exFAT」那一行，插卡后重新跑一次 info。")


def cmd_deploy(args):
    root = args.base or drive_root(args.drive)
    if not os.path.isdir(lp(root.rstrip("\\"))):
        raise SystemExit("根路径不存在：" + root)
    print("目标根目录：%s" % root)
    last = None
    for idx, cur in enumerate(build_chain(root), 1):
        print("  [%d] %-52s %s" % (idx, TEMPLATE[idx - 1], attrs_text(get_attrs(cur))))
        last = cur

    parent = last.rsplit("\\", 1)[0]
    if TEMPLATE[-1] not in os.listdir(parent):
        raise SystemExit("异常：%s 没出现在 %s 里，尾点可能被规范化" % (TEMPLATE[-1], parent))

    made = [make_nomedia(last)]
    for src in (args.src or []):
        made.append(put_file(last, src))
    pad = make_pad(last, args.pad)
    if pad:
        made.append(pad)

    print("\n已生成：%s" % last)
    for item in made:
        print("  + %-24s %s" % (os.path.basename(item), attrs_text(get_attrs(item))))
    print("\nAndroid 侧：这一层的尾点目录会被 FUSE 过滤，普通管理器列不出来。")
    print("Windows 侧：%s 已打 H+S，资源管理器默认跳过。" % TEMPLATE[0])


def cmd_verify(args):
    root = args.base or drive_root(args.drive)
    first = join(root.rstrip("\\"), TEMPLATE[0])

    print("== 1) 普通视图（Win32 不带 \\\\?\\）")
    try:
        print("   %s 里有：%s" % (first, os.listdir(first)))
    except OSError as exc:
        print("   列目录失败：%s" % exc)
    print("   8.3 短名（Android 侧唯一能当入口的东西）：")
    print("        " + dir_short_names(first))

    print("\n== 2) 设备路径视图（\\\\?\\）")
    cur = lp(root.rstrip("\\"))
    for idx, part in enumerate(TEMPLATE, 1):
        cur = join(cur, part)
        exists = os.path.isdir(cur)
        print("   [%d] %-52s exists=%s attrs=%s" % (idx, part, exists, attrs_text(get_attrs(cur))))
        if exists and idx == len(TEMPLATE):
            for name in os.listdir(cur):
                child = join(cur, name)
                size = 0 if os.path.isdir(child) else os.path.getsize(child)
                print("        - %-32s %s %d B" % (name, attrs_text(get_attrs(child)), size))

    print("\n== 3) 结论")
    print("   尾点名：FUSE readdir/lookup 双过滤，按名字 stat 会 ENOENT。")
    print("   短名：合法 FAT 名，知道它就能进 —— 但它同时是播放器/媒体库的唯一通道，删不掉也禁不了。")


def cmd_clean(args):
    root = args.base or drive_root(args.drive)
    cur = lp(root.rstrip("\\"))
    chain = []
    for part in TEMPLATE:
        cur = join(cur, part)
        if not os.path.isdir(cur):
            print("跳过（不存在）：%s" % part)
            return
        chain.append(cur)

    deepest = chain[-1]
    for name in os.listdir(deepest):
        p = join(deepest, name)
        a = get_attrs(p)
        if (a & ATTR_DIR) and not (a & ATTR_REPARSE):
            rm_tree(p)
        else:
            set_attrs(p, ATTR_NORMAL)
            os.remove(p)
    set_attrs(deepest, ATTR_NORMAL)
    os.rmdir(deepest)
    print("已删除最深层：%s" % deepest)

    for d in reversed(chain[:-1]):
        try:
            os.rmdir(d)
            print("已删除：%s" % d)
        except OSError:
            print("保留（目录非空，可能有别人的东西）：%s" % d)
            break


def cmd_selftest(_args):
    tmp = tempfile.mkdtemp(prefix="tfhide_selftest_")
    print("临时目录：%s" % tmp)
    try:
        ns = argparse.Namespace(base=tmp, drive=None, src=None, pad=1)
        cmd_deploy(ns)
        print("\n---- verify ----")
        cmd_verify(ns)
        print("\n---- clean ----")
        cmd_clean(ns)
        print("\n临时目录剩余：%s" % os.listdir(tmp))
    finally:
        os.rmdir(tmp)
        print("selftest 通过，临时目录已清理")


def main():
    ap = argparse.ArgumentParser(description="SD/TF 卡真隐藏目录树工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="列出盘符、类型、文件系统")
    p.set_defaults(func=cmd_info)

    for name, func, helptext in (
        ("deploy", cmd_deploy, "生成隐藏目录树"),
        ("verify", cmd_verify, "核对名字与属性"),
        ("clean", cmd_clean, "删除这套隐藏目录"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--drive", help="盘符，如 E 或 E:")
        p.add_argument("--base", help="覆盖根目录（测试用）")
        p.add_argument("--src", nargs="*", help="要放进最深层的文件")
        p.add_argument("--pad", type=int, default=0, help="填充文件大小 MB（抹平容量差）")
        p.set_defaults(func=func)

    p = sub.add_parser("selftest", help="在临时目录里跑完整流程")
    p.set_defaults(func=cmd_selftest)

    args = ap.parse_args()
    if args.cmd in ("deploy", "verify", "clean") and not (args.drive or args.base):
        ap.error("--drive 必须给，例如 --drive E")
    args.func(args)


if __name__ == "__main__":
    main()
