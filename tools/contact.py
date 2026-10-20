"""Contact sheet of out/shot_*.bmp: python tools/contact.py [out.png] [cols] [first] [last]"""
import glob, os, sys
from PIL import Image, ImageDraw
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'out', 'contact.png')
cols = int(sys.argv[2]) if len(sys.argv) > 2 else 4
shots = sorted(glob.glob(os.path.join(ROOT, 'out', 'shot_*.bmp')))
if len(sys.argv) > 4:
    shots = shots[int(sys.argv[3]):int(sys.argv[4])]
w, h = 400, 300
rows = (len(shots) + cols - 1) // cols
sheet = Image.new('RGB', (cols * w, max(1, rows) * h))
d = ImageDraw.Draw(sheet)
for i, p in enumerate(shots):
    im = Image.open(p).convert('RGB').resize((w, h))
    sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    d.text(((i % cols) * w + 4, (i // cols) * h + 4), os.path.basename(p), fill=(255, 255, 0))
sheet.save(out)
print(len(shots), 'shots ->', out)
