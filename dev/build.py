from pathlib import Path
import sys
import subprocess
import multiprocessing
from typing import Dict
import os

command: str
upscaled_suffix: str
orig_assets_dir: Path
srgb_profile = Path("srgb.icm")


def panic_usage():
    print("Usage: build.py pre|post UPSCALED_IMAGE_SUFFIX PATH_TO_GAME_ASSETS")
    raise Exception("Invalid usage")


def decode_clean(b: bytes):
    return "" if not b else b.decode("utf-8").strip()


def run_process(
    *cmd: str,
):
    try:
        result = subprocess.run(cmd, check=True)
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


def convert_pre(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    # change transparency mode from black color to alpha channel
    # so AI-generated black pixels don't get interpreted as transparent
    run_process(
        "magick",
        "convert",
        str(src),
        "-transparent",
        "black",
        "png:" + str(dst.with_suffix(".bmp")),
    )


def convert_post(uhd_src: Path, hd_src: Path, upscaled_suffix: str):
    def fix(x: Path):
        return x.with_stem(x.stem.removesuffix(upscaled_suffix)).with_suffix(".bmp")

    fixed_uhd_src = fix(uhd_src)
    os.remove(fixed_uhd_src)
    uhd_src = uhd_src.rename(fixed_uhd_src)
    hd_src = fix(hd_src)
    # some AI programs output in a different color space, which the game can't read
    # some source images are higher quality than the expected 256x256, which produces larger dimensions than 1024x1024
    # png will still work despite the incorrect extension
    run_process(
        "magick",
        "convert",
        str(uhd_src),
        "-colorspace",
        "sRGB",
        "-profile",
        str(srgb_profile),
        "-strip",
        "-resize",
        "1024x1024",
        "png:" + str(uhd_src),
    )

    hd_src.parent.mkdir(parents=True, exist_ok=True)
    run_process("magick", "convert", str(uhd_src), "-strip", "-resize", "512x512", "png:" + str(hd_src))


def pre(uhd_assets_dir: Path):
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

    with multiprocessing.Pool() as pool:
        pool.starmap(
            convert_pre,
            [(f, uhd_assets_dir.joinpath(f.relative_to(orig_assets_dir))) for f in files],
        )


def post(uhd_assets_dir: Path, hd_assets_dir: Path, upscaled_suffix: str):
    with multiprocessing.Pool() as pool:
        pool.starmap(
            convert_post,
            [
                (f, hd_assets_dir.joinpath(f.relative_to(uhd_assets_dir)), upscaled_suffix)
                for f in uhd_assets_dir.glob(f"**/*{upscaled_suffix}.*")
            ],
        )


if __name__ == "__main__":
    if not srgb_profile.exists():
        raise Exception("SRGB Profile does not exist: " + str(srgb_profile))
    if len(sys.argv) != 4:
        panic_usage()

    command = sys.argv[1]
    upscaled_suffix = sys.argv[2]
    orig_assets_dir = Path(sys.argv[3])
    uhd_assets_dir = orig_assets_dir.with_name(orig_assets_dir.name + "-uhd")
    hd_assets_dir = orig_assets_dir.with_name(orig_assets_dir.name + "-hd")

    if command == "pre":
        pre(uhd_assets_dir)
    elif command == "post":
        post(uhd_assets_dir, hd_assets_dir, upscaled_suffix)
    else:
        panic_usage()
