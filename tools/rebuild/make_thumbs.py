"""把 1678 张页面截图压成缩略图，落到 DATA_DIR/previews/<slug>/<page>.png。"""
import pathlib
import sys

from PIL import Image

SRC = pathlib.Path(r"D:\_rebuild_sites")
OUT = pathlib.Path(r"D:\_previews")
WIDTH = 480
QUALITY = 82


def main() -> int:
    made = 0
    skipped = 0
    sites = 0
    for site in sorted(p for p in SRC.iterdir() if p.is_dir()):
        shots = site / "shots"
        if not shots.is_dir():
            continue
        target_dir = OUT / site.name
        target_dir.mkdir(parents=True, exist_ok=True)
        for shot in shots.glob("*-ours.png"):
            stem = shot.name[: -len("-ours.png")]
            dst = target_dir / f"{stem}.png"
            if dst.exists() and dst.stat().st_mtime >= shot.stat().st_mtime:
                skipped += 1
                continue
            try:
                with Image.open(shot) as img:
                    img = img.convert("RGB")
                    ratio = WIDTH / img.width
                    resized = img.resize((WIDTH, max(1, int(img.height * ratio))), Image.LANCZOS)
                    resized.save(dst, "PNG", optimize=True)
                made += 1
            except Exception as exc:
                print("失败", shot, exc)
        sites += 1
    total_bytes = sum(p.stat().st_size for p in OUT.rglob("*.png"))
    print(f"站点 {sites}，新生成 {made}，跳过 {skipped}，总体积 {total_bytes/1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
