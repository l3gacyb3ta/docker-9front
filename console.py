#!/usr/bin/env python3
"""Talk to the 9front VM's serial console (qemu unix socket).

The VM has console=0 in plan9.ini, so the whole machine is driveable without a
display.  `attach` must be running for the other subcommands to work.

  console.py attach          relay the console into $RUN/console.log (run first,
                             in the background: console.py attach &)
  console.py log [N]         print the last N bytes of the log
  console.py send TEXT       send TEXT followed by a newline
  console.py run CMD [T]     send CMD and wait up to T seconds for the prompt
  console.py halt            fshalt the guest and wait for it to finish
"""
import os, re, select, socket, subprocess, sys, time

RUN = os.environ.get("RUN", "/tmp/9front-cpu-%d" % os.getuid())
SOCK = os.path.join(RUN, "console.sock")
LOG = os.path.join(RUN, "console.log")
FIFO = os.path.join(RUN, "console.in")
PROMPT = os.environ.get("P9_PROMPT", r"[a-z0-9_-]+# $")


def attach():
    if not os.path.exists(FIFO):
        os.mkfifo(FIFO)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    s.setblocking(False)
    log = open(LOG, "ab", buffering=0)
    # O_RDWR keeps the fifo from reporting EOF when no writer is attached.
    fifo = os.open(FIFO, os.O_RDWR | os.O_NONBLOCK)
    while True:
        r, _, _ = select.select([s, fifo], [], [], 1.0)
        if s in r:
            try:
                data = s.recv(65536)
            except BlockingIOError:
                data = b""
            if data == b"":
                return
            log.write(data)
        if fifo in r:
            try:
                data = os.read(fifo, 65536)
            except BlockingIOError:
                data = b""
            if data:
                s.sendall(data)


def send(text):
    with open(FIFO, "wb", buffering=0) as f:
        f.write(text.encode())


def size():
    try:
        return os.path.getsize(LOG)
    except OSError:
        return 0


def read_from(start):
    try:
        with open(LOG, "rb") as f:
            f.seek(start)
            return f.read().decode("utf-8", "replace")
    except FileNotFoundError:
        return ""


def expect(pattern, timeout, start):
    rx = re.compile(pattern, re.M)
    end = time.time() + timeout
    while time.time() < end:
        buf = read_from(start).replace("\r", "")
        if rx.search(buf):
            return True, buf
        time.sleep(0.25)
    return False, read_from(start).replace("\r", "")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "attach":
        attach()
    elif cmd == "log":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
        print(read_from(max(0, size() - n)), end="")
    elif cmd == "send":
        send(" ".join(sys.argv[2:]) + "\n")
    elif cmd == "run":
        timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
        start = size()
        send(sys.argv[2] + "\n")
        ok, buf = expect(PROMPT, timeout, start)
        print(buf, end="")
        sys.exit(0 if ok else 1)
    elif cmd == "halt":
        start = size()
        send("fshalt\n")
        ok, buf = expect(r"done halting", 60.0, start)
        print(buf, end="")
        sys.exit(0 if ok else 1)
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)


main()
