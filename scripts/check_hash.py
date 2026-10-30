"""Print the SHA3-256 of a file; fail if an expected hash is given and differs.

Usage: python check_hash.py <file> [expected-sha3-256-hex]
"""

import hashlib
import sys

path = sys.argv[1]
expected = sys.argv[2].strip().lower() if len(sys.argv) > 2 else ""
with open(path, "rb") as f:
    got = hashlib.sha3_256(f.read()).hexdigest()
print(f"sha3-256 {got}  {path}")
if expected and got != expected:
    print(f"MISMATCH: expected {expected}", file=sys.stderr)
    sys.exit(1)
