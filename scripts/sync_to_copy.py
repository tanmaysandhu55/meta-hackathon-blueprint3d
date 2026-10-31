import shutil
import os

src_base = r"C:\Users\tanma\Downloads\Meta-Ai-hackthon\FloorPlan3D-project"
dst_base = r"C:\Users\tanma\Downloads\FloorPlan3D - Copy"

files_to_copy = [
    r"templates\index.html",
    r"static\css\styles.css",
    r"static\css\custom.css",
    r"static\css\editor.css",
    r"static\js\landing.js",
    r"static\js\viewer.js",
    r"static\js\app.js",
    r"static\js\editor.js",
    r"static\hero.png",
    r"samples\index.json",
]

dirs_to_copy = [
    r"static\data",
]

for rel in files_to_copy:
    src = os.path.join(src_base, rel)
    dst = os.path.join(dst_base, rel)
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        print(f"Copied file: {rel}")
    else:
        print(f"Source file not found: {src}")

for rel in dirs_to_copy:
    src = os.path.join(src_base, rel)
    dst = os.path.join(dst_base, rel)
    if os.path.exists(src):
        os.makedirs(dst, exist_ok=True)
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dst, item)
            if os.path.isfile(s):
                shutil.copy2(s, d)
        print(f"Copied dir: {rel}")

print("Sync completed successfully.")
