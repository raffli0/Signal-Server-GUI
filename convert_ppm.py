from PIL import Image
import sys
import os

if len(sys.argv) < 3:
    print("Usage: python3 convert_ppm.py <input.ppm> <output.png>")
    sys.exit(1)

ppm_path = sys.argv[1]
png_path = sys.argv[2]

if os.path.exists(ppm_path):
    img = Image.open(ppm_path)
    img.save(png_path)
    print("Saved to", png_path)
else:
    print("PPM not found!")
