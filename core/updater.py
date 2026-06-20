"""FAIL-CLOSED auto-update check (optional; off by default).

Security stance: until a REAL Ed25519 public key is baked in below, this NEVER applies an update —
it always returns "run the bundled engine". An update is only ever applied if a detached signature
over the manifest verifies against the embedded public key. No key / bad signature / any error =>
fall back to the bundled app. This makes it impossible to ship the boss a tampered or half-published
update: the CI also writes the manifest ONLY after the boot self-test passes, so a manifest can never
point ahead of a verified artifact.

To enable later: (1) generate an Ed25519 keypair, keep the private key in CI secrets only;
(2) paste the public key bytes into PUBLIC_KEY_HEX; (3) have CI sign the manifest after Gate 4 and
publish manifest + signature next to the installer.
"""
PUBLIC_KEY_HEX = ""   # empty == updates disabled (fail-closed). Paste 64 hex chars to enable.


def check_for_update(manifest_bytes=b"", signature_bytes=b""):
    """Return a verified update descriptor, or None to run the bundled engine. Fail-closed."""
    if not PUBLIC_KEY_HEX:
        return None                      # no key embedded -> never update
    try:
        from nacl.signing import VerifyKey   # PyNaCl, only needed if updates are enabled
        VerifyKey(bytes.fromhex(PUBLIC_KEY_HEX)).verify(manifest_bytes, signature_bytes)
    except Exception:
        return None                      # any verification failure -> run bundled engine
    import json
    try:
        return json.loads(manifest_bytes.decode())
    except Exception:
        return None
