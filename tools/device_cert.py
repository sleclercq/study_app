"""
device_cert.py - One client certificate per device allowed to open https://e.lairning.com.

A WAF rule of the lairning.com zone blocks every request that does not present a
client certificate issued by the zone. Each device (iPhone, Mac, PC) gets its own
certificate, so that a lost one is revoked without touching the others.

    python3 tools/device_cert.py csr iphone-1
        private key + certificate request in _certs/
    Cloudflare: SSL/TLS > Client Certificates > Create Certificate >
        "Use my private key and CSR", paste _certs/iphone-1.csr, longest validity,
        then save the certificate shown as _certs/iphone-1.pem
    python3 tools/device_cert.py profile iphone-1
        asks a password, writes _certs/iphone-1.p12 and .mobileconfig,
        then DELETES the unencrypted key

The private key never leaves this Mac (Cloudflare only sees the request) and _certs/
is gitignored. Once the profile is built the key only exists inside the .p12, which
the password protects: that password is typed on the device at installation and is
written nowhere, so a copied file is useless without it. Pick a long one: the .p12
can be attacked offline. A forgotten password means a new certificate, nothing more.

Installing:
  iPhone   AirDrop the .mobileconfig, then Réglages > Général > VPN et gestion de
           l'appareil, Installer, type the password. iOS gives no way to export it.
  Mac      security import _certs/NAME.p12 -k ~/Library/Keychains/login.keychain-db -x
           in the child's session (-x: key not extractable; a double-click import
           would let anyone export it from Keychain Access). Safari, Chrome, Edge.
  Windows  double-click the .p12, "Current user", leave "Mark this key as
           exportable" unticked. Chrome, Edge.

The .p12 is encrypted with 3DES/SHA1 on purpose: OpenSSL 3's default (AES-256,
PBKDF2) is refused by some iOS versions as a "wrong password", 3DES is read everywhere.
"""

import getpass
import os
import plistlib
import re
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CERTS = ROOT / "_certs"
HOST = "e.lairning.com"


def openssl(*args, env=None):
    return subprocess.run(["openssl", *args], check=True, capture_output=True, text=True,
                          env=env).stdout


def csr(name):
    key, req = CERTS / f"{name}.key", CERTS / f"{name}.csr"
    if key.exists() or (CERTS / f"{name}.p12").exists():
        sys.exit(f"{name} existe déjà dans _certs/ : choisis un autre nom.")
    CERTS.mkdir(exist_ok=True)
    os.chmod(CERTS, 0o700)
    openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
            "-out", str(req), "-subj", f"/CN={name}/O=lairning")
    os.chmod(key, 0o600)
    print(req.read_text(), end="")
    print(f"\nÀ coller dans Cloudflare : {req.relative_to(ROOT)}")
    print(f"Puis enregistrer le certificat obtenu dans _certs/{name}.pem")


def profile(name):
    key, pem = CERTS / f"{name}.key", CERTS / f"{name}.pem"
    p12, mobileconfig = CERTS / f"{name}.p12", CERTS / f"{name}.mobileconfig"
    for f in (key, pem):
        if not f.exists():
            sys.exit(f"Il manque {f.relative_to(ROOT)}.")
    if openssl("x509", "-in", str(pem), "-noout", "-pubkey") != \
            openssl("pkey", "-in", str(key), "-pubout"):
        sys.exit(f"{pem.name} ne correspond pas à la clé {key.name} : mauvais certificat collé ?")
    print(openssl("x509", "-in", str(pem), "-noout", "-subject", "-issuer", "-enddate"), end="")
    aki = openssl("x509", "-in", str(pem), "-noout", "-ext", "authorityKeyIdentifier")
    issuer_ski = re.sub(r"[^0-9A-F]", "", aki.split("\n", 1)[1].upper().replace("KEYID", ""))
    print(f"Clé de l'émetteur (cf.tls_client_auth.cert_issuer_ski) : {issuer_ski}")

    password = getpass.getpass("Mot de passe du certificat : ")
    if len(password) < 8 or getpass.getpass("Encore une fois : ") != password:
        sys.exit("Mot de passe trop court (8 caractères au moins) ou différent : rien n'est écrit.")
    openssl("pkcs12", "-export", "-inkey", str(key), "-in", str(pem), "-out", str(p12),
            "-name", f"revisions-{name}", "-keypbe", "PBE-SHA1-3DES",
            "-certpbe", "PBE-SHA1-3DES", "-macalg", "sha1", "-passout", "env:P12_PASSWORD",
            env={**os.environ, "P12_PASSWORD": password})
    os.chmod(p12, 0o600)

    # No "Password" key in the payload: iOS asks for it at installation.
    with open(mobileconfig, "wb") as f:
        plistlib.dump({
            "PayloadType": "Configuration",
            "PayloadVersion": 1,
            "PayloadIdentifier": f"com.lairning.e.{name}",
            "PayloadUUID": str(uuid.uuid4()).upper(),
            "PayloadDisplayName": f"Révisions ({name})",
            "PayloadDescription": f"Autorise cet appareil à ouvrir https://{HOST}",
            "PayloadOrganization": "lairning",
            "PayloadContent": [{
                "PayloadType": "com.apple.security.pkcs12",
                "PayloadVersion": 1,
                "PayloadIdentifier": f"com.lairning.e.{name}.identity",
                "PayloadUUID": str(uuid.uuid4()).upper(),
                "PayloadDisplayName": f"Certificat {name}",
                "PayloadCertificateFileName": f"{name}.p12",
                "PayloadContent": p12.read_bytes(),
            }],
        }, f)
    os.chmod(mobileconfig, 0o600)
    key.unlink()
    print(f"Écrits : _certs/{p12.name} (ordinateurs) et _certs/{mobileconfig.name} (iPhone).")
    print(f"Clé non chiffrée supprimée : {key.name}.")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("csr", "profile") \
            or not re.fullmatch(r"[a-z0-9-]+", sys.argv[2]):
        sys.exit("Usage : python3 tools/device_cert.py csr|profile NOM  (NOM en a-z, 0-9, -)")
    {"csr": csr, "profile": profile}[sys.argv[1]](sys.argv[2])
