"""Repackage Windows SDK text using exact pinned Git bytes; preserve native binaries."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile

records = []
for archive in sorted(Path("dist").glob("encore-*.zip")):
    original_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    expected_hash = Path(str(archive) + ".sha256").read_text().split()[0].lower()
    if original_hash != expected_hash:
        raise SystemExit(f"Original artifact checksum mismatch: {archive}")
    with zipfile.ZipFile(archive) as stream:
        entries = stream.infolist()
        files = {item.filename: stream.read(item) for item in entries}
    manifest_name = next(name for name in files if name.endswith("/SDK.json"))
    prefix = manifest_name[:-len("SDK.json")]
    manifest = json.loads(files[manifest_name])
    target = archive.name[len("encore-"):-len(".zip")]
    provenance = json.loads(Path(f"dist/provenance-{target}.json").read_text())
    for binary, key in [("encore.exe", "compiler_sha256"), ("encore-lsp.exe", "lsp_sha256")]:
        if hashlib.sha256(files[prefix + "bin/" + binary]).hexdigest() != provenance[key]:
            raise SystemExit(f"Original binary hash mismatch: {binary}")
    replacements = {}
    for package in manifest["packages"]:
        raw = subprocess.check_output(["git", "-C", package["path"], "-c", "core.autocrlf=false",
                                       "-c", "core.eol=lf", "archive", "--format=tar", package["commit"]])
        with tarfile.open(fileobj=io.BytesIO(raw)) as stream:
            expected = {item.name: stream.extractfile(item).read() for item in stream.getmembers() if item.isfile()}
        package_prefix = prefix + "lib/encore/index/" + Path(package["path"]).name + "/"
        actual = {name[len(package_prefix):]: data for name, data in files.items()
                  if name.startswith(package_prefix) and not name.endswith("/")}
        if actual.keys() != expected.keys():
            raise SystemExit(f"SDK file set differs: {package['path']}")
        for name, data in expected.items():
            if actual[name] != data:
                if b"\0" in actual[name] or b"\0" in data or actual[name].replace(b"\r\n", b"\n") != data:
                    raise SystemExit(f"SDK contains a difference beyond CRLF: {package['path']}/{name}")
                replacements[package_prefix + name] = data
    temporary = archive.with_suffix(".canonical.zip")
    with zipfile.ZipFile(temporary, "w") as stream:
        for item in entries:
            stream.writestr(item, replacements.get(item.filename, files[item.filename]))
    # Every member outside the listed SDK text replacements must remain byte-identical.
    with zipfile.ZipFile(temporary) as stream:
        if stream.namelist() != [item.filename for item in entries]:
            raise SystemExit("Archive member order or names changed")
        for item in entries:
            if stream.read(item.filename) != replacements.get(item.filename, files[item.filename]):
                raise SystemExit(f"Unexpected repackaging change: {item.filename}")
    temporary.replace(archive)
    canonical_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    Path(str(archive) + ".sha256").write_text(f"{canonical_hash}  {archive.name}\n")
    record = {"archive": archive.name, "original_sha256": original_hash, "canonical_sha256": canonical_hash,
              "sdk_text_files_canonicalized": len(replacements), "compiler_sha256": provenance["compiler_sha256"],
              "lsp_sha256": provenance["lsp_sha256"], "native_binaries_unchanged": True}
    records.append(record)
    print(json.dumps(record), flush=True)
Path("dist/repackaging.json").write_text(json.dumps({"schema": 1,
    "reason": "Windows Git archive applied core.autocrlf. SDK text restored to exact pinned Git bytes; native binaries unchanged.",
    "archives": records}, indent=2) + "\n")
