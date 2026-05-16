from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "mozok_game" / "data" / "art" / "island_ruins"
RNG = random.Random(54)


def ensure_dirs() -> None:
    for rel in [
        "scene",
        "tiles/grass",
        "tiles/cave",
        "tiles/camp",
        "tiles/ruins",
        "objects",
        "characters/alice",
        "characters/boris",
        "characters/mira",
    ]:
        (ART / rel).mkdir(parents=True, exist_ok=True)


def rgba(colour: tuple[int, int, int], alpha: int = 255) -> tuple[int, int, int, int]:
    return (*colour, alpha)


def gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    width, height = size
    img = Image.new("RGBA", size)
    px = img.load()
    for y in range(height):
        t = y / max(1, height - 1)
        colour = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        for x in range(width):
            px[x, y] = rgba(colour)
    return img


def add_noise(img: Image.Image, amount: int = 18) -> Image.Image:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    px = overlay.load()
    for y in range(img.height):
        for x in range(img.width):
            n = RNG.randint(-amount, amount)
            px[x, y] = (255, 255, 255, max(0, n)) if n > 0 else (0, 0, 0, min(255, -n))
    return Image.alpha_composite(img, overlay)


def vignette(img: Image.Image, strength: int = 155) -> Image.Image:
    width, height = img.size
    mask = Image.new("L", img.size, 0)
    px = mask.load()
    cx = width / 2
    cy = height / 2
    max_dist = math.sqrt(cx * cx + cy * cy)
    for y in range(height):
        for x in range(width):
            dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2) / max_dist
            px[x, y] = min(255, int(strength * (dist**1.7)))
    dark = Image.new("RGBA", img.size, (0, 0, 0, strength))
    dark.putalpha(mask)
    return Image.alpha_composite(img, dark)


def stone_texture(path: Path, base: tuple[int, int, int], moss: bool = True) -> None:
    img = gradient((512, 512), tuple(min(255, c + 18) for c in base), tuple(max(0, c - 28) for c in base))
    draw = ImageDraw.Draw(img)
    y = 0
    row_h = 58
    while y < 512:
        offset = 0 if (y // row_h) % 2 == 0 else -70
        x = offset
        while x < 512:
            w = RNG.randint(82, 150)
            rect = (x, y, x + w, y + row_h)
            shade = RNG.randint(-18, 20)
            colour = tuple(max(0, min(255, c + shade)) for c in base)
            draw.rectangle(rect, fill=rgba(colour, 255), outline=rgba((33, 36, 32), 160), width=2)
            for _ in range(RNG.randint(2, 5)):
                cx = RNG.randint(max(0, x), min(511, x + w))
                cy = RNG.randint(max(0, y), min(511, y + row_h))
                draw.line((cx, cy, cx + RNG.randint(-28, 28), cy + RNG.randint(-10, 18)), fill=rgba((28, 30, 27), 80), width=1)
            x += w
        y += row_h
    if moss:
        for _ in range(90):
            x = RNG.randint(0, 511)
            y = RNG.randint(250, 511)
            colour = RNG.choice([(45, 99, 50), (60, 121, 54), (28, 82, 45)])
            draw.ellipse((x - 18, y - 5, x + 18, y + 8), fill=rgba(colour, RNG.randint(45, 115)))
    img = add_noise(img, 24)
    img.save(path)


def floor_texture(path: Path, base: tuple[int, int, int]) -> None:
    img = gradient((512, 512), tuple(min(255, c + 18) for c in base), tuple(max(0, c - 34) for c in base))
    draw = ImageDraw.Draw(img)
    for y in range(0, 512, 64):
        draw.line((0, y, 512, y + RNG.randint(-10, 10)), fill=rgba((36, 34, 28), 150), width=3)
    for x in range(-60, 560, 104):
        draw.line((x, 0, x + RNG.randint(-20, 25), 512), fill=rgba((38, 35, 27), 120), width=2)
    for _ in range(120):
        x = RNG.randint(0, 511)
        y = RNG.randint(0, 511)
        colour = RNG.choice([(54, 111, 55), (38, 83, 45), (126, 114, 72), (70, 64, 44)])
        draw.ellipse((x - 5, y - 2, x + 12, y + 4), fill=rgba(colour, RNG.randint(45, 125)))
    img = add_noise(img, 18)
    img.save(path)


def backdrop(path: Path, mood: str = "grass") -> None:
    if mood == "cave":
        img = gradient((944, 436), (28, 34, 40), (49, 50, 48))
        wall = (68, 69, 72)
        moss = (29, 70, 47)
        glow = (88, 128, 135)
    elif mood == "camp":
        img = gradient((944, 436), (55, 48, 33), (87, 68, 39))
        wall = (98, 84, 58)
        moss = (58, 97, 44)
        glow = (219, 124, 54)
    else:
        img = gradient((944, 436), (41, 62, 58), (74, 91, 59))
        wall = (88, 93, 78)
        moss = (41, 107, 52)
        glow = (148, 184, 132)
    draw = ImageDraw.Draw(img)

    # distant chamber
    draw.rectangle((242, 74, 702, 238), fill=rgba(tuple(max(0, c - 17) for c in wall)))
    for x in range(260, 700, 62):
        draw.rectangle((x, 82, x + 30, 245), fill=rgba(tuple(max(0, c - 8) for c in wall)))
        draw.rectangle((x + 3, 82, x + 27, 245), outline=rgba((25, 25, 22), 115), width=2)

    # center doorway
    arch = (384, 63, 560, 242)
    draw.rounded_rectangle(arch, radius=26, fill=rgba((5, 14, 17), 245), outline=rgba((128, 115, 72), 180), width=4)
    draw.rectangle((402, 135, 542, 248), fill=rgba((3, 12, 15), 250))
    for i in range(4):
        draw.arc((366 - i * 8, 48 - i * 6, 578 + i * 8, 268 + i * 8), 180, 360, fill=rgba((98, 96, 79), 115), width=3)

    # ceiling and floor hints
    for i in range(7):
        y = 86 + i * 31
        draw.line((120, y, 824, y + RNG.randint(-5, 5)), fill=rgba((25, 30, 27), 70), width=2)
    for i in range(5):
        y = 252 + i * 36
        draw.line((176 - i * 45, y, 768 + i * 45, y + RNG.randint(-4, 4)), fill=rgba((147, 130, 78), 100), width=2)

    # side columns
    for x in (126, 184, 704, 762):
        draw.rectangle((x, 86, x + 46, 318), fill=rgba(tuple(max(0, c - 2) for c in wall)))
        draw.rectangle((x - 9, 110, x + 55, 134), fill=rgba(tuple(min(255, c + 22) for c in wall)))
        draw.rectangle((x - 14, 302, x + 60, 332), fill=rgba(tuple(min(255, c + 12) for c in wall)))
        draw.line((x + 8, 96, x + 12, 296), fill=rgba((31, 30, 25), 110), width=2)

    # moss and light
    for _ in range(110):
        x = RNG.randint(80, 860)
        y = RNG.randint(228, 380)
        draw.ellipse((x - 20, y - 4, x + 22, y + 8), fill=rgba(moss, RNG.randint(38, 115)))
    for x in (338, 606):
        draw.line((x, 34, x, 86), fill=rgba((82, 64, 34), 180), width=2)
        draw.ellipse((x - 14, 82, x + 14, 110), fill=rgba(glow, 185))
        draw.ellipse((x - 34, 68, x + 34, 126), fill=rgba(glow, 36))

    img = add_noise(img, 12)
    img = vignette(img, 85)
    img.save(path)


def transparent(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 0))


def object_food_crate(path: Path) -> None:
    img = transparent((512, 512))
    draw = ImageDraw.Draw(img)
    draw.ellipse((96, 404, 416, 466), fill=(0, 0, 0, 90))
    draw.polygon([(114, 186), (402, 156), (430, 342), (132, 374)], fill=rgba((141, 85, 43)), outline=rgba((55, 32, 18)), width=7)
    draw.polygon([(114, 186), (254, 106), (402, 156), (260, 226)], fill=rgba((175, 113, 54)), outline=rgba((61, 37, 21)), width=6)
    draw.polygon([(260, 226), (402, 156), (430, 342), (280, 396)], fill=rgba((113, 67, 37)), outline=rgba((55, 32, 18)), width=6)
    for x in (164, 250, 344):
        draw.line((x, 174, x + 18, 363), fill=rgba((67, 39, 22)), width=6)
    draw.rectangle((172, 238, 354, 289), fill=rgba((204, 181, 96)), outline=rgba((75, 55, 28)), width=4)
    draw.text((214, 252), "RATIONS", fill=rgba((42, 30, 18)))
    img.save(path)


def object_campfire(path: Path) -> None:
    img = transparent((512, 512))
    draw = ImageDraw.Draw(img)
    draw.ellipse((118, 398, 394, 462), fill=(0, 0, 0, 90))
    for angle in (20, -18, 0):
        draw.rounded_rectangle((160 + angle, 350, 356 + angle, 382), radius=13, fill=rgba((93, 54, 27)), outline=rgba((36, 20, 10)), width=4)
    for _ in range(18):
        x = RNG.randint(194, 314)
        y = RNG.randint(156, 330)
        draw.ellipse((x - 78, y - 88, x + 78, y + 110), fill=rgba((255, 128, 35), 18))
    draw.polygon([(254, 352), (180, 255), (228, 266), (218, 142), (285, 252), (326, 210), (304, 350)], fill=rgba((232, 62, 38)))
    draw.polygon([(258, 337), (215, 262), (247, 270), (251, 184), (291, 270), (309, 246), (296, 336)], fill=rgba((255, 169, 40)))
    draw.polygon([(260, 322), (242, 282), (258, 289), (266, 237), (285, 297), (276, 322)], fill=rgba((255, 235, 111)))
    img.save(path)


def object_spring(path: Path) -> None:
    img = transparent((512, 512))
    draw = ImageDraw.Draw(img)
    draw.ellipse((104, 390, 408, 462), fill=(0, 0, 0, 70))
    draw.ellipse((120, 274, 392, 408), fill=rgba((51, 92, 88)), outline=rgba((28, 38, 34)), width=7)
    draw.ellipse((148, 292, 364, 382), fill=rgba((61, 158, 190), 210), outline=rgba((154, 219, 223), 170), width=5)
    for i in range(5):
        y = 312 + i * 12
        draw.arc((156, y, 356, y + 46), 0, 180, fill=rgba((202, 242, 241), 145), width=3)
    for _ in range(38):
        x = RNG.randint(98, 414)
        y = RNG.randint(328, 424)
        draw.ellipse((x - 12, y - 5, x + 15, y + 8), fill=rgba((47, 119, 52), RNG.randint(70, 150)))
    img.save(path)


def object_cave(path: Path) -> None:
    img = transparent((512, 512))
    draw = ImageDraw.Draw(img)
    draw.ellipse((82, 402, 430, 468), fill=(0, 0, 0, 95))
    draw.polygon([(96, 408), (134, 228), (202, 118), (304, 104), (386, 220), (424, 408)], fill=rgba((54, 52, 60)), outline=rgba((28, 26, 31)), width=8)
    draw.rounded_rectangle((172, 184, 344, 412), radius=58, fill=rgba((4, 13, 16)), outline=rgba((103, 94, 112), 120), width=5)
    draw.arc((150, 150, 366, 420), 190, 350, fill=rgba((152, 135, 74), 120), width=4)
    for _ in range(50):
        x = RNG.randint(102, 418)
        y = RNG.randint(112, 404)
        draw.line((x, y, x + RNG.randint(-16, 20), y + RNG.randint(6, 26)), fill=rgba((28, 29, 32), 100), width=2)
    img.save(path)


def object_radio(path: Path) -> None:
    img = transparent((512, 512))
    draw = ImageDraw.Draw(img)
    draw.ellipse((126, 392, 386, 450), fill=(0, 0, 0, 80))
    draw.rounded_rectangle((144, 214, 376, 374), radius=24, fill=rgba((74, 91, 92)), outline=rgba((26, 31, 33)), width=7)
    draw.rectangle((176, 248, 286, 314), fill=rgba((31, 45, 50)), outline=rgba((155, 177, 164)), width=4)
    draw.ellipse((306, 252, 354, 300), fill=rgba((30, 31, 34)), outline=rgba((174, 177, 148)), width=5)
    draw.line((214, 214, 162, 126), fill=rgba((170, 160, 118)), width=5)
    draw.line((162, 126, 126, 101), fill=rgba((170, 160, 118)), width=3)
    for i in range(4):
        draw.arc((102 - i * 18, 114 - i * 18, 410 + i * 18, 410 + i * 18), 220, 286, fill=rgba((114, 202, 230), 55), width=3)
    img.save(path)


def object_shelter(path: Path) -> None:
    img = transparent((512, 512))
    draw = ImageDraw.Draw(img)
    draw.ellipse((94, 402, 418, 466), fill=(0, 0, 0, 75))
    draw.polygon([(106, 274), (256, 130), (416, 274)], fill=rgba((142, 116, 58)), outline=rgba((64, 48, 25)), width=7)
    for x in range(128, 390, 34):
        draw.line((256, 132, x, 274), fill=rgba((80, 61, 31)), width=4)
    draw.rectangle((146, 274, 374, 410), fill=rgba((90, 114, 67)), outline=rgba((43, 53, 31)), width=6)
    draw.rectangle((206, 304, 306, 410), fill=rgba((38, 47, 32)), outline=rgba((24, 28, 20)), width=4)
    img.save(path)


def draw_character(path: Path, palette: dict[str, tuple[int, int, int]], emotion: str) -> None:
    img = transparent((768, 1024))
    draw = ImageDraw.Draw(img)
    # shadow
    draw.ellipse((200, 910, 568, 982), fill=(0, 0, 0, 80))
    # legs and boots
    draw.rounded_rectangle((280, 648, 344, 916), radius=28, fill=rgba(palette["pants"]), outline=rgba((28, 24, 24)), width=5)
    draw.rounded_rectangle((424, 648, 488, 916), radius=28, fill=rgba(palette["pants"]), outline=rgba((28, 24, 24)), width=5)
    draw.rounded_rectangle((236, 886, 354, 956), radius=24, fill=rgba(palette["dark"]), outline=rgba((20, 17, 16)), width=5)
    draw.rounded_rectangle((414, 886, 536, 956), radius=24, fill=rgba(palette["dark"]), outline=rgba((20, 17, 16)), width=5)
    # coat/body
    draw.polygon([(244, 342), (524, 342), (584, 692), (468, 748), (384, 704), (300, 748), (184, 692)], fill=rgba(palette["coat"]), outline=rgba((32, 27, 26)), width=7)
    draw.polygon([(308, 356), (460, 356), (492, 662), (384, 716), (276, 662)], fill=rgba(palette["shirt"]), outline=rgba((35, 30, 30)), width=4)
    # arms
    draw.rounded_rectangle((170, 392, 252, 684), radius=32, fill=rgba(palette["coat"]), outline=rgba((31, 26, 24)), width=5)
    draw.rounded_rectangle((516, 392, 598, 684), radius=32, fill=rgba(palette["coat"]), outline=rgba((31, 26, 24)), width=5)
    draw.ellipse((156, 650, 250, 736), fill=rgba(palette["skin"]), outline=rgba((92, 61, 48)), width=4)
    draw.ellipse((518, 650, 612, 736), fill=rgba(palette["skin"]), outline=rgba((92, 61, 48)), width=4)
    # neck/head
    draw.rounded_rectangle((338, 274, 430, 372), radius=30, fill=rgba(palette["skin"]), outline=rgba((92, 61, 48)), width=4)
    draw.ellipse((270, 120, 498, 338), fill=rgba(palette["skin"]), outline=rgba((72, 48, 40)), width=6)
    # hair
    hair = palette["hair"]
    draw.pieslice((240, 70, 526, 306), 180, 360, fill=rgba(hair), outline=rgba((34, 25, 23)), width=5)
    for i in range(9):
        x = 262 + i * 30
        draw.polygon([(x, 172), (x + 60, 146 + (i % 3) * 10), (x + 24, 290 + RNG.randint(-18, 18))], fill=rgba(hair), outline=rgba((37, 27, 24)))
    draw.polygon([(260, 190), (208, 346), (304, 300)], fill=rgba(hair), outline=rgba((37, 27, 24)), width=4)
    draw.polygon([(498, 190), (560, 346), (462, 300)], fill=rgba(hair), outline=rgba((37, 27, 24)), width=4)
    # eyes and mouth
    eye = palette["eye"]
    if emotion == "afraid":
        draw.ellipse((318, 220, 352, 252), fill=rgba((245, 245, 235)), outline=rgba((20, 20, 20)), width=3)
        draw.ellipse((416, 220, 450, 252), fill=rgba((245, 245, 235)), outline=rgba((20, 20, 20)), width=3)
        draw.ellipse((330, 229, 344, 247), fill=rgba(eye))
        draw.ellipse((428, 229, 442, 247), fill=rgba(eye))
        draw.arc((346, 270, 424, 314), 200, 340, fill=rgba((70, 35, 35)), width=5)
    elif emotion == "angry":
        draw.line((306, 218, 356, 238), fill=rgba((24, 20, 18)), width=6)
        draw.line((414, 238, 464, 218), fill=rgba((24, 20, 18)), width=6)
        draw.ellipse((326, 238, 350, 260), fill=rgba(eye))
        draw.ellipse((420, 238, 444, 260), fill=rgba(eye))
        draw.line((342, 292, 430, 282), fill=rgba((64, 34, 32)), width=5)
    elif emotion == "happy":
        draw.arc((310, 226, 356, 264), 200, 340, fill=rgba((20, 20, 20)), width=5)
        draw.arc((412, 226, 458, 264), 200, 340, fill=rgba((20, 20, 20)), width=5)
        draw.arc((342, 258, 430, 326), 20, 160, fill=rgba((76, 38, 36)), width=5)
    else:
        draw.ellipse((318, 226, 354, 258), fill=rgba((245, 245, 235)), outline=rgba((20, 20, 20)), width=3)
        draw.ellipse((414, 226, 450, 258), fill=rgba((245, 245, 235)), outline=rgba((20, 20, 20)), width=3)
        draw.ellipse((331, 235, 346, 253), fill=rgba(eye))
        draw.ellipse((427, 235, 442, 253), fill=rgba(eye))
        if emotion == "curious":
            draw.arc((344, 264, 430, 310), 10, 150, fill=rgba((70, 35, 35)), width=4)
        elif emotion == "suspicious":
            draw.line((340, 286, 428, 286), fill=rgba((64, 34, 32)), width=5)
            draw.line((306, 214, 356, 222), fill=rgba((24, 20, 18)), width=5)
        else:
            draw.arc((346, 270, 424, 306), 20, 160, fill=rgba((70, 35, 35)), width=4)
    # accessories
    draw.rectangle((330, 390, 438, 416), fill=rgba(palette["accent"]), outline=rgba((26, 22, 18)), width=3)
    draw.line((384, 420, 384, 690), fill=rgba((32, 28, 26)), width=5)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=90, threshold=3))
    img.save(path)


def generate_characters() -> None:
    palettes = {
        "alice": {
            "hair": (191, 72, 64),
            "eye": (80, 154, 188),
            "skin": (235, 183, 141),
            "coat": (94, 65, 120),
            "shirt": (214, 204, 168),
            "pants": (48, 56, 82),
            "dark": (39, 30, 46),
            "accent": (195, 154, 70),
        },
        "boris": {
            "hair": (214, 216, 201),
            "eye": (92, 175, 124),
            "skin": (221, 171, 130),
            "coat": (62, 102, 78),
            "shirt": (193, 184, 148),
            "pants": (50, 62, 54),
            "dark": (30, 38, 32),
            "accent": (151, 176, 102),
        },
        "mira": {
            "hair": (188, 194, 226),
            "eye": (92, 128, 220),
            "skin": (232, 186, 150),
            "coat": (87, 108, 172),
            "shirt": (224, 219, 188),
            "pants": (56, 66, 110),
            "dark": (32, 35, 62),
            "accent": (118, 200, 183),
        },
    }
    emotions = ["neutral", "curious", "suspicious", "afraid", "angry", "happy", "tired"]
    for agent, palette in palettes.items():
        for emotion in emotions:
            draw_character(ART / "characters" / agent / f"{emotion}.png", palette, emotion)


def paste_fit(canvas: Image.Image, image: Image.Image, box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    width = x1 - x0
    height = y1 - y0
    scale = min(width / image.width, height / image.height)
    size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
    resized = image.resize(size, Image.Resampling.LANCZOS)
    canvas.alpha_composite(resized, (x0 + width // 2 - size[0] // 2, y1 - size[1]))


def generate_preview() -> None:
    canvas = Image.new("RGBA", (1280, 720), (8, 7, 5, 255))
    draw = ImageDraw.Draw(canvas)
    view = (168, 8, 1112, 444)
    backdrop_img = Image.open(ART / "scene" / "backdrop.png").convert("RGBA").resize((944, 436), Image.Resampling.LANCZOS)
    canvas.alpha_composite(backdrop_img, (168, 8))

    floor = Image.open(ART / "scene" / "floor.png").convert("RGBA").resize((820, 128), Image.Resampling.LANCZOS)
    floor.putalpha(150)
    canvas.alpha_composite(floor, (230, 308))

    paste_fit(canvas, Image.open(ART / "objects" / "food_crate.png").convert("RGBA"), (615, 282, 760, 392))
    paste_fit(canvas, Image.open(ART / "objects" / "campfire.png").convert("RGBA"), (486, 280, 604, 398))
    paste_fit(canvas, Image.open(ART / "characters" / "alice" / "curious.png").convert("RGBA"), (770, 156, 938, 410))
    paste_fit(canvas, Image.open(ART / "characters" / "mira" / "afraid.png").convert("RGBA"), (354, 176, 500, 410))

    for rect, title in [((8, 8, 158, 436), "Front"), ((1122, 8, 1272, 436), "Back"), ((168, 452, 1112, 712), "Dialogue / Mozok Brain")]:
        draw.rounded_rectangle(rect, radius=6, fill=(34, 24, 14), outline=(221, 176, 67), width=4)
        draw.rectangle((rect[0] + 12, rect[1] + 8, rect[0] + 135, rect[1] + 30), fill=(239, 227, 174), outline=(117, 76, 25), width=2)
        draw.text((rect[0] + 24, rect[1] + 12), title, fill=(41, 31, 24))

    draw.rectangle((188, 486, 1092, 692), fill=(49, 91, 70), outline=(221, 176, 67), width=2)
    draw.text((204, 516), "Group Chat", fill=(239, 227, 174))
    draw.text((204, 548), "You: What do you think about the cave?", fill=(244, 238, 214))
    draw.text((204, 576), "Alice: It keeps answering us in clicks.", fill=(174, 220, 238))
    draw.text((622, 516), "Cognitive Field", fill=(239, 227, 174))
    draw.text((622, 548), "Alice / cave signal resonance", fill=(244, 238, 214))
    draw.text((884, 516), "Memory Flash", fill=(239, 227, 174))
    draw.text((884, 548), "The cave clicked after sunset.", fill=(244, 238, 214))

    # subtle frame
    draw.rectangle(view, outline=(117, 76, 25), width=4)
    canvas.save(ART / "preview.png")


def main() -> None:
    ensure_dirs()
    stone_texture(ART / "scene" / "wall.png", (67, 72, 61), moss=True)
    floor_texture(ART / "scene" / "floor.png", (96, 85, 58))
    backdrop(ART / "scene" / "backdrop.png", "grass")

    for mood, base in {
        "grass": (62, 86, 57),
        "ruins": (87, 86, 81),
        "camp": (93, 70, 42),
        "cave": (47, 48, 54),
    }.items():
        stone_texture(ART / "tiles" / mood / "wall.png", base, moss=mood != "cave")
        floor_texture(ART / "tiles" / mood / "floor.png", base)
        backdrop(ART / "tiles" / mood / "backdrop.png", mood)

    object_food_crate(ART / "objects" / "food_crate.png")
    object_campfire(ART / "objects" / "campfire.png")
    object_spring(ART / "objects" / "water_source.png")
    object_cave(ART / "objects" / "cave_entrance.png")
    object_radio(ART / "objects" / "broken_radio.png")
    object_shelter(ART / "objects" / "shelter.png")
    generate_characters()
    generate_preview()
    print(f"Generated island ruins art pack in {ART}")


if __name__ == "__main__":
    main()
