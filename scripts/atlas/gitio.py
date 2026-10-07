"""Thin wrappers around the git CLI.

Facts are always read from git objects (never the working tree) so that base and head
of a branch are analysed the same way, and nothing needs to be checked out.
"""

import os
import subprocess


class GitError(RuntimeError):
    pass


def git(repo, *args, check=True, stdin=None):
    try:
        proc = subprocess.run(
            ["git", "-C", repo, *args],
            input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        raise GitError("git is not installed or not on PATH")
    if check and proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip()
        raise GitError("git %s failed: %s" % (" ".join(args), msg))
    return proc.stdout


def repo_root(path):
    return git(path, "rev-parse", "--show-toplevel").strip()


def resolve(repo, ref):
    return git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}").strip()


def try_resolve(repo, ref):
    try:
        return resolve(repo, ref) or None
    except GitError:
        return None


def current_branch(repo):
    out = git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    return None if out == "HEAD" else out


def default_base(repo, preferred=None):
    """The ref a branch is compared against: preferred, origin's HEAD, then main/master."""
    candidates = []
    if preferred:
        candidates += ["origin/" + preferred, preferred] if "/" not in preferred else [preferred]
    head = git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False).strip()
    if head.startswith("refs/remotes/"):
        candidates.append(head[len("refs/remotes/"):])
    candidates += ["origin/main", "origin/master", "main", "master"]
    for ref in candidates:
        if try_resolve(repo, ref):
            return ref
    raise GitError("could not find a base branch (tried %s); pass --base" % ", ".join(candidates))


def merge_base(repo, a, b):
    return git(repo, "merge-base", a, b).strip()


def short(sha):
    return sha[:7] if sha else sha


def common_dir(repo):
    """The shared .git directory (the same for every worktree of the repo)."""
    path = git(repo, "rev-parse", "--git-common-dir").strip()
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(repo, path))


def worktrees(repo):
    out = git(repo, "worktree", "list", "--porcelain", check=False)
    paths = [line[len("worktree "):] for line in out.splitlines() if line.startswith("worktree ")]
    return paths or [repo]


def commit_date(repo, rev):
    return git(repo, "show", "-s", "--format=%cI", rev).strip()


def remote_url(repo):
    return git(repo, "config", "--get", "remote.origin.url", check=False).strip() or None


class TreeReader:
    """Lists and reads the blobs of one commit through a single `git cat-file --batch`."""

    def __init__(self, repo, rev):
        self.repo = repo
        self.rev = resolve(repo, rev)
        if not self.rev:
            raise GitError("unknown revision: %s" % rev)
        self._proc = None

    def entries(self):
        """[(path, blob_sha, size)] for regular files; symlinks and submodules are skipped."""
        out = git(self.repo, "ls-tree", "-r", "-z", "-l", "--full-tree", self.rev)
        result = []
        for rec in out.split("\0"):
            if not rec:
                continue
            meta, path = rec.split("\t", 1)
            mode, otype, sha, size = meta.split()
            if otype != "blob" or mode == "120000":
                continue
            result.append((path, sha, int(size) if size.isdigit() else 0))
        return result

    def read(self, path):
        """Bytes of `path` at this revision, or None if it does not exist."""
        if self._proc is None:
            self._proc = subprocess.Popen(
                ["git", "-C", self.repo, "cat-file", "--batch"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            )
        self._proc.stdin.write(("%s:%s\n" % (self.rev, path)).encode("utf-8"))
        self._proc.stdin.flush()
        header = self._proc.stdout.readline().decode("utf-8", "replace").split()
        if len(header) < 3 or header[1] != "blob":
            return None
        size = int(header[2])
        data = self._proc.stdout.read(size)
        self._proc.stdout.read(1)  # trailing newline
        return data

    def close(self):
        if self._proc is not None:
            self._proc.stdin.close()
            self._proc.stdout.close()
            self._proc.wait()
            self._proc = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def decode(data):
    """Text for analysis, or None for binary content."""
    if data is None or b"\0" in data[:8000]:
        return None
    return data.decode("utf-8", "replace")
