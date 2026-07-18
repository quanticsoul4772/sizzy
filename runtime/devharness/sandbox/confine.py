"""Shared pivot_root worktree-confinement setup for the WSL + VPS launchers (Track 1c, hardened post-review).

Builds a fresh root holding ONLY the system dirs (`--rbind` — `/usr` is a separate mount on WSL2) + the
worktree bound at `/work`, then `pivot_root`s into it so `/home`, the Windows drives, `~/.ssh`, `/root` and
other projects are gone. Hardening from the security review:

- **Minimal /dev (M2):** a fresh tmpfs with only the safe char nodes (null/zero/full/random/urandom/tty) and
  a **private** `/dev/shm` tmpfs — NOT the host's `--rbind`'d /dev, whose shared `/dev/shm` would be a
  cross-sandbox / sandbox↔host data channel.
- **/proc masking (L3):** a fresh procfs for the pid namespace with `/proc/{sysrq-trigger,kcore,kmsg}` masked
  by `/dev/null` (defense-in-depth atop the unprivileged-uid DAC).

Returns the shell through `cd /work; echo <sentinel> >&2; `; the caller appends its `exec …`. `worktree_src`
is the (already-quoted-if-needed) source path to bind at `/work`.
"""

_NR = "/tmp/devharness-sb-root"


def pivot_setup(worktree_src: str, sentinel: str) -> str:
    return (
        f"set -e; NR={_NR}; rm -rf $NR 2>/dev/null || true; "
        "mkdir -p $NR/work $NR/.oldroot $NR/usr $NR/etc $NR/tmp $NR/proc $NR/dev; "
        "mount --make-rprivate /; mount --bind $NR $NR; "
        f"mount --rbind {worktree_src} $NR/work; mount --rbind /usr $NR/usr; "
        'for x in bin sbin lib lib64; do '
        'if [ -L /$x ]; then ln -s "$(readlink /$x)" $NR/$x; '
        'elif [ -d /$x ]; then mkdir -p $NR/$x; mount --rbind /$x $NR/$x; fi; done; '
        "mount --rbind /etc $NR/etc; mount -t tmpfs tmpfs $NR/tmp; "
        # minimal /dev: a tmpfs + only the safe char nodes + a PRIVATE /dev/shm (not the host's).
        # /dev/tty is deliberately NOT bound (audit F2): a build/test runner doesn't need it, and binding a
        # shared controlling tty with ioctl unfiltered is a latent TIOCSTI host-keystroke-injection surface.
        "mount -t tmpfs tmpfs $NR/dev; "
        'for n in null zero full random urandom; do '
        '[ -e /dev/$n ] && touch $NR/dev/$n && mount --bind /dev/$n $NR/dev/$n; done; '
        "mkdir -p $NR/dev/shm; mount -t tmpfs tmpfs $NR/dev/shm; "
        # fresh /proc for the pid namespace; mask the sensitive entries with /dev/null
        "mount -t proc proc $NR/proc; "
        'for p in sysrq-trigger kcore kmsg; do '
        '[ -e $NR/proc/$p ] && mount --bind /dev/null $NR/proc/$p 2>/dev/null || true; done; '
        "cd $NR; pivot_root . .oldroot; umount -l /.oldroot; cd /work; "
        f"echo {sentinel} >&2; "
    )
