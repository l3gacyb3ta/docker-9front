#!/bin/sh
# Boot 9front under QEMU. Disk image lives on the Orchard volume;
# fetched once from DISK_IMAGE_URL if the volume is empty.
set -eu

DISK="${DISK_PATH:-/data/9front.qcow2}"
MEM="${QEMU_MEM:-1024}"
CPUS="${QEMU_CPUS:-2}"

if [ ! -f "$DISK" ]; then
    if [ -z "${DISK_IMAGE_URL:-}" ]; then
        echo "fatal: no disk at $DISK and DISK_IMAGE_URL unset" >&2
        exit 1
    fi
    echo "first boot: fetching disk image from $DISK_IMAGE_URL"
    curl -fL --retry 3 --retry-delay 5 -o "$DISK.tmp" "$DISK_IMAGE_URL"
    mv "$DISK.tmp" "$DISK"
fi

# Notes on flags:
#   -accel tcg,thread=multi   MTTCG: one host thread per guest vCPU
#   -nographic                guest console on stdio -> pod logs.
#                             Requires console=0 in plan9.ini.
#   virtio-blk                9front sdvirtio driver; much faster than
#                             emulated IDE under TCG
#   e1000                     9front igbe driver; the boring, known-good
#                             NIC. ethervirtio also works if you want it.
#   hostfwd                   slirp NAT: container port -> guest port.
#                             17019 rcpu, 564 exportfs, 567 authsrv.
#   -monitor unix socket      escape hatch: exec_in_pod + socat to reach
#                             the QEMU monitor without killing console

exec 3< <(printf '\n'; sleep infinity)
exec qemu-system-x86_64 \
    -M pc \
    -accel tcg,thread=multi \
    -cpu max \
    -smp "$CPUS" \
    -m "$MEM" \
    -nographic \
    -drive file="$DISK",format=qcow2,if=none,id=hd0,cache=writeback \
    -device virtio-blk-pci,drive=hd0 \
    -netdev user,id=n0,hostfwd=tcp::17019-:17019,hostfwd=tcp::17020-:17019,hostfwd=tcp::567-:567 \
    -device e1000,netdev=n0 \
    -monitor unix:/tmp/qemu-monitor.sock,server,nowait <&3
