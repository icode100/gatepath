"""Generate GatePath PWA icons from the canonical Route G geometry."""

from pathlib import Path
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
ICONS = PUBLIC / "icons"

PRIMARY = "#151515"
ROUTE = "#FAFAFA"
WAYPOINT = "#D96A42"
MONOCHROME = "#000000"


def rounded_line(draw: ImageDraw.ImageDraw, points, width: int, fill: str) -> None:
    draw.line(points, fill=fill, width=width, joint="curve")
    radius = width // 2
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)


def render_icon(size: int, maskable: bool = False) -> Image.Image:
    scale = 4
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), PRIMARY)
    draw = ImageDraw.Draw(image)

    # Keep the complete mark inside the maskable safe zone while letting the
    # standard icon occupy more of its rounded tile.
    inset = 0.20 if maskable else 0.13
    left = canvas * inset
    top = canvas * inset
    right = canvas * (1 - inset)
    bottom = canvas * (1 - inset)
    width = max(8, round(canvas * 0.09))

    # The open loop and horizontal terminal form a route-shaped G.
    box = (left, top, right, bottom)
    draw.arc(box, start=45, end=325, fill=ROUTE, width=width)
    center_y = canvas * 0.54
    rounded_line(
        draw,
        [(canvas * 0.51, center_y), (canvas * (0.76 if maskable else 0.80), center_y)],
        width,
        ROUTE,
    )
    waypoint_radius = canvas * (0.047 if maskable else 0.055)
    waypoint_x = canvas * (0.76 if maskable else 0.80)
    draw.ellipse(
        (
            waypoint_x - waypoint_radius,
            center_y - waypoint_radius,
            waypoint_x + waypoint_radius,
            center_y + waypoint_radius,
        ),
        fill=WAYPOINT,
    )
    return image.resize((size, size), Image.Resampling.LANCZOS)


def render_monochrome_icon(size: int) -> Image.Image:
    """Render an alpha-only launcher glyph for supporting themed-icon hosts."""

    scale = 4
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    inset = 0.20
    width = max(8, round(canvas * 0.09))
    box = (
        canvas * inset,
        canvas * inset,
        canvas * (1 - inset),
        canvas * (1 - inset),
    )
    # Keep the route and its inward terminal as one continuous G-shaped mark.
    # The small opening in the upper-right is reserved for the waypoint, which
    # mirrors the detached-dot treatment used by Android themed icons.
    draw.arc(box, start=8, end=325, fill=MONOCHROME, width=width)
    center_y = canvas * 0.54
    rounded_line(
        draw,
        [(canvas * 0.51, center_y), (canvas * 0.79, center_y)],
        width,
        MONOCHROME,
    )
    # The themed layer must stay one colour because Android/launchers supply
    # its tint. A real transparent gap keeps the waypoint legible at launcher
    # sizes without relying on a background-coloured halo.
    waypoint_radius = canvas * 0.05
    waypoint_x = canvas * 0.77
    waypoint_y = canvas * 0.43
    draw.ellipse(
        (
            waypoint_x - waypoint_radius,
            waypoint_y - waypoint_radius,
            waypoint_x + waypoint_radius,
            waypoint_y + waypoint_radius,
        ),
        fill=MONOCHROME,
    )
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    outputs = [
        (ICONS / "icon-192.png", 192, False),
        (ICONS / "icon-512.png", 512, False),
        (ICONS / "icon-maskable-512.png", 512, True),
        (PUBLIC / "apple-touch-icon.png", 180, False),
    ]
    for path, size, maskable in outputs:
        render_icon(size, maskable).save(path, format="PNG", optimize=True)
        print(f"generated {path.relative_to(ROOT)} ({size}x{size})")
    monochrome_path = ICONS / "icon-monochrome-512.png"
    render_monochrome_icon(512).save(
        monochrome_path,
        format="PNG",
        optimize=True,
    )
    print(f"generated {monochrome_path.relative_to(ROOT)} (512x512)")


if __name__ == "__main__":
    main()
