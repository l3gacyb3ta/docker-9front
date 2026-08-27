#!/usr/bin/env bash
# Connect to the 9front CPU server running in the VM.
#
#   ./connect.sh                  graphical drawterm session
#   ./connect.sh -c 'echo hi'     text-mode, run one command and exit
#
# Password for glenda: plan9cpu
set -euo pipefail

HOST_ADDR="${HOST_ADDR:-127.0.0.1}"
CPU_PORT="${CPU_PORT:-17019}"
AUTH_PORT="${AUTH_PORT:-20567}"
USER9="${USER9:-glenda}"

# drawterm derives the secstore address from the auth address when -s is absent.
# Because our auth address carries an explicit (non-default) port, that would
# make drawterm speak the secstore protocol at authsrv and hang forever, so
# point secstore at a port nothing listens on: the dial fails fast and drawterm
# falls through to asking for the password.
exec drawterm \
	-h "tcp!$HOST_ADDR!$CPU_PORT" \
	-a "tcp!$HOST_ADDR!$AUTH_PORT" \
	-s "tcp!$HOST_ADDR!1" \
	-u "$USER9" \
	"$@"
