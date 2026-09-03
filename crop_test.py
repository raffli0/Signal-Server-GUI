from PIL import Image

img = Image.open("/home/dedsec/.gemini/antigravity-ide/brain/a399921a-b791-4c6b-ab79-bfcd825ad180/scratch/coverage_tworay_fixed.png")
w, h = img.size
# Crop center region (around Tx)
crop_box = (int(w*0.35), int(h*0.35), int(w*0.65), int(h*0.65))
cropped = img.crop(crop_box)
cropped.save("/home/dedsec/.gemini/antigravity-ide/brain/a399921a-b791-4c6b-ab79-bfcd825ad180/scratch/coverage_tworay_cropped.png")
print("Cropped size:", cropped.size)
