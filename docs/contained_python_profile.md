# Finite Python function profile

This optional development tool runs one JSON function in a separate process.
It is not installed into Nara, the daemon, or the default packet dispatcher.
Its caller must own the private evidence-directory ancestry and lifecycle.
The implementation targets the existing Linux Bubblewrap, system Python and
libseccomp installation; unavailable restrictions fail without a fallback.

The parent copies exact candidate, request and bootstrap bytes before launch.
Only those read-only files, read-only system libraries/interpreter and a
read-only PID-namespace proc mount are visible. There are no writable mounts,
host home/repository mounts, credentials, model sockets or inherited FDs.
All supported user/network/PID/IPC/UTS/cgroup namespaces are requested, with
further user namespaces disabled, capabilities dropped and a new session.

Before candidate import the bootstrap sets no_new_privs, hard resource limits,
and a seccomp denial profile for process creation, exec, sockets, namespaces,
mounts, tracing, kernel/keyring and asynchronous-I/O control operations.
CPU is limited to 2 seconds, address space to 256 MiB, stack to 8 MiB,
descriptors to 32, and file size/process creation/core size to zero.
The parent enforces 3 seconds by default (maximum 15), at most 64 KiB total
stdout/stderr, and process-group TERM/KILL with bounded reaping. Namespace
teardown and the no-child-process policy are both required containment layers.

The parent verifier stays outside candidate authority and never imports it.
Candidate output remains untrusted data. A successful child exit is not a
passing acceptance test; independent parent assertions decide each check.
Tests must cover positive execution and concrete boundary failures before a
model candidate uses this profile. Binary/controller/bootstrap/request/source
hashes and bounded raw output are retained in each local receipt.

This profile does not authenticate model weights, qualify arbitrary Python
dependencies, prove scientific claims, repair other runner paths, or permit
persistent activation. Broader use and any changed profile need fresh review
and qualification. Existing full-suite, real-smoke and merge gates remain.

## Admission and whole-attempt supervision

The caller must freeze and independently approve all five exact runtime
identities (Bubblewrap, Python, libseccomp, controller, bootstrap), then pass
`approved_runtime`. Measurements from `runtime_identity()` are observations,
not approval. Missing approval or any drift produces a prelaunch failure.
The bootstrap loads the exact absolute libseccomp path that is measured.
This is not complete dependency attestation: libc, loader, Python standard
library and kernel remain trusted platform inputs. The controller is already
imported; its on-disk self-hash does not authenticate executing code.

The Linux caller must be single-threaded. After bounded argument validation,
the evidence directory is traversed with directory descriptors and NOFOLLOW.
Ancestors must be root/caller owned and not group/other writable, except a
root-owned sticky ancestor such as /tmp. The leaf must be caller-owned 0700.
The attempt directory and receipt replacement are anchored to retained fds.
No permissions are changed. Invalid arguments or failure to admit a writable
trusted sink raise before receipt admission; an unsafe path cannot be used to
promise a durable report. The caller controls ancestry and lifecycle throughout;
these static checks do not exclude malicious equal-UID races or authenticate a
checkout. Source copies and bind paths still rely on that obligation.

A durable initial receipt is written/fsynced before the trusted supervisor is
forked. That child starts its own session; Bubblewrap and Python remain in its
process group (no nested --new-session). Preflight hashes, input copies and
inner Popen run inside this supervised attempt. The parent starts its deadline
before fork, terminates at the deadline, and reserves at most 1.5 seconds for
TERM/KILL and reaping. The bootstrap also denies setsid/setpgid. Normal Bubblewrap
setup after exec is in this monitored interval. The receipt distinguishes
prelaunch refusal, launch/execution failure, timeout, incomplete teardown and
exit; a launched flag or returncode is never parent acceptance. Raw outputs are
fsynced before the terminal receipt. Failed terminal persistence raises and
leaves the earlier durable snapshot; it is not reported as successful delivery.

Initial fork, trusted-sink admission and receipt storage can themselves block
in the OS. An already-running external supervisor is needed for a strict
API-entry bound in that fault model. SIGKILL cannot promptly reap a process in
uninterruptible kernel sleep; such teardown is reported incomplete. A process
or storage crash may leave only the initial/intermediate receipt. The tool does
not promise completed evidence on failed storage or a universal real-time bound.

The profile additionally denies all SysV shared-memory/semaphore/message-queue
operations and unsupported memfd, eventfd, timerfd, inotify/fanotify, message-
queue and pidfd creation. Tiny synthetic refusal tests allocate no pressure.
This reduces specific unsupported allocation surfaces; RLIMIT_AS and IPC
namespaces still are not total kernel-memory controllers. The default-allow
filter is not a qualified general-purpose hostile Python sandbox.

The old check_research_progress caller has no approved-runtime argument and
therefore fails closed. A separately frozen external acceptance controller
must supply the reviewed profile for a new governed attempt; the old caller is
not silently treated as integrated or repaired. Public adoption, whole-source
review, full suite and real integrated smoke remain separate gates.

## Parent terminal evidence

After confirmed supervisor reap, the retained parent directory descriptor owns
an independent evidence pass. It verifies the candidate and request copies
against the exact caller bytes and the bootstrap copy against the approved
digest. Missing, changed or unreadable input cannot pass integrity. Unreaped
supervisors leave evidence unchecked and teardown incomplete.

The parent reads only bounded, regular canonical stdout.bin/stderr.bin files,
recomputes their hashes, and retains the combined output bound. Temporary
fragments are not published output. A published empty file is real empty output;
an absent file has no invented text, hash or path. Published bytes without a
complete child checkpoint, or from timeout/output truncation, are partial.
Complete bytes must also match the child checkpoint's recorded stream digest;
changed or missing checkpoint digests make that stream invalid, not complete.
The parent cannot recover an uncheckpointed return code or event interleaving.

parent_finalized records this parent observation, not successful execution or
durable delivery. terminal_evidence_complete requires independently verified
inputs and both complete published streams; it is still not semantic acceptance.
Timeout, failed admission and incomplete teardown retain their failure status.
An otherwise exited attempt with incomplete evidence becomes failed. The final
parent checkpoint must succeed before the API returns; a storage failure raises
and preserves the earlier durable snapshot without promising terminal delivery.
Reaping the supervisor alone does not independently prove every descendant gone;
existing profile/OS assumptions and storage-blocking limitations remain.
