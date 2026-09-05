"""Trusted bootstrap for a read-only, single-process Python function call.

This file runs only inside contained_python's namespace. The parent verifier
never imports the candidate. Returned values are untrusted test observations.
"""
import ctypes
import errno
import importlib.util
import json
from pathlib import Path
import resource
import sysconfig


def restrict():
    limits = {
        resource.RLIMIT_CPU: 2,
        resource.RLIMIT_AS: 256 * 1024 * 1024,
        resource.RLIMIT_STACK: 8 * 1024 * 1024,
        resource.RLIMIT_FSIZE: 0,
        resource.RLIMIT_NOFILE: 32,
        resource.RLIMIT_NPROC: 0,
        resource.RLIMIT_CORE: 0,
    }
    for kind, value in limits.items():
        resource.setrlimit(kind, (value, value))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        raise RuntimeError("no_new_privs failed")
    seccomp = ctypes.CDLL("/usr/lib/" + sysconfig.get_config_var("MULTIARCH") + "/libseccomp.so.2", use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                       ctypes.c_int, ctypes.c_uint]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    context = seccomp.seccomp_init(0x7FFF0000)
    if not context:
        raise RuntimeError("seccomp_init failed")
    names = (
        "clone", "clone3", "fork", "vfork", "execve", "execveat", "setsid", "setpgid",
        "shmget", "shmat", "shmdt", "shmctl", "semget", "semop", "semtimedop",
        "semctl", "msgget", "msgsnd", "msgrcv", "msgctl", "ipc",
        "memfd_create", "memfd_secret", "eventfd", "eventfd2", "timerfd_create",
        "inotify_init", "inotify_init1", "fanotify_init", "mq_open", "pidfd_open",
        "socket", "socketpair", "connect", "bind", "listen", "accept",
        "accept4", "unshare", "setns", "mount", "umount2", "pivot_root",
        "move_mount", "open_tree", "fsopen", "fsmount", "fspick", "fsconfig",
        "ptrace", "process_vm_readv", "process_vm_writev", "pidfd_getfd",
        "bpf", "perf_event_open", "keyctl", "add_key", "request_key",
        "io_uring_setup", "io_uring_enter", "io_uring_register",
        "userfaultfd", "reboot", "kexec_load", "kexec_file_load",
        "init_module", "finit_module", "delete_module", "swapon", "swapoff",
    )
    try:
        for name in names:
            number = seccomp.seccomp_syscall_resolve_name(name.encode())
            if number < 0:
                if name in {"clone", "execve", "socket", "unshare", "setsid",
                            "shmget", "shmat", "shmdt", "shmctl", "semget", "semop",
                            "semtimedop", "semctl", "msgget", "msgsnd", "msgrcv", "msgctl"}:
                    raise RuntimeError("mandatory syscall unknown: " + name)
                continue
            if seccomp.seccomp_rule_add(context, 0x00050000 | errno.EPERM,
                                        number, 0) != 0:
                raise RuntimeError("seccomp rule failed: " + name)
        if seccomp.seccomp_load(context) != 0:
            raise RuntimeError("seccomp_load failed")
    finally:
        seccomp.seccomp_release(context)


def main():
    request = json.loads(Path("/input/request.json").read_text())
    restrict()
    spec = importlib.util.spec_from_file_location("candidate", "/input/candidate.py")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        value = getattr(module, request["function"])(*request["arguments"])
        result = {"status": "returned", "value": value}
    except BaseException as error:
        result = {"status": "error", "error_type": type(error).__name__,
                  "error_message": str(error)[:1000]}
    print(json.dumps(result, ensure_ascii=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
