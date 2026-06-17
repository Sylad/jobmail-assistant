#!/usr/bin/env python3
"""Génère scripts/desktop/windows/JobMail.ico — icône simple (enveloppe indigo)."""
import sys
from PIL import Image, ImageDraw

def main(out: str) -> None:
    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, S - 8, S - 8], radius=48, fill=(79, 70, 229, 255))
    d.rounded_rectangle([56, 84, S - 56, S - 84], radius=16, fill=(255, 255, 255, 255))
    d.line([56, 92, S // 2, 150], fill=(79, 70, 229, 255), width=10)
    d.line([S - 56, 92, S // 2, 150], fill=(79, 70, 229, 255), width=10)
    img.save(out, format="ICO",
             sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {out}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "JobMail.ico")
