#!/usr/bin/env bash
# tf_hide_armbian.sh —— 在 Linux（Armbian / Ubuntu 等）侧把“真隐藏”目录直接落到 TF 卡上
#
# 为什么 Linux 能做而 Windows/Android 不能：
#   Linux 的 vfat 驱动不会剥掉名字尾部的点，所以 "X.." 能原样写进 FAT 目录项；
#   DOS 的 HIDDEN/SYSTEM 属性用 fatattr 通过 ioctl 直接改目录项属性字节。
#
# 用法（卡挂载后）：
#   ./tf_hide_armbian.sh deploy  /mnt/sdcard
#   ./tf_hide_armbian.sh pack    /mnt/sdcard tf_hidden_tree.tar.gz
#   ./tf_hide_armbian.sh verify  /mnt/sdcard
#   ./tf_hide_armbian.sh clean   /mnt/sdcard
#
# 依赖：fatattr（sudo apt install -y fatattr）。缺了会提示，但目录仍然会建好。

set -euo pipefail

LEVELS=(
  "RECYCLER88"
  "MICROSOFT-7701091-6666888-16826688.."
  '$$$'
  'com8.{21EC2020-3AEA-1069-A2DD-08002B30309D}'
  "su-heng"
  "local"
  "4124"
)

die() { echo "错误：$*" >&2; exit 1; }

usage() {
  cat >&2 <<'EOF'
用法：
  tf_hide_armbian.sh deploy  <挂载点>
  tf_hide_armbian.sh pack    <挂载点> <tar.gz>
  tf_hide_armbian.sh verify  <挂载点>
  tf_hide_armbian.sh clean   <挂载点>
EOF
  exit 2
}

check_mount() {
  local mp="$1"
  [ -d "$mp" ] || die "挂载点不存在：$mp"
  local fs
  fs="$(findmnt -no FSTYPE --target "$mp" 2>/dev/null || true)"
  echo "挂载点：$mp  文件系统：${fs:-未知}" >&2
  case "${fs:-}" in
    vfat|msdos|fat) ;;
    *) echo "提示：这里不是 FAT 卷，尾点名与 DOS 属性在 ext4 上没有意义。" >&2 ;;
  esac
}

have_fatattr() { command -v fatattr >/dev/null 2>&1; }

# 逐层建目录；结果写到全局 DEEPEST
build() {
  local mp="$1" cur="$1" lv
  for lv in "${LEVELS[@]}"; do
    cur="$cur/$lv"
    if [ -d "$cur" ]; then
      echo "  已存在 $lv"
    else
      mkdir "$cur" || die "建目录失败：$cur"
      echo "  创建   $lv"
    fi
  done
  DEEPEST="$cur"
}

# 校验尾点：看 RECYCLER88 这一层里是否存在带 ".." 的名字
assert_name() {
  local mp="$1" dot parent listing
  dot="$mp/${LEVELS[0]}/${LEVELS[1]}"
  parent="$(dirname "$dot")"
  listing="$(ls -A "$parent")"
  case "$listing" in
    *"${LEVELS[1]}"*) echo "  名字校验：尾点保留 OK" ;;
    *) die "尾点被吃掉了：$parent 里只有 —— $listing" ;;
  esac
}

set_attrs() {
  local cur="$1" lv
  if ! have_fatattr; then
    echo "  未找到 fatattr，HIDDEN/SYSTEM 没有打上。补一句再跑：sudo apt install -y fatattr" >&2
    return 0
  fi
  for lv in "${LEVELS[@]}"; do
    cur="$cur/$lv"
    fatattr +h +s "$cur" 2>/dev/null || echo "  属性设置失败：$lv" >&2
  done
  echo "  已给 7 层目录打上 HIDDEN|SYSTEM"
}

cmd_deploy() {
  local mp="$1"
  check_mount "$mp"
  build "$mp"
  assert_name "$mp"
  [ -e "$DEEPEST/.nomedia" ] || : > "$DEEPEST/.nomedia"
  echo "  已放 .nomedia"
  set_attrs "$DEEPEST"
  sync
  echo "完成。手机上打开普通管理器，RECYCLER88 里应该是空的。"
}

cmd_pack() {
  local mp="$1" tgz="$2"
  [ -f "$tgz" ] || die "找不到包：$tgz"
  tgz="$(realpath "$tgz")"
  check_mount "$mp"
  tar -xzf "$tgz" --no-same-owner -C "$mp"
  local lv cur="$mp"
  for lv in "${LEVELS[@]}"; do cur="$cur/$lv"; done
  DEEPEST="$cur"
  assert_name "$mp"
  set_attrs "$DEEPEST"
  sync
  echo "已从包展开并处理完毕。"
}

cmd_verify() {
  local mp="$1" cur="$1" lv attrs
  check_mount "$mp"
  for lv in "${LEVELS[@]}"; do
    cur="$cur/$lv"
    if [ -d "$cur" ]; then
      if have_fatattr; then attrs="$(fatattr "$cur" 2>/dev/null || true)"; else attrs="(缺 fatattr)"; fi
      printf '  %-52s 存在  属性=%s\n' "$lv" "$attrs"
    else
      printf '  %-52s 缺失\n' "$lv"
    fi
  done
  echo "  最深层内容：" >&2
  ls -A "$cur" >&2 || true
}

cmd_clean() {
  local mp="$1" cur="$1" lv
  check_mount "$mp"
  for lv in "${LEVELS[@]}"; do
    cur="$cur/$lv"
    [ -d "$cur" ] || { echo "跳过（不存在）：$lv"; return 0; }
  done
  if have_fatattr; then
    set +e
    fatattr -h -s "$cur" 2>/dev/null
    set -e
  fi
  rm -rf "$cur"
  local p="$cur" depth
  for depth in 6 5 4 3 2 1; do
    p="$(dirname "$p")"
    rmdir "$p" 2>/dev/null || { echo "保留（非空）：$p"; break; }
  done
  sync
  echo "已清理。"
}

[ $# -ge 1 ] || usage

case "$1" in
  deploy) [ $# -eq 2 ] || usage; cmd_deploy "$2" ;;
  pack)   [ $# -eq 3 ] || usage; cmd_pack "$2" "$3" ;;
  verify) [ $# -eq 2 ] || usage; cmd_verify "$2" ;;
  clean)  [ $# -eq 2 ] || usage; cmd_clean "$2" ;;
  *) usage ;;
esac
