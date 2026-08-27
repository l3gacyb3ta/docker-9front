# 9front CPU server in QEMU

A headless 9front CPU server running under QEMU/KVM, reachable from the Linux
host with `drawterm`.

Everything needed is in the flake — `nix develop`, or let direnv do it.

## Quick start

```sh
./run-vm.sh                       # boot the VM (daemonises, no display)
./connect.sh                      # graphical drawterm session
./connect.sh -G -c 'echo hi'      # or run a single command, text mode
```

Password for `glenda` is **`plan9cpu`**.

To drive the machine's own console instead (it is on a serial port, not a
screen):

```sh
./console.py attach &             # relay the console into $RUN/console.log
./console.py run 'cat /net/ndb'
./console.py log 2000
./console.py halt                 # clean fshalt
```

`$RUN` defaults to `/tmp/9front-cpu-$UID` and holds the console socket, the
qemu monitor socket, the pid file and the console log.

## The setup

| | |
|---|---|
| disk image | `cpu.qcow2` (working copy; `9front.amd64.qcow2` is left pristine) |
| sysname | `fern` |
| auth domain | `9front` |
| hostowner | `glenda`, password `plan9cpu` |
| root fs | hjfs on `/dev/sdF0/fs` (virtio-blk) |
| guest IP | `10.0.2.15` (qemu user-mode networking) |

`plan9.ini` (in the 9fat partition) is:

```
bootfile=9pc64
service=cpu
console=0 b115200
nobootprompt=local!/dev/sdF0/fs
```

`service=cpu` is what makes it a CPU server; `console=0` puts the console on
the serial port so the VM needs no display; `nobootprompt` stops it waiting at
the `bootargs is (tcp, tls, il, local!device)` prompt on every boot.

The device name is a property of the *virtual hardware*, not the image:
virtio-blk is `sdF0`, AHCI is `sdE0`. `run-vm.sh` and the container both use
virtio-blk so one image boots unattended in both.

The machine is its own auth server. `/lib/ndb/local` already carried
`auth=fern authdom=9front` and an `ipnet=slirp` entry with `cpu=fern`; the
listeners come from `/rc/bin/service/tcp17019` (rcpu) and
`/rc/bin/service.auth/tcp567` (authsrv), both started by `cpurc`.

### Ports

| host | guest | service |
|---|---|---|
| 17019 | 17019 | `rcpu` — the CPU service |
| 20567 | 567 | `authsrv` — tickets |

9front's CPU service is **rcpu on 17019**, not the legacy `cpu` on 17010 —
there is no listener on 17010, so pointing drawterm there just hangs.

Auth is forwarded to **20567** rather than 567 because binding 567 on the host
would need root. Everything downstream has to carry that port explicitly, which
causes the secstore gotcha below.

## Gotchas worth remembering

**drawterm and secstore.** With no `-s`, drawterm derives the secstore address
from the auth address. Since our auth address has an explicit non-default port,
drawterm ends up speaking the secstore protocol to `authsrv`, and both sides
wait for each other forever — drawterm hangs with no output and never prompts
for a password. `connect.sh` passes `-s tcp!127.0.0.1!1` so that dial fails
immediately and drawterm falls through to the password prompt.

**Order of `auth/wrkey` and `auth/changeuser`.** `/adm/keys` is encrypted with
the host owner's key from nvram. Running `auth/wrkey` after `auth/changeuser`
leaves the existing `/adm/keys` undecryptable, and the next boot says
`keyfs: 0: no termination` / `0 keys read in AES format` — the auth server then
has no keys at all. Do it in this order:

```
auth/wrkey                                    # set the machine key first
unmount /mnt/keys; kill keyfs | rc            # then rebuild the key file
rm /adm/keys
auth/keyfs -wp -m /mnt/keys /adm/keys
auth/changeuser glenda
```

A healthy boot prints `1 keys read in AES format`.

**rc syntax.** `=` is its own token to rc, so `echo FOO=$bar` is a syntax
error, not an argument. Same for double quotes — rc does not have them.

## Running it in a container

`run-vm.sh` and the container give the guest identical virtual hardware
(`-M pc`, virtio-blk, e1000), so the same disk image works in both. The only
difference is KVM locally versus plain emulation on a pod with no `/dev/kvm`.

```sh
docker build -t 9front-cpu .
docker run -d --name 9front \
  -p 17019:17019 -p 17020:17020 -p 567:567 \
  -v 9front-data:/data \
  -e DISK_IMAGE_URL=https://your-host/9front-cpu.qcow2 \
  9front-cpu
```

The disk image is **not** baked into the container image. It is fetched from
`DISK_IMAGE_URL` into the volume the first time the container starts and reused
from then on; publish the configured `cpu.qcow2` somewhere the pod can reach.
A `.gz` is detected and decompressed, and `DISK_IMAGE_SHA256` is checked when
set.

Inside the container the process can bind port 567, so **there is no secstore
workaround to do** — clients connect the ordinary way:

```sh
drawterm -h yourhost -a yourhost -u glenda
```

The `-s` hack in `connect.sh` is only needed for the local setup, where auth has
to live on 20567 because binding 567 as a normal user is not allowed.

### Environment

| variable | default | meaning |
|---|---|---|
| `DISK_IMAGE_URL` | — | where to fetch the image on first start (required if the volume is empty) |
| `DISK_IMAGE_SHA256` | — | optional integrity check on the download |
| `DISK_PATH` | `/data/9front.qcow2` | image location on the volume |
| `QEMU_MEM` / `QEMU_CPUS` | `1024` / `2` | guest size |
| `P9_PASSWORD` | — | if set, take ownership of the credentials on first start |
| `P9_HOSTOWNER` / `P9_AUTHDOM` | `glenda` / `9front` | who that password belongs to |
| `PORT_RCPU` / `PORT_9FS` / `PORT_AUTH` | `17019` / `17020` / `567` | host-side ports inside the container |

### Operating it

The guest console is relayed to stdout, so `docker logs` shows the 9front boot
and any kernel messages. `9console` drives the same console from outside:

```sh
docker exec 9front 9console run 'ps'
docker exec 9front 9console log 4000
docker logs -f 9front
```

`docker stop` sends SIGTERM, which runs `fshalt` and waits for hjfs to flush
before qemu exits — a hard kill risks the file system, so give it room
(`stop_grace_period: 120s` in the compose file). The healthcheck connects to
17019 and requires the real auth banner (`dp9ik@9front`) rather than just
checking that qemu is alive.

### Changing the password on first start

Setting `P9_PASSWORD` runs `docker/provision.py` once, before the machine goes
into service. It needs three boots, because `/adm/keys` is encrypted with the
host owner's key from nvram:

```
boot 1  auth/wrkey        write the new machine key
boot 2  rebuild /adm/keys, auth/changeuser   factotum now has the new key
boot 3  assert the console says "N keys read in AES format"
```

It rewrites the key file from scratch, so any *extra* users baked into the
published image are dropped. That is fine on a fresh volume, which is the only
time it runs — a `.provisioned` marker next to the disk keeps it from running
again.

Leave `P9_PASSWORD` unset to keep whatever credentials the published image has.

## Editing plan9.ini without booting

`9fat.sh` exports the qcow2 as a raw file over FUSE (no root, no nbd) and drives
mtools at the 9fat offset:

```sh
./9fat.sh cat            # print plan9.ini
./9fat.sh put file       # install file as plan9.ini
./9fat.sh ls
```

The VM must be shut down first — qemu holds a write lock on the image.
