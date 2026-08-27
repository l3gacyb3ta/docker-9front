#!/usr/bin/env python3
"""One-time provisioning of the 9front image: set the host owner's password.

Runs only on first start (guarded by a sentinel next to the disk image) and
only when P9_PASSWORD is set.  Otherwise whatever credentials the published
image carries are left alone.

/adm/keys is encrypted with the host owner's key from nvram, so the order
matters and it takes two boots:

  boot 1  auth/wrkey            write the new machine key to nvram
  boot 2  rebuild /adm/keys     factotum now holds the new key, so the key
          auth/changeuser       file gets re-encrypted with it
  boot 3  check the console says "N keys read in AES format"

Doing changeuser before wrkey (or skipping the reboot between them) leaves a
key file the auth server cannot decrypt, and every login fails with
"0 keys read in AES format".

Because the key file has to be re-encrypted under the new machine key, it is
rebuilt from scratch -- any extra users the published image carried are
dropped.  That is fine on a fresh volume, which is the only time this runs.
"""
import os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vm

USER = os.environ.get("P9_HOSTOWNER", "glenda")
DOM = os.environ.get("P9_AUTHDOM", "9front")
PW = os.environ.get("P9_PASSWORD", "")
SENTINEL = os.path.join(os.path.dirname(vm.DISK), ".provisioned")
BOOT_TIMEOUT = float(os.environ.get("PROVISION_BOOT_TIMEOUT", "600"))


def log(msg):
    print("provision: " + msg, flush=True)


def sink(d):
    sys.stdout.buffer.write(d)
    sys.stdout.buffer.flush()


def dialog(con, cmd, steps, timeout=300):
    """Send cmd, then walk a fixed prompt/reply script.

    Strictly sequential: each step only looks at output produced after the
    previous prompt was answered.  Matching "whichever prompt is on screen"
    instead drifts out of step and happily types the password into the
    expiration-date field.
    """
    con.buf = b""
    con.send(cmd)
    pos = 0
    for pat, reply in steps:
        m = con.expect_from(pat, pos, timeout, sink)
        if m is None:
            raise TimeoutError("never saw %r while running %r" % (pat, cmd))
        pos = m.end()
        con.send(reply)
    if con.expect_from(vm.PROMPT, pos, timeout, sink) is None:
        raise TimeoutError("no shell prompt after: " + cmd)
    return con.text()[pos:]


WRKEY = [
    (r"authid: $", USER),
    (r"authdom: $", DOM),
    (r"secstore key: $", ""),
    (r"\npassword: $", PW),
    (r"\nconfirm password: $", PW),
    (r"enable legacy p9sk1\[no\]: $", ""),
]

# changeuser only asks "assign new Plan 9 password?" for a user that already
# has a key.  Provisioning always rebuilds /adm/keys first, so the user is new
# and that prompt is absent -- but match either opening so this still works if
# it is ever run against an intact key file.
CHANGEUSER_OPEN = re.compile(r"(assign new Plan 9 password\? \[y/n\]: )|(\nPassword: )")

CHANGEUSER_REST = [
    (r"\nConfirm password: $", PW),
    (r"assign new Inferno/POP secret\? \[y/n\]: $", "n"),
    (r"Expiration date[^\n]*: $", ""),
    (r"Post id: $", ""),
    (r"full name[^\n]*: $", ""),
    (r"Department #: $", ""),
    (r"email address[^\n]*: $", ""),
    (r"Sponsor.s email address: $", ""),
]


def changeuser(con, user, timeout=300):
    con.buf = b""
    con.send("auth/changeuser " + user)
    m = con.expect_from(CHANGEUSER_OPEN, 0, timeout, sink)
    if m is None:
        raise TimeoutError("changeuser never asked for a password")
    pos = m.end()
    if m.group(1):                      # existing user: confirm we want a new one
        con.send("y")
        m = con.expect_from(r"\nPassword: $", pos, timeout, sink)
        if m is None:
            raise TimeoutError("changeuser never asked for a password")
        pos = m.end()
    con.send(PW)
    for pat, reply in CHANGEUSER_REST:
        m = con.expect_from(pat, pos, timeout, sink)
        if m is None:
            raise TimeoutError("changeuser stuck before %r" % pat)
        pos = m.end()
        con.send(reply)
    if con.expect_from(r"installed for Plan 9", pos, timeout, sink) is None:
        raise TimeoutError("changeuser did not report success")
    con.expect_from(vm.PROMPT, pos, timeout, sink)


def boot(label):
    log("boot: " + label)
    qemu = vm.start_qemu(forward=False)
    con = vm.Console()
    if not con.expect(vm.PROMPT, BOOT_TIMEOUT, sink):
        qemu.kill()
        raise TimeoutError("guest never reached a shell prompt")
    return qemu, con


def halt(qemu, con):
    con.buf = b""
    con.send("fshalt")
    con.expect(r"done halting", 120, sink)
    try:
        qemu.wait(60)
    except Exception:
        qemu.kill()


def main():
    if not PW:
        log("P9_PASSWORD unset, keeping the image's own credentials")
        return 0
    if os.path.exists(SENTINEL):
        log("already provisioned")
        return 0

    qemu, con = boot("phase 1, write nvram key")
    dialog(con, "auth/wrkey", WRKEY)
    halt(qemu, con)

    qemu, con = boot("phase 2, rebuild the key file")
    con.run("unmount /mnt/keys", 60, sink)
    con.run("kill keyfs | rc", 60, sink)
    con.run("rm -f /adm/keys", 60, sink)
    con.run("auth/keyfs -wp -m /mnt/keys /adm/keys", 60, sink)
    changeuser(con, USER)
    keys = con.run("ls /mnt/keys", 60, sink)
    if USER not in keys:
        log("FAILED: no key for %s after changeuser" % USER)
        qemu.kill()
        return 1
    halt(qemu, con)

    qemu, con = boot("phase 3, verify")
    text = con.buf.decode("utf-8", "replace")
    if not re.search(r"[1-9]\d* keys read in AES format", text):
        log("FAILED: auth server read no keys on boot")
        qemu.kill()
        return 1
    halt(qemu, con)

    open(SENTINEL, "w").write("%s@%s\n" % (USER, DOM))
    log("done, %s@%s can log in with the supplied password" % (USER, DOM))
    return 0


if __name__ == "__main__":
    sys.exit(main())
