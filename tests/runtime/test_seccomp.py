"""Track 1d: the seccomp installer wraps the command + denies the escape/privilege syscalls.

The BPF filter's runtime behaviour (a denied syscall returns EPERM, an allowed one runs) is exercised live
on the real launchers (the gated SC-3 tests + the operator-driven verification); this guards the structure:
the command runs under the installer, the installer is fail-closed, and the denylist covers the primitives.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.sandbox import seccomp
from devharness.sandbox.seccomp import seccomp_exec


def test_seccomp_exec_wraps_command_under_the_python_installer():
    frag = seccomp_exec("pytest -q")
    assert frag.startswith("python3 -c ")
    assert frag.rstrip().endswith("pytest -q")  # the real command is the final arg
    # the installer execs the command only AFTER loading the filter
    assert "os.execvp(sys.argv[1],sys.argv[1:])" in frag


def test_installer_is_fail_closed_and_sets_no_new_privs():
    assert "os._exit(159)" in seccomp._INSTALLER  # if the filter can't load, the command does NOT run
    assert "NNP=38" in seccomp._INSTALLER          # PR_SET_NO_NEW_PRIVS, required before SET_MODE_FILTER


def test_x32_abi_bypass_is_guarded():  # review H1
    # x32 shares AUDIT_ARCH_X86_64 but sets bit 0x40000000 in the nr; the filter must KILL on it, else the
    # number-only denylist is bypassable (an x32 `mount` = 0x40000000|165 matches no deny entry).
    assert "JGE" in seccomp._INSTALLER and "0x40000000" in seccomp._INSTALLER


def test_denylist_covers_the_escape_primitives():
    # legacy + NEW mount API (review M1), the module family, kexec, ptrace, bpf, userfaultfd, io_uring,
    # unshare/setns/pivot_root
    for nr in (165, 166, 442, 428, 429, 430, 431, 432, 433,  # mount + new mount API
               101, 272, 308, 155, 175, 176, 313, 246, 321, 323, 425, 426, 427):
        assert nr in seccomp._DENY, f"syscall {nr} not denied"


def test_clone_is_NOT_denied():  # blocking clone(56)/clone3(435) would break fork; filter inherits anyway
    assert 56 not in seccomp._DENY and 435 not in seccomp._DENY
