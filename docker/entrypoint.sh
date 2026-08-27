#!/bin/sh
# Boot 9front as a CPU server.  The disk image lives on the mounted volume and
# is fetched once from DISK_IMAGE_URL if the volume is empty.
set -eu

DISK="${DISK_PATH:-/data/9front.qcow2}"
RUN="${RUN:-/run/9front}"
mkdir -p "$RUN" "$(dirname "$DISK")"

if [ ! -f "$DISK" ]; then
	if [ -z "${DISK_IMAGE_URL:-}" ]; then
		echo "fatal: no disk at $DISK and DISK_IMAGE_URL unset" >&2
		exit 1
	fi
	echo "first boot: fetching disk image from $DISK_IMAGE_URL"
	curl -fL --retry 3 --retry-delay 5 -o "$DISK.part" "$DISK_IMAGE_URL"

	if [ -n "${DISK_IMAGE_SHA256:-}" ]; then
		echo "$DISK_IMAGE_SHA256  $DISK.part" | sha256sum -c - || {
			echo "fatal: checksum mismatch" >&2
			rm -f "$DISK.part"
			exit 1
		}
	fi

	# 9front publishes its images gzipped; accept either form.
	if gzip -t "$DISK.part" 2>/dev/null; then
		echo "decompressing"
		gzip -dc "$DISK.part" > "$DISK.raw" && mv "$DISK.raw" "$DISK" && rm -f "$DISK.part"
	else
		mv "$DISK.part" "$DISK"
	fi
	echo "disk image ready: $(qemu-img info "$DISK" | sed -n 's/^virtual size: /virtual size /p')"
fi

# Optional: set the host owner's password on first start.  No-op unless
# P9_PASSWORD is set; see docker/provision.py for why it needs three boots.
python3 /opt/9front/provision.py

exec python3 /opt/9front/supervise.py
