#!/usr/bin/env python3
"""
Generate static/hero.png - a clean transparent isometric cut-out render
of the FloorPlan3D architectural building, following the editorial studio style.
"""

import math
import os
from PIL import Image, ImageDraw, ImageFilter

def create_hero_png():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_path = os.path.join(repo_root, "static", "hero.png")

    width, height = 880, 640
    # Canvas with full transparency
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    
    # Create a separate layer for drop shadow
    shadow_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_img)

    # Isometric projection parameters
    # Origin in center-lower area
    ox, oy = 440, 360
    scale = 32.0  # pixels per meter

    def to_iso(x, y, z=0.0):
        # Isometric rotation (30 degrees)
        # Plan coordinates: X right, Y down/forward
        # Center the plan around (8.0, 6.0)
        px = (x - 8.0) * scale
        py = (y - 6.0) * scale
        pz = z * scale

        iso_x = ox + (px - py) * math.cos(math.radians(30))
        iso_y = oy + (px + py) * math.sin(math.radians(30)) - pz
        return (iso_x, iso_y)

    # Palette
    ink = (26, 25, 23, 255)            # #1A1917
    ink_shadow = (26, 25, 23, 50)       # Drop shadow
    wall_top = (231, 227, 218, 255)     # #E7E3DA
    wall_left = (180, 175, 165, 255)    # Shaded left face
    wall_right = (205, 200, 190, 255)   # Shaded right face
    floor_slab = (245, 243, 238, 255)   # Very light warm bone
    pigment = (155, 52, 24, 255)        # #9B3418
    grid_line = (26, 25, 23, 30)

    # 1. Footprint polygon for shadow
    footprint = [
        to_iso(1.0, 1.0, 0),
        to_iso(15.0, 1.0, 0),
        to_iso(15.0, 11.0, 0),
        to_iso(1.0, 11.0, 0)
    ]
    # Draw soft drop shadow on shadow layer
    shadow_offset_y = 18
    shadow_poly = [(pt[0] + 6, pt[1] + shadow_offset_y) for pt in footprint]
    shadow_draw.polygon(shadow_poly, fill=(20, 20, 20, 90))
    # Blur shadow
    shadow_blurred = shadow_img.filter(ImageFilter.GaussianBlur(radius=20))
    img.paste(shadow_blurred, (0, 0), shadow_blurred)

    draw = ImageDraw.Draw(img)

    # 2. Base ground grid under the building
    for x in range(0, 17, 2):
        p1 = to_iso(x, 0.0, 0)
        p2 = to_iso(x, 12.0, 0)
        draw.line([p1, p2], fill=grid_line, width=1)
    for y in range(0, 13, 2):
        p1 = to_iso(0.0, y, 0)
        p2 = to_iso(16.0, y, 0)
        draw.line([p1, p2], fill=grid_line, width=1)

    # 3. Floor slab
    draw.polygon(footprint, fill=floor_slab, outline=ink, width=1)

    # Room dividing floor patterns (hairline room borders)
    rooms = [
        # (id, x1, y1, x2, y2, label)
        ("r1", 1.2, 1.2, 7.3, 5.9, "101"),
        ("r2", 7.5, 1.2, 14.8, 5.9, "LAB"),
        ("r3", 1.2, 6.1, 14.8, 7.1, "CORRIDOR"),
        ("r4", 1.2, 7.3, 5.3, 10.8, "REST"),
        ("r5", 5.5, 7.3, 10.0, 10.8, "OFFICE"),
        ("r6", 10.2, 7.3, 12.4, 10.8, "LOBBY"),
        ("r7", 12.6, 7.3, 14.8, 10.8, "STAIRS"),
    ]

    for rid, x1, y1, x2, y2, lbl in rooms:
        poly = [to_iso(x1, y1, 0), to_iso(x2, y1, 0), to_iso(x2, y2, 0), to_iso(x1, y2, 0)]
        draw.polygon(poly, outline=(26, 25, 23, 60), width=1)
        # Small pigment marker dot in center of room
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        c_pt = to_iso(cx, cy, 0)
        draw.ellipse([c_pt[0]-2, c_pt[1]-2, c_pt[0]+2, c_pt[1]+2], fill=pigment)

    # 4. Helper to draw an extruded 3D wall segment
    wall_h = 2.4  # meters height for cutout view (so interior is visible)

    def draw_wall(x1, y1, x2, y2, h=wall_h):
        # Segment from (x1, y1) to (x2, y2)
        p1_b = to_iso(x1, y1, 0)
        p2_b = to_iso(x2, y2, 0)
        p1_t = to_iso(x1, y1, h)
        p2_t = to_iso(x2, y2, h)

        # Vector in 2D space
        dx = x2 - x1
        dy = y2 - y1

        # Shading depends on orientation
        if abs(dx) > abs(dy):
            side_color = wall_left
        else:
            side_color = wall_right

        # Vertical face
        wall_face = [p1_b, p2_b, p2_t, p1_t]
        draw.polygon(wall_face, fill=side_color, outline=ink, width=1)

    # Helper to draw a wall box with thickness
    def draw_wall_box(x1, y1, x2, y2, h=wall_h, thick=0.2):
        # We draw the 4 sides and top
        corners_b = [
            to_iso(x1, y1, 0),
            to_iso(x2, y1, 0),
            to_iso(x2, y2, 0),
            to_iso(x1, y2, 0)
        ]
        corners_t = [
            to_iso(x1, y1, h),
            to_iso(x2, y1, h),
            to_iso(x2, y2, h),
            to_iso(x1, y2, h)
        ]

        # Draw South-facing or East-facing visible faces
        # Face 1 (front right): from (x2, y1) to (x2, y2)
        draw.polygon([corners_b[1], corners_b[2], corners_t[2], corners_t[1]], fill=wall_right, outline=ink, width=1)
        # Face 2 (front left / south): from (x2, y2) to (x1, y2)
        draw.polygon([corners_b[2], corners_b[3], corners_t[3], corners_t[2]], fill=wall_left, outline=ink, width=1)
        # Face 3 (top)
        draw.polygon(corners_t, fill=wall_top, outline=ink, width=1)

    # Walls list sorted back-to-front for proper painter's algorithm
    # Back walls (North & West)
    draw_wall_box(1.0, 1.0, 15.0, 1.2, h=1.8)
    draw_wall_box(1.0, 1.0, 1.2, 11.0, h=1.8)

    # Interior dividing walls (lower height 1.4m for clear cutaway view)
    draw_wall_box(7.3, 1.2, 7.5, 6.0, h=1.4)
    draw_wall_box(1.2, 5.9, 15.0, 6.1, h=1.4)
    draw_wall_box(1.2, 7.1, 10.0, 7.3, h=1.4)
    draw_wall_box(5.3, 7.3, 5.5, 11.0, h=1.4)
    draw_wall_box(10.0, 7.3, 10.2, 11.0, h=1.4)
    draw_wall_box(12.4, 7.3, 12.6, 11.0, h=1.4)

    # Front walls (East & South) - low 0.8m cutaway profile
    draw_wall_box(14.8, 1.2, 15.0, 11.0, h=0.9)
    draw_wall_box(1.0, 10.8, 15.0, 11.0, h=0.9)

    # Door swing arcs on floor
    doors = [
        (4.0, 6.0, 0.72),
        (11.0, 6.0, 0.72),
        (3.2, 7.2, 0.64),
        (7.8, 7.2, 0.68),
        (1.1, 6.16, 0.88),
        (11.35, 10.9, 1.0),
    ]
    for dx, dy, dw in doors:
        p_ctr = to_iso(dx, dy, 0.05)
        p_swing = to_iso(dx + dw * 0.7, dy + dw * 0.7, 0.05)
        draw.line([p_ctr, p_swing], fill=pigment, width=2)
        draw.ellipse([p_ctr[0]-3, p_ctr[1]-3, p_ctr[0]+3, p_ctr[1]+3], fill=pigment)

    # Save PNG
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, "PNG", optimize=True)
    print(f"Generated hero image at {output_path} ({width}x{height} px).")

if __name__ == "__main__":
    create_hero_png()
