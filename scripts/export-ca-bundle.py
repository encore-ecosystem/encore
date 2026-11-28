#!/usr/bin/env python3
"""Record the native builder's default trust roots for relocatable SDKs."""
import ssl
import sys
from pathlib import Path

certificates = ssl.create_default_context().get_ca_certs(binary_form=True)
if certificates:
    contents = "".join(ssl.DER_cert_to_PEM_cert(cert) for cert in certificates)
else:
    candidates = [Path("/opt/homebrew/etc/ca-certificates/cert.pem"), Path("/usr/local/etc/ca-certificates/cert.pem")]
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise SystemExit("No default CA certificates available for SDK packaging")
    contents = source.read_text()
Path(sys.argv[1]).write_text(contents)
