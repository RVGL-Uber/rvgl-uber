import multiprocessing
from pathlib import Path
import shutil
import hashlib
import json
import sys
from typing import Any, Dict
from fnmatch import fnmatch

info_path = Path("info.json")


def make_zip(src_file: Path):
    print("Packing " + src_file.name)
    shutil.make_archive(src_file.name, "zip", str(src_file))


def apply_zip(src_zip: Path):
    sha = hashlib.sha256()
    with open(src_zip, "rb") as src_file:
        chunk = src_file.read(256 * 1024)
        while chunk:
            sha.update(chunk)
            chunk = src_file.read(256 * 1024)
    return (src_zip, sha.hexdigest())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: package.py VERSION_NAME")
        raise Exception("Invalid usage")

    if not info_path.exists():
        raise Exception("info.json does not exist: " + str(info_path))

    # only semantic version supported, e.g. 1.0.0
    raw_version = sys.argv[1]
    major, minor, patch = (int(i) for i in raw_version.split("."))
    if minor > 99:
        raise Exception("Minor version exceeds 99, a major version bump is required")
    if patch > 99:
        raise Exception("Patch version exceeds 99, a minor version bump is required")
    # The launcher enforces a float version format like 99.9999, so replicate it from semantic version:
    # major = M, minor = m, patch = p: MM.mmpp
    float_version = major + minor / 100 + patch / 10000

    with open("info.json") as f:
        info = json.load(f)

    with multiprocessing.Pool() as pool:
        manager = multiprocessing.Manager()
        manifest: Dict[Any, Any] = {
            "name": "Re-Volt Uber Packs",
            "version": float_version,
            "packages": {},
        }
        pool.map(make_zip, tuple(filter(lambda x: x.is_dir(), Path("src").iterdir())))
        for src_zip, sha in pool.map(apply_zip, Path(".").glob("*.zip")):
            manifest["packages"][src_zip.stem] = {
                "description": next(f["description"] for f in info if fnmatch(src_zip.stem, f["name"])),
                "version": float_version,
                "checksum": sha,
                "url": f"https://github.com/RVGL-Uber/rvgl-uber/releases/download/v{raw_version}/{src_zip.name}",
            }

    with open("manifest.json", "w") as f:
        f.write(json.dumps(manifest, sort_keys=True, indent=4))
