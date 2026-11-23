"""Draw the app icon (assets/lectura.ico): an indigo tile with a slide and a capture dot."""

from pathlib import Path

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, S - 8, S - 8), radius=56, fill=(79, 70, 229, 255))
# slide
d.rounded_rectangle((44, 66, 212, 170), radius=12, fill=(255, 255, 255, 255))
d.rectangle((62, 86, 150, 98), fill=(79, 70, 229, 255))
d.rectangle((62, 112, 190, 120), fill=(190, 188, 240, 255))
d.rectangle((62, 132, 172, 140), fill=(190, 188, 240, 255))
# stand
d.rectangle((122, 170, 134, 196), fill=(255, 255, 255, 255))
d.rounded_rectangle((92, 192, 164, 204), radius=6, fill=(255, 255, 255, 255))
# capture dot
d.ellipse((176, 44, 222, 90), fill=(229, 72, 77, 255), outline=(255, 255, 255, 255), width=6)

out = Path(__file__).resolve().parents[1] / "assets" / "lectura.ico"
out.parent.mkdir(exist_ok=True)
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(out.with_suffix(".png"))
print("wrote", out)

# dropdown chevron for the combo boxes (drawn at 4x, scaled down for smooth edges)
chev = Image.new("RGBA", (48, 32), (0, 0, 0, 0))
ImageDraw.Draw(chev).line([(8, 8), (24, 24), (40, 8)], fill=(107, 112, 133, 255), width=6)
chev.resize((12, 8), Image.LANCZOS).save(out.parent / "chevron.png")
print("wrote", out.parent / "chevron.png")
