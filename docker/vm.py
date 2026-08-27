"""Shared bits for running the 9front VM inside the container.

The virtual hardware here is the contract with the disk image: virtio-blk
(9front calls it /dev/sdF0, which is what plan9.ini's nobootprompt names) and
e1000.  Changing either means the image stops booting unattended.
"""
import os, re, select, socket, subprocess, time

RUN = os.environ.get("RUN", "/run/9front")
DISK = os.environ.get("DISK_PATH", "/data/9front.qcow2")
CONSOLE_SOCK = os.path.join(RUN, "console.sock")
MONITOR_SOCK = os.path.join(RUN, "monitor.sock")
LOG = os.path.join(RUN, "console.log")
FIFO = os.path.join(RUN, "console.in")

# 17019 rcpu (the cpu service), 17020 tls 9fs, 567 authsrv.  The host-side port
# is overridable because binding 567 needs root -- which you have inside the
# container, but not when running these scripts directly on a workstation.
PORTS = [
    (int(os.environ.get("PORT_RCPU", "17019")), 17019),
    (int(os.environ.get("PORT_9FS", "17020")), 17020),
    (int(os.environ.get("PORT_AUTH", "567")), 567),
]
PROMPT = re.compile(r"[a-z0-9_-]+# $", re.M)


def accel():
    """KVM when the pod has /dev/kvm, otherwise plain emulation."""
    if os.access("/dev/kvm", os.W_OK):
        return ["-accel", "kvm", "-cpu", "host"]
    return ["-accel", "tcg,thread=multi", "-cpu", "max"]


def qemu_argv(forward=True):
    net = "user,id=n0"
    if forward:
        net += "," + ",".join("hostfwd=tcp::%d-:%d" % (h, g) for h, g in PORTS)
    return [
        "qemu-system-x86_64",
        "-M", "pc",
        *accel(),
        "-smp", os.environ.get("QEMU_CPUS", "2"),
        "-m", os.environ.get("QEMU_MEM", "1024"),
        "-drive", "file=%s,format=qcow2,if=none,id=hd0,cache=writeback" % DISK,
        "-device", "virtio-blk-pci,drive=hd0",
        "-netdev", net,
        "-device", "e1000,netdev=n0",
        "-display", "none",
        "-serial", "unix:%s,server=on,wait=off" % CONSOLE_SOCK,
        "-monitor", "unix:%s,server=on,wait=off" % MONITOR_SOCK,
    ]


def start_qemu(forward=True):
    os.makedirs(RUN, exist_ok=True)
    for p in (CONSOLE_SOCK, MONITOR_SOCK):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass
    return subprocess.Popen(qemu_argv(forward))


class Console:
    """The guest's serial console, with expect/send on top."""

    def __init__(self, timeout=120):
        end = time.time() + timeout
        while True:
            try:
                self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.s.connect(CONSOLE_SOCK)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if time.time() > end:
                    raise
                time.sleep(0.2)
        self.s.setblocking(False)
        self.buf = b""

    def pump(self, seconds=0.2, sink=None):
        r, _, _ = select.select([self.s], [], [], seconds)
        if not r:
            return b""
        try:
            d = self.s.recv(65536)
        except BlockingIOError:
            return b""
        if d == b"":
            raise EOFError("console closed")
        self.buf += d
        if sink:
            sink(d)
        return d

    def send(self, text):
        self.s.sendall((text + "\n").encode())

    def expect(self, pattern, timeout=180, sink=None):
        rx = pattern if hasattr(pattern, "search") else re.compile(pattern, re.M)
        end = time.time() + timeout
        while time.time() < end:
            self.pump(0.3, sink)
            if rx.search(self.buf.decode("utf-8", "replace").replace("\r", "")):
                return True
        return False

    def expect_from(self, pattern, pos, timeout=180, sink=None):
        """Find pattern at or after pos in the console text; return its end.

        Positions index the decoded, CR-stripped text, which only ever grows at
        the end, so they stay valid as more output arrives.
        """
        rx = pattern if hasattr(pattern, "search") else re.compile(pattern)
        end = time.time() + timeout
        while True:
            m = rx.search(self.text(), pos)
            if m:
                return m
            if time.time() > end:
                return None
            self.pump(0.3, sink)

    def text(self):
        return self.buf.decode("utf-8", "replace").replace("\r", "")

    def run(self, cmd, timeout=180, sink=None):
        self.buf = b""
        self.send(cmd)
        if not self.expect(PROMPT, timeout, sink):
            raise TimeoutError("no prompt after: " + cmd)
        return self.buf.decode("utf-8", "replace").replace("\r", "")
