"""把 character-body-no-fish.png 切成可以各自動畫的圖層（只需在素材改變時執行一次）。

需要 Pillow 與 numpy（不在遊戲的 requirements 內）：
    python scripts/build_monk_layers.py [--preview 輸出資料夾]

所有圖層都保持 755x670 的原畫布大小，CSS 直接疊在同一位置即可。
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parents[1] / "app" / "static" / "assets"
SOURCE = ASSETS / "character-body-no-fish.png"
FISH = ASSETS / "original-wooden-fish.png"

# 大和尚的前臂、手與木槌。袖口的輪廓線留在身體上；下緣貼著前臂輪廓，讓袖子下方的兩條衣褶留在身體上
ARM_POLYGON = [
    (196, 70), (305, 70), (318, 128), (360, 185), (398, 212), (409, 240), (409, 309),
    (405, 308), (392, 298), (375, 284), (360, 272), (343, 265), (322, 250), (300, 220), (262, 172), (196, 172),
]
# 原圖大和尚的白袍內部是透明的，靠網頁背景看起來是白色；填上同樣的顏色，袖子才能蓋住後面的前臂
PAGE_BACKGROUND = (248, 244, 239, 255)
# 小和尚（不含頭上的木魚，木魚另有圖層）
SMALL_MONK_POLYGON = [(40, 236), (335, 236), (338, 640), (40, 640)]
# 小和尚頭頂左邊的黃色敲擊線
MARKS_BOX = (30, 95, 200, 236)

# CSS 使用的旋轉支點與敲擊角度，也用在預覽圖。支點在袖口上緣，揮下時前臂的切口會轉進袖子裡
ARM_PIVOT = (408, 248)
STRIKE_DEGREES = -14
SMALL_MONK_ORIGIN = (180, 600)


def polygon_mask(size, points):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return np.array(mask) > 0


def box_mask(size, box):
    mask = np.zeros((size[1], size[0]), dtype=bool)
    left, top, right, bottom = box
    mask[top:bottom, left:right] = True
    return mask


def fill_enclosed(image: Image.Image) -> Image.Image:
    """Fills transparent areas that are fully surrounded by outlines (the robe) with the page background."""
    alpha = np.array(image)[:, :, 3]
    # copy(): an image made by fromarray shares the read-only array, and floodfill would silently do nothing
    region = Image.fromarray(np.where(alpha < 128, 255, 0).astype(np.uint8)).copy()
    ImageDraw.floodfill(region, (0, 0), 128)
    enclosed = np.array(region) == 255
    data = np.array(image)
    data[enclosed] = PAGE_BACKGROUND
    return Image.fromarray(data)


def build_layers() -> dict[str, Image.Image]:
    source = Image.open(SOURCE).convert("RGBA")
    pixels = np.array(source)
    arm = polygon_mask(source.size, ARM_POLYGON)
    marks = box_mask(source.size, MARKS_BOX) & ~arm
    small = polygon_mask(source.size, SMALL_MONK_POLYGON) & ~arm & ~marks
    big = ~(arm | marks | small)

    def layer(mask):
        data = pixels.copy()
        data[~mask] = 0  # clear the colour too, otherwise invisible pixels keep each file at ~600 KB
        return Image.fromarray(data)

    return {
        "monk-big.png": fill_enclosed(layer(big)),
        "monk-arm.png": layer(arm),
        "monk-small.png": layer(small),
        "impact-marks.png": layer(marks),
    }


def preview(layers: dict[str, Image.Image], folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    fish = Image.open(FISH).convert("RGBA")
    size = fish.size
    for name, degrees, squash in (("rest", 0, 1.0), ("strike", STRIKE_DEGREES, 0.96)):
        frame = Image.new("RGBA", size, PAGE_BACKGROUND)
        # 前臂在大和尚後面，讓袖子蓋住切口。PIL 的正角度是逆時針，CSS rotate() 的正角度是順時針
        frame.alpha_composite(layers["monk-arm.png"].rotate(-degrees, center=ARM_PIVOT, resample=Image.BICUBIC))
        frame.alpha_composite(layers["monk-big.png"])
        small = Image.new("RGBA", size, (0, 0, 0, 0))
        small.alpha_composite(layers["monk-small.png"])
        small.alpha_composite(fish)
        if squash != 1.0:
            ox, oy = SMALL_MONK_ORIGIN
            scaled = small.resize((size[0], round(size[1] * squash)))
            small = Image.new("RGBA", size, (0, 0, 0, 0))
            small.alpha_composite(scaled, (0, round(oy - oy * squash)))
        frame.alpha_composite(small)
        frame.alpha_composite(layers["impact-marks.png"])
        frame.convert("RGB").save(folder / f"{name}.png")


def main() -> None:
    parser = argparse.ArgumentParser(description="切出和尚動畫圖層")
    parser.add_argument("--preview", type=Path, help="輸出靜止與敲擊瞬間的預覽圖到這個資料夾")
    parser.add_argument("--dry-run", action="store_true", help="只輸出預覽，不寫入 app/static/assets")
    args = parser.parse_args()
    layers = build_layers()
    if not args.dry_run:
        for name, image in layers.items():
            image.save(ASSETS / name, optimize=True)
    if args.preview:
        preview(layers, args.preview)


if __name__ == "__main__":
    main()
