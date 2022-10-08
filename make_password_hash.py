import sys
import hashlib


def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

pw_clear = sys.argv[1].strip()
print(make_hashes(pw_clear))


