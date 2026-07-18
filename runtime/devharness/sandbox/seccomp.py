"""Seccomp syscall filtering for the sandbox (Track 1d) — the final hardening layer.

After the worktree-confining pivot_root + the privilege drop, the command is wrapped in a seccomp BPF
filter that DENIES (EPERM) the escape/privilege syscalls a build/test never needs: mount/umount2, the
module family (init/finit/delete), kexec, ptrace, bpf, keyctl/add_key/request_key, userfaultfd,
unshare/setns/pivot_root, open_by_handle_at, perf_event_open, mount_setattr. Benign syscalls pass; an escape
attempt fails with EPERM rather than killing legitimate work.

The installer is a self-contained `python3 -c` ctypes program — no compiler or extra file on the target, and
python3 is in the bound `/usr`. Fail-closed: if the filter can't be installed, the command does NOT run
(exit 159). x86_64 only: a non-x86_64 `AUDIT_ARCH` traps to KILL, AND any syscall number with the x32 bit
(`nr >= 0x40000000`) traps to KILL — x32 shares `AUDIT_ARCH_X86_64`, so without that guard an x32 `mount`
(`0x40000000|165`) would bypass the number-only denylist (security review H1). Verified live (WSL):
`Seccomp: 2`, an `unshare --user` that succeeds unprivileged is denied EPERM.

NOTE the denylist deliberately excludes `clone`/`clone3` — blocking them would break `fork`, and the filter
is inherited across clone/fork (with NO_NEW_PRIVS), so a child in a new namespace still carries it.
"""

import shlex

# x86_64 syscall numbers for escape/privilege primitives, denied with EPERM. Covers the legacy mount API
# (165/166/442) AND the new mount API (428-433), the module family, kexec, ptrace, bpf, keyctl, userfaultfd,
# unshare/setns/pivot_root, io_uring (425-427, a known filter-bypass engine), process_vm_*, memfd_secret.
_DENY = [165, 166, 167, 168, 169, 155, 101, 246, 320, 175, 176, 313,
         321, 248, 249, 250, 323, 272, 308, 304, 298, 442,
         428, 429, 430, 431, 432, 433, 447, 425, 426, 427, 310, 311]

# A self-contained installer: build the BPF denylist, set NO_NEW_PRIVS, load the filter, then exec the
# command (sys.argv[1:]). %s is the comma-joined deny list.
_INSTALLER = (
    "import ctypes,os,struct,sys\n"
    "A=0xC000003E;NNP=38;SMF=1;SYS=317;ALLOW=0x7FFF0000;EPERM=0x00050001;KILL=0x80000000\n"
    "LD,W,ABS,JMP,JEQ,JGE,K,RET=0,0,0x20,5,0x10,0x30,0,6\n"
    "DENY=[%s]\n"
    "def Sx(c,k):return struct.pack('HBBI',c,0,0,k)\n"
    "def Jx(c,k,a,b):return struct.pack('HBBI',c,a,b,k)\n"
    # arch gate, then x32 gate (nr>=0x40000000 -> KILL), then the number denylist
    "p=b''.join([Sx(LD|W|ABS,4),Jx(JMP|JEQ|K,A,1,0),Sx(RET|K,KILL),"
    "Sx(LD|W|ABS,0),Jx(JMP|JGE|K,0x40000000,0,1),Sx(RET|K,KILL)]"
    "+sum([[Jx(JMP|JEQ|K,n,0,1),Sx(RET|K,EPERM)] for n in DENY],[])+[Sx(RET|K,ALLOW)])\n"
    "class Fp(ctypes.Structure):_fields_=[('l',ctypes.c_ushort),('f',ctypes.c_void_p)]\n"
    "bb=ctypes.create_string_buffer(p,len(p));fp=Fp(len(p)//8,ctypes.cast(bb,ctypes.c_void_p))\n"
    "lc=ctypes.CDLL('libc.so.6',use_errno=True)\n"
    "if lc.prctl(NNP,1,0,0,0)!=0 or lc.syscall(SYS,SMF,0,ctypes.byref(fp))!=0:\n"
    "    sys.stderr.write('seccomp: install failed (fail-closed)\\n');os._exit(159)\n"
    "os.execvp(sys.argv[1],sys.argv[1:])\n"
) % ",".join(str(n) for n in _DENY)


def seccomp_exec(cmd: str) -> str:
    """A shell fragment that runs ``cmd`` (an already shlex-joined command) under the seccomp filter:
    ``python3 -c <installer> <cmd>``. Use as the final ``exec`` target inside the sandbox."""
    return f"python3 -c {shlex.quote(_INSTALLER)} {cmd}"
