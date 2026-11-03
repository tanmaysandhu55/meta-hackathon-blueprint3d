import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()
from meta_media_service import generate_floorplan

print("Calling generate_floorplan('a 2-story house')...")
img_bytes = generate_floorplan("a 2-story house")
with open("samples/test_2story_muse_draft.png", "wb") as f:
    f.write(img_bytes)
print("Saved samples/test_2story_muse_draft.png")
