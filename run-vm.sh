#!/usr/bin/env bash
# Boot the 9front CPU server VM headlessly on this machine.
#
# The virtual hardware deliberately matches what the container uses (see
# docker/entrypoint.sh) so one disk image works in both places: virtio-blk
# (which 9front names /dev/sdF0, the device plan9.ini boots from) and e1000.
# The only difference is KVM here vs TCG on a pod without /dev/kvm.
#
# Console is the serial port on a unix socket (plan9.ini has console=0), so no
# display is needed; drive it with ./console.py.  Networking is qemu user-mode
# with the ports drawterm needs forwarded to localhost:
#
#   host 17019 -> guest 17019   rcpu(1), the CPU service
#   host 20567 -> guest 567     authsrv (567 is privileged on the host)
set -euo pipefail

DIR="$(dirname "$(readlink -f "$0")")"
IMG="${IMG:-$DIR/cpu.qcow2}"
RUN="${RUN:-${TMPDIR:-/tmp}/9front-cpu-$(id -u)}"
CPU_PORT="${CPU_PORT:-17019}"
AUTH_PORT="${AUTH_PORT:-20567}"
MEM="${QEMU_MEM:-2048}"
CPUS="${QEMU_CPUS:-4}"

mkdir -p "$RUN"
CONSOLE_SOCK="$RUN/console.sock"
MONITOR_SOCK="$RUN/monitor.sock"
PIDFILE="$RUN/qemu.pid"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
	echo "already running (pid $(cat "$PIDFILE"))" >&2
	exit 1
fi
rm -f "$CONSOLE_SOCK" "$MONITOR_SOCK" "$PIDFILE" "$RUN/console.in"

if [ -w /dev/kvm ]; then
	ACCEL=(-accel kvm -cpu host)
else
	ACCEL=(-accel tcg,thread=multi -cpu max)
fi

exec qemu-system-x86_64 \
	-M pc \
	"${ACCEL[@]}" \
	-smp "$CPUS" \
	-m "$MEM" \
	-drive file="$IMG",format=qcow2,if=none,id=hd0,cache=writeback \
	-device virtio-blk-pci,drive=hd0 \
	-netdev user,id=n0,hostfwd=tcp::"$CPU_PORT"-:17019,hostfwd=tcp::"$AUTH_PORT"-:567 \
	-device e1000,netdev=n0 \
	-display none \
	-serial unix:"$CONSOLE_SOCK",server=on,wait=off \
	-monitor unix:"$MONITOR_SOCK",server=on,wait=off \
	-pidfile "$PIDFILE" \
	-daemonize
