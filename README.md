# tf-hide

在 SD / TF 卡上生成**真正隐藏**的目录，而不是“改个名字骗管理器”。名字、DOS 属性、媒体扫描三层一起挡。

## 为什么普通做法藏不住

| 做法 | 结果 |
| --- | --- |
| 目录名前加 `.` | 只是默认不显示，开“显示隐藏”就全露 |
| 改成一个像系统目录的名字 | 同上，MT / MiXplorer 一样列得出来 |
| App 内调用“隐藏属性”接口 | 安卓不给普通应用这个接口，没有可调的东西 |

## 原理：三层各管一段

模板（7 层）：

```
RECYCLER88/
└─ MICROSOFT-7701091-6666888-16826688../      ← 尾点长名，FAT 上非法
   └─ $$$/
      └─ com8.{21EC2020-3AEA-1069-A2DD-08002B30309D}/
         └─ su-heng/local/4124/
            └─ .nomedia                        ← 挡媒体扫描
```

1. **尾点长名**：以 `..` 结尾在 FAT 属非法长名。Android 的 FUSE 在 `readdir` 与 `lookup` 两层都过滤——列不出来，按名字 `stat` 也是 `ENOENT`。
2. **HIDDEN + SYSTEM**：直接写 FAT 目录项的属性字节（`0x16` = 目录 + 隐藏 + 系统）。Windows 资源管理器默认跳过。
3. **`.nomedia`**：挡住 Android 媒体库与相册聚合，否则里面的音频会被扫进播放器。

## 为什么只能在 PC / Linux 上生成

Android 上无论用 `java.io.File`、`Os.mkdir` 还是自己写的脚本，最后都走：

```
App → Linux syscall → 内核 FUSE → vfat → 卡
```

尾点就是在 FUSE + vfat 这一层被剥掉的（实测 `mkdir PROBE..` 返回成功，落盘却叫 `PROBE`）。安卓没有 `\\?\` 这种“别解析、原样交给驱动”的前缀，也没有给目录打 DOS 属性的 ioctl。

绕过去只有两条路，都需要 root：直接写卷的裸扇区，或用 `su` 走底层。

## Linux（Armbian / Ubuntu）用法

Linux 的 vfat 驱动不剥尾部点，所以能直接建；属性用 `fatattr` 通过 ioctl 打。

```bash
sudo apt install -y fatattr
./tf_hide_armbian.sh deploy /mnt/sdcard      # 逐层建目录 + 打 H/S + .nomedia
./tf_hide_armbian.sh verify /mnt/sdcard      # 逐层核对名字与属性
./tf_hide_armbian.sh clean  /mnt/sdcard      # 只删这套链，不动别人的东西
```

也可以用打包好的树展开（名字在包里就是带尾点的）：

```bash
./tf_hide_armbian.sh pack /mnt/sdcard tf_hidden_tree.tar.gz
```

`pack` 之后仍要跑 `fatattr`（tar 只能带名字，带不了 DOS 属性）。

## Windows 用法

Windows 必须先绕过 Win32 的路径规范化，所以脚本统一走 `\\?\` 设备路径 + `SetFileAttributesW`。

```powershell
python tf_hide.py info                             # 看盘符/文件系统，认出哪张卡
python tf_hide.py deploy --drive E                # 建 7 层壳
python tf_hide.py deploy --drive E --src "D:\001.mp3" --pad 8
python tf_hide.py verify --drive E                # 核对名字、属性、8.3 短名
python tf_hide.py clean  --drive E
python tf_hide.py selftest                        # 临时目录自测，不碰卡
```

注意：包含 `\\?\` 的脚本必须存成独立 `.py` 再跑，Git Bash 的 heredoc 会把反斜杠转成 `/`，前缀直接失效。

## 验证要点

- `deploy` 会断言尾点没被规范化，被吃掉就报错退出。
- `verify` 会打印 `dir /x` 的 8.3 短名（Windows 侧）。

## 一个绕不过的事实：8.3 短名

FAT 创建长名时必然同时写一条 8.3 短名（如 `MICROS~1`）。短名是合法 FAT 名，不在 FUSE 黑名单里：

- 它是唯一能进树的入口（PC 上 `dir /x` 能看到，`adb` 也能靠爆破短名进去）；
- 它也是普通播放器/媒体库能扫到文件的通道——想“即插即播”就得留着它；
- 短名存在于紧随 LFN 的目录项里，删不掉，`fsutil 8dot3name` 在 FAT32 上直接报 `Incorrect function`。

所以这个方案挡的是“随手翻一翻”的人，不是挡读过这份 README 的人。

## 边界

- 卡在手机里时，App 无法生成这层壳；它只能生成普通目录（安全柜之类）。
- 卡重新格式化后要重跑一次。
- 有 root 或 Shizuku 的机器仍能进 `Android/data` 私有目录，那是另一回事。

## 文件

| 文件 | 用途 |
| --- | --- |
| `tf_hide_armbian.sh` | Linux 侧建树 / 展开 / 核对 / 清理 |
| `tf_hide.py` | Windows 侧同上，走 `\\?\` 设备路径 |
| `LICENSE` | MIT |
