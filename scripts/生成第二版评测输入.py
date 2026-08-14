"""生成第二版可复现视觉评测输入和任务集。"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = PROJECT_ROOT / "benchmarks/任务集/输入"
SOURCE_SUITE = PROJECT_ROOT / "benchmarks/任务集/第一版任务集.json"
TARGET_SUITE = PROJECT_ROOT / "benchmarks/任务集/第二版任务集.json"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
) -> None:
    left, top, right, bottom = box
    text_box = draw.textbbox((0, 0), text, font=font)
    width = text_box[2] - text_box[0]
    height = text_box[3] - text_box[1]
    draw.text(
        (left + (right - left - width) / 2, top + (bottom - top - height) / 2),
        text,
        font=font,
        fill=fill,
    )


def _ui_screenshot() -> Image.Image:
    image = Image.new("RGB", (960, 540), "#f5f7fb")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 960, 68), fill="#172554")
    draw.text((38, 19), "EvoShop", font=_font(28), fill="white")
    draw.text((742, 24), "Products    Help", font=_font(17), fill="#dbeafe")

    draw.rounded_rectangle((245, 92, 715, 500), radius=22, fill="white", outline="#dbe2ea", width=2)
    draw.text((292, 125), "Welcome back", font=_font(34), fill="#172554")
    draw.text((292, 175), "Sign in to continue", font=_font(18), fill="#64748b")
    draw.text((292, 224), "Email", font=_font(16), fill="#334155")
    draw.rounded_rectangle((292, 250, 668, 298), radius=8, fill="#f8fafc", outline="#94a3b8")
    draw.text((310, 265), "member@example.com", font=_font(15), fill="#64748b")
    draw.text((292, 320), "Password", font=_font(16), fill="#334155")
    draw.rounded_rectangle((292, 346, 668, 394), radius=8, fill="#f8fafc", outline="#94a3b8")
    draw.text((310, 360), "************", font=_font(17), fill="#64748b")
    draw.rounded_rectangle((292, 414, 668, 462), radius=9, fill="#2563eb")
    _centered_text(draw, (292, 414, 668, 462), "Sign in", font=_font(18), fill="white")

    draw.rounded_rectangle(
        (80, 205, 222, 363), radius=18, fill="#fffbeb", outline="#f59e0b", width=3
    )
    draw.ellipse((127, 225, 175, 273), fill="#f59e0b")
    _centered_text(draw, (127, 225, 175, 273), "%", font=_font(22), fill="white")
    _centered_text(
        draw,
        (94, 286, 208, 336),
        "Exclusive\ndiscount",
        font=_font(18),
        fill="#92400e",
    )
    draw.line((222, 284, 270, 284), fill="#f59e0b", width=4)
    draw.polygon(((270, 284), (257, 276), (257, 292)), fill="#f59e0b")
    draw.rounded_rectangle(
        (735, 204, 920, 360), radius=16, fill="#eff6ff", outline="#60a5fa", width=2
    )
    draw.text((756, 224), "UI requirement", font=_font(18), fill="#1e3a8a")
    draw.multiline_text(
        (756, 264),
        "Show a login hint\nfor member-only\ndiscounts.",
        font=_font(16),
        fill="#1e40af",
        spacing=8,
    )
    return image


def _architecture_diagram() -> Image.Image:
    image = Image.new("RGB", (1200, 700), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.text((54, 40), "Discount calculation architecture", font=_font(34), fill="#0f172a")
    draw.text(
        (55, 92),
        "Pricing returns a discount; service computes the final total.",
        font=_font(19),
        fill="#475569",
    )

    draw.rounded_rectangle(
        (70, 190, 485, 525), radius=24, fill="#eff6ff", outline="#2563eb", width=4
    )
    draw.rounded_rectangle(
        (715, 190, 1130, 525), radius=24, fill="#f0fdf4", outline="#16a34a", width=4
    )
    draw.rectangle((70, 190, 485, 260), fill="#2563eb")
    draw.rectangle((715, 190, 1130, 260), fill="#16a34a")
    _centered_text(draw, (70, 190, 485, 260), "service.py", font=_font(27), fill="white")
    _centered_text(draw, (715, 190, 1130, 260), "pricing.py", font=_font(27), fill="white")

    draw.text((110, 305), "final_total(total, customer_type)", font=_font(19), fill="#1e3a8a")
    draw.rounded_rectangle(
        (112, 360, 442, 450), radius=12, fill="white", outline="#93c5fd", width=2
    )
    _centered_text(draw, (112, 360, 442, 450), "total - discount", font=_font(23), fill="#1e3a8a")

    draw.text((755, 305), "discount_amount(total, customer_type)", font=_font(18), fill="#14532d")
    draw.rounded_rectangle(
        (760, 360, 1085, 450), radius=12, fill="white", outline="#86efac", width=2
    )
    _centered_text(draw, (760, 360, 1085, 450), "return discount", font=_font(23), fill="#14532d")

    draw.line((486, 405, 713, 405), fill="#7c3aed", width=7)
    draw.polygon(((713, 405), (686, 389), (686, 421)), fill="#7c3aed")
    draw.text((530, 355), "calls", font=_font(19), fill="#6d28d9")
    draw.line((713, 475, 486, 475), fill="#f97316", width=7)
    draw.polygon(((486, 475), (513, 459), (513, 491)), fill="#f97316")
    draw.text((535, 493), "discount value", font=_font(19), fill="#c2410c")
    draw.rounded_rectangle(
        (245, 585, 955, 652), radius=14, fill="#fff7ed", outline="#fb923c", width=2
    )
    _centered_text(
        draw,
        (245, 585, 955, 652),
        "Boundary: pricing never returns the final price",
        font=_font(22),
        fill="#9a3412",
    )
    return image


def _unrelated_image() -> Image.Image:
    image = Image.new("RGB", (720, 480), "#ecfeff")
    draw = ImageDraw.Draw(image)
    draw.ellipse((65, 85, 295, 315), fill="#67e8f9")
    draw.ellipse((238, 145, 468, 375), fill="#c4b5fd")
    draw.ellipse((414, 75, 644, 305), fill="#fda4af")
    draw.rounded_rectangle((145, 350, 575, 430), radius=18, fill="#0f172a")
    _centered_text(
        draw, (145, 350, 575, 430), "TEAM OFFSITE - FRIDAY 18:00", font=_font(22), fill="white"
    )
    return image


def _encode_png(image: Image.Image) -> tuple[bytes, str]:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    data = buffer.getvalue()
    return data, base64.b64encode(data).decode("ascii") + "\n"


def main() -> None:
    generators: dict[str, tuple[str, Callable[[], Image.Image]]] = {
        "bench-09-image-ui": ("界面截图-第二版.png.b64", _ui_screenshot),
        "bench-10-image-architecture": ("架构图-第二版.png.b64", _architecture_diagram),
        "bench-11-image-negative": ("无关图片-第二版.png.b64", _unrelated_image),
    }
    digests: dict[str, str] = {}
    for benchmark_id, (filename, generator) in generators.items():
        data, encoded = _encode_png(generator())
        (INPUT_ROOT / filename).write_text(encoded, encoding="ascii", newline="\n")
        digests[benchmark_id] = hashlib.sha256(data).hexdigest()

    suite = json.loads(SOURCE_SUITE.read_text(encoding="utf-8"))
    suite["suite_id"] = "evoweave_v2"
    suite["version"] = 4
    for task in suite["tasks"]:
        benchmark_id = task["benchmark_id"]
        if benchmark_id not in generators:
            continue
        filename, _generator = generators[benchmark_id]
        artifact = task["input_artifacts"][0]
        artifact["source"] = f"benchmarks/任务集/输入/{filename}"
        artifact["sha256"] = digests[benchmark_id]

    TARGET_SUITE.write_text(
        json.dumps(suite, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for benchmark_id, (filename, _generator) in generators.items():
        print(f"{benchmark_id}: {filename} {digests[benchmark_id]}")


if __name__ == "__main__":
    main()
