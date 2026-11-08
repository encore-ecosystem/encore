"""Describe source-byte differences without modifying the release archives."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile

for archive in sorted(Path("dist").glob("encore-*")):
    if not (archive.name.endswith(".tar.gz") or archive.name.endswith(".zip")):
        continue
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as stream:
            files = {name: stream.read(name) for name in stream.namelist() if not name.endswith("/")}
    else:
        with tarfile.open(archive, "r:gz") as stream:
            files = {item.name: stream.extractfile(item).read() for item in stream.getmembers() if item.isfile()}
    manifest_name = next(name for name in files if name.endswith("/SDK.json"))
    prefix = manifest_name[:-len("SDK.json")]
    manifest = json.loads(files[manifest_name])
    print("ARCHIVE", archive.name, flush=True)
    for package in manifest["packages"]:
        folder = Path(package["path"]).name
        raw = subprocess.check_output(["git", "-C", package["path"], "archive", "--format=tar", package["commit"]])
        with tarfile.open(fileobj=io.BytesIO(raw)) as stream:
            expected = {item.name: stream.extractfile(item).read() for item in stream.getmembers() if item.isfile()}
        package_prefix = prefix + "lib/encore/index/" + folder + "/"
        actual = {name[len(package_prefix):]: data for name, data in files.items() if name.startswith(package_prefix)}
        differences = sorted(name for name in actual.keys() & expected.keys() if actual[name] != expected[name])
        if actual != expected:
            print("PACKAGE", folder, "EXTRA", sorted(actual.keys() - expected.keys()), "MISSING", sorted(expected.keys() - actual.keys()), flush=True)
            for name in differences:
                print("DIFFERENT", name, "actual", len(actual[name]), hashlib.sha256(actual[name]).hexdigest(),
                      "expected", len(expected[name]), hashlib.sha256(expected[name]).hexdigest(), flush=True)
                if len(actual[name]) < 2000 and len(expected[name]) < 2000:
                    print("ACTUAL", repr(actual[name]), "EXPECTED", repr(expected[name]), flush=True)
        else:
            print("MATCH", folder, len(actual), flush=True)
