#!/usr/bin/env python3
"""Run the 9front VM as the container's main process.

Boots qemu, relays the guest's serial console to stdout so it lands in the pod
logs, and on SIGTERM runs fshalt and waits for hjfs to flush before letting
qemu die -- a hard kill on a pod restart risks the file system.

The console is also mirrored to $RUN/console.log and accepts input on the
$RUN/console.in fifo, which is what `9console send|run|log` talks to, so you
can drive the machine from `docker exec` / exec_in_pod.
"""
import os, select, signal, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vm

HALT_TIMEOUT = float(os.environ.get("HALT_TIMEOUT", "90"))
stopping = False


def out(data):
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def main():
    os.makedirs(vm.RUN, exist_ok=True)
    if not os.path.exists(vm.FIFO):
        os.mkfifo(vm.FIFO)
    log = open(vm.LOG, "ab", buffering=0)

    qemu = vm.start_qemu(forward=True)
    con = vm.Console()
    # O_RDWR so the fifo never reports EOF when no writer is attached.
    fifo = os.open(vm.FIFO, os.O_RDWR | os.O_NONBLOCK)

    def sink(d):
        out(d)
        log.write(d)

    def on_term(_sig, _frm):
        global stopping
        if stopping:
            return
        stopping = True

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    inputs = {0, fifo}
    halt_deadline = None
    while True:
        if qemu.poll() is not None:
            out(b"\nqemu exited with %d\n" % qemu.returncode)
            return qemu.returncode
        if stopping and halt_deadline is None:
            out(b"\nSIGTERM: halting 9front cleanly...\n")
            try:
                con.send("fshalt")
            except OSError:
                pass
            halt_deadline = time.time() + HALT_TIMEOUT
        if halt_deadline and time.time() > halt_deadline:
            out(b"\nhalt timed out, terminating qemu\n")
            qemu.terminate()
            try:
                qemu.wait(10)
            except Exception:
                qemu.kill()
            return 1

        try:
            con.pump(0.3, sink)
        except EOFError:
            out(b"\nconsole closed\n")
            qemu.wait(30)
            return qemu.returncode or 0

        # stdin (docker attach) and the fifo both feed the console
        for src in list(inputs):
            r, _, _ = select.select([src], [], [], 0)
            if not r:
                continue
            try:
                d = os.read(src, 65536)
            except (BlockingIOError, OSError):
                continue
            if d:
                con.s.sendall(d)
            elif src == 0:
                # `docker run -d` leaves stdin at EOF, and an EOF fd selects
                # readable forever -- stop polling it or we spin at 100% cpu.
                inputs.discard(0)


if __name__ == "__main__":
    sys.exit(main())
