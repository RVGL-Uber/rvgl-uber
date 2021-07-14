from pathlib import Path
import sys
import subprocess
import multiprocessing
from typing import Dict, Match
from fnmatch import fnmatch
import re

srgb_profile = Path("srgb.icm")
overrides = Path("overrides")

upscaled_suffix = "-upscaled"
quality_levels = [(512, "hd"), (1024, "uhd")]


def panic_usage():
    print("Usage:", "build.py pre PACKS_DIR PACKS_SUFFIX", "build.py post PACKS_DIR", end="\n")
    raise Exception("Invalid usage")


def decode_clean(b: bytes):
    return "" if not b else b.decode("utf-8").strip()


def run_process(
    *cmd: str,
):
    try:
        result = subprocess.run(cmd, check=True, capture_output=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raise (
            Exception(
                {
                    "stdout": decode_clean(e.stdout),
                    "stderr": decode_clean(e.stderr),
                }
            )
        ) from e
    return result


def identify_dimensions(src: Path):
    result = decode_clean(
        run_process(
            "magick",
            "identify",
            str(src),
        ).stdout
    )
    matches = re.search(" \\d+x\\d+ ", result)
    if isinstance(matches, Match):
        return (int(x) for x in matches[0].split("x"))
    else:
        raise Exception("Unable to get image size")


def convert_pre(src: Path, dst: Path):
    w, h = identify_dimensions(src)
    max_quality = max(q[0] for q in quality_levels)
    if w >= max_quality and h >= max_quality:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    # change transparency mode from black color to alpha channel
    # so upscaling-generated black pixels don't get interpreted as transparent
    run_process(
        "magick",
        "convert",
        str(src),
        "-transparent",
        "black",
        "png:" + str(dst.with_suffix(".bmp")),
    )


def convert_post(upscaled_file: Path, dest_assets_dir: Path):
    def restore_name(x: Path):
        return x.with_stem(x.stem.removesuffix(upscaled_suffix)).with_suffix(".bmp")

    original_file = restore_name(upscaled_file)
    w_original, h_original = identify_dimensions(original_file)

    for level in quality_levels:
        quality_file = Path(f"{dest_assets_dir.name}-{level[1]}").joinpath(original_file.relative_to(dest_assets_dir))
        quality_file.parent.mkdir(parents=True, exist_ok=True)
        if w_original >= level[0] and h_original >= level[0]:
            # use original asset if it's high enough quality
            run_process(
                "magick",
                "convert",
                str(original_file),
                "-strip",
                "-resize",
                f"{level[0]}x{level[0]}>",
                "png:" + str(quality_file),
            )
        else:
            run_process(
                "magick",
                "convert",
                str(upscaled_file),
                # some upscaling tools output in a different color space, which the game can't read
                "-colorspace",
                "sRGB",
                "-profile",
                str(srgb_profile),
                "-strip",
                "-resize",
                # some upscaled images will exceed the max quality, so downscale them
                # aspect ration will be preserved
                f"{level[0]}x{level[0]}>",
                # png will still work despite the incorrect extension
                "png:" + str(quality_file),
            )


def pre(orig_assets_dir: Path, override_assets_dir: Path, dest_assets_dir: Path):
    files: Dict[Path, None] = {}
    for f in orig_assets_dir.glob("**/*.bm*"):
        files[f] = None
    # 1024, 512, 256, 128
    suffixes = [".bmn", ".bmo", ".bmp", ".bmq"]
    for f in list(files.keys()):
        try:
            # remove all lower quality textures from the dictionary
            for suffix in suffixes[min(suffixes.index(f.suffix) + 1, len(suffixes)) :]:
                files.pop(f.with_suffix(suffix), None)
        except ValueError:
            pass
        # remove macOS history files which are not valid images
        if f.name.startswith("._"):
            files.pop(f)

    # some assets are weird (corrupted?) and crash ImageMagick
    # they have been manually fixed and added as overrides
    for f in override_assets_dir.glob("**/*"):
        if f.is_file():
            files.pop(orig_assets_dir.joinpath(f.relative_to(override_assets_dir)))
            convert_pre(f, dest_assets_dir.joinpath(f.relative_to(override_assets_dir)))

    with multiprocessing.Pool() as pool:
        pool.starmap(
            convert_pre,
            [(f, dest_assets_dir.joinpath(f.relative_to(orig_assets_dir))) for f in files],
        )


def post(dest_assets_dir: Path):
    with multiprocessing.Pool() as pool:
        pool.starmap(
            convert_post,
            [(f, dest_assets_dir) for f in dest_assets_dir.glob(f"**/*{upscaled_suffix}.*")],
        )


if __name__ == "__main__":
    if not srgb_profile.exists():
        raise Exception("sRGB profile does not exist: " + str(srgb_profile))
    if not overrides.exists():
        raise Exception("overrides do not exist: " + str(overrides))
    if len(sys.argv) < 3:
        panic_usage()

    command = sys.argv[1]
    packs_dir = Path(sys.argv[2])

    if command == "pre":
        if len(sys.argv) != 4:
            panic_usage()
        packs_suffix = sys.argv[3]
        pack_whitelist = ["game_files", "io_*", "rvgl_*"]
        for orig_assets_dir in packs_dir.glob("*"):
            if not orig_assets_dir.is_dir() or not any(
                fnmatch(orig_assets_dir.name, pattern) for pattern in pack_whitelist
            ):
                continue

            override_assets_dir = overrides.joinpath(orig_assets_dir.name)
            dest_assets_dir = Path("uber-" + orig_assets_dir.name + packs_suffix)

            pre(orig_assets_dir, override_assets_dir, dest_assets_dir)
    elif command == "post":
        for dest_assets_dir in packs_dir.glob("*"):
            post(dest_assets_dir)
    else:
        panic_usage()
