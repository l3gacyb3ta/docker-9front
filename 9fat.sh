#!/usr/bin/env bash
# Mount/unmount the 9fat partition of cpu.qcow2 on the host so plan9.ini can be
# edited without booting the VM.  Uses a qemu FUSE export (no root, no nbd) plus
# mtools at the 9fat offset.
#
#   ./9fat.sh mount     -> exports the image and prints the MTOOLSRC to use
#   ./9fat.sh cat       -> print plan9.ini
#   ./9fat.sh put FILE  -> install FILE as plan9.ini
#   ./9fat.sh umount
set -euo pipefail

IMG="${IMG:-$(dirname "$(readlink -f "$0")")/cpu.qcow2}"
WORK="${WORK:-${TMPDIR:-/tmp}/9fat-$(id -u)}"
RAW="$WORK/raw"
RC="$WORK/mtoolsrc"
# 9fat lives at the start of the type-0x39 MBR partition (LBA 63).
OFFSET=$((63 * 512))

do_mount() {
	mkdir -p "$WORK"
	[ -e "$RAW" ] || : > "$RAW"
	mountpoint -q "$RAW" 2>/dev/null && return 0
	[ -s "$RAW" ] && return 0
	qemu-storage-daemon \
		--blockdev node-name=prot,driver=file,filename="$IMG" \
		--blockdev node-name=fmt,driver=qcow2,file=prot \
		--export type=fuse,id=exp,node-name=fmt,mountpoint="$RAW",writable=on \
		--pidfile "$WORK/pid" --daemonize
	cat > "$RC" <<-EOF
		drive z: file="$RAW" offset=$OFFSET
		mtools_skip_check=1
	EOF
}

do_umount() {
	fusermount3 -u "$RAW" 2>/dev/null || true
	[ -f "$WORK/pid" ] && kill "$(cat "$WORK/pid")" 2>/dev/null || true
	rm -f "$WORK/pid"
}

case "${1:-}" in
mount)  do_mount; echo "export MTOOLSRC=$RC" ;;
umount) do_umount ;;
cat)    do_mount; MTOOLSRC=$RC mtype z:/plan9.ini; do_umount ;;
put)    do_mount; MTOOLSRC=$RC mcopy -o "$2" z:/plan9.ini; do_umount ;;
ls)     do_mount; MTOOLSRC=$RC mdir -/ z:; do_umount ;;
*)      echo "usage: $0 {mount|umount|cat|put FILE|ls}" >&2; exit 2 ;;
esac
