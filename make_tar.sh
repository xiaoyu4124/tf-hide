#!/usr/bin/env bash
# make_tar.sh —— 在任意 Linux 上生成带尾点名字的 tar 包（不碰卡）
#
# 产物解压到 FAT 挂载点即可得到同名目录树；DOS 属性仍需 fatattr 补：
#   ./tf_hide_armbian.sh pack /mnt/sdcard tf_hidden_tree.tar.gz
#
# 用法：
#   ./make_tar.sh [输出文件名，默认 tf_hidden_tree.tar.gz]

set -euo pipefail

OUT="${1:-tf_hidden_tree.tar.gz}"

LEVELS=(
  "RECYCLER88"
  "MICROSOFT-7701091-6666888-16826688.."
  '$$$'
  'com8.{21EC2020-3AEA-1069-A2DD-08002B30309D}'
  "su-heng"
  "local"
  "4124"
)

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cur="$tmp"
for lv in "${LEVELS[@]}"; do
  cur="$cur/$lv"
  mkdir "$cur"
done
: > "$cur/.nomedia"

tar -czf "$OUT" -C "$tmp" "${LEVELS[0]}"

echo "已生成：$OUT"
tar -tzf "$OUT" | sed 's/^/  /'
