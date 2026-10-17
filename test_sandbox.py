"""Run: python test_sandbox.py  -- prints 'all sandbox tests passed' if the sandbox holds."""
import os
import tempfile

os.environ["WORKSPACE_ROOT"] = tempfile.mkdtemp()  # throwaway root for testing

from sandbox import WORKSPACE_ROOT, SandboxError, safe_path  # noqa: E402


def blocked(p: str) -> bool:
    try:
        safe_path(p)
    except SandboxError:
        return True
    return False


# Legit paths must work
for ok in ["notes.txt", "a/b/c.txt", ".", "a/../b.txt"]:
    assert not blocked(ok), f"should allow: {ok}"

# Escapes must be rejected
for bad in ["../x", "a/../../x", "..", "/etc/passwd", "", "bad\x00name"]:
    assert blocked(bad), f"should block: {bad!r}"

# Sibling folder sharing the same name prefix
evil = WORKSPACE_ROOT.parent / (WORKSPACE_ROOT.name + "-evil")
assert blocked(f"../{evil.name}/x"), "prefix trick got through"

# Symlink pointing outside the workspace
outside = tempfile.mkdtemp()
try:
    (WORKSPACE_ROOT / "link").symlink_to(outside, target_is_directory=True)
    assert blocked("link/secret.txt"), "symlink escape got through"
except OSError:
    print("skipped symlink test (not permitted on this system)")

print("all sandbox tests passed")
