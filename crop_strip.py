from PIL import Image

img = Image.open("/home/dedsec/.gemini/antigravity-ide/brain/a399921a-b791-4c6b-ab79-bfcd825ad180/scratch/coverage_tworay_fixed.png")
w, h = img.size
# Crop a diagonal-like slice or horizontal slice
crop_box = (int(w*0.3), int(h*0.48), int(w*0.7), int(h*0.54))
cropped = img.crop(crop_box)
cropped.save("/home/dedsec/.gemini/antigravity-ide/brain/a399921a-b791-4c6b-ab79-bfcd825ad180/scratch/coverage_strip.png")
print("Saved strip")
