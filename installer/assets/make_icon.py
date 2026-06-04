import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow is not installed. Please run: pip install Pillow")
    sys.exit(1)

def create_icon():
    # Setup
    size = (512, 512)
    bg_color = "#1a1a2e"
    text_color = "white"
    text = "BA"
    
    # Create image
    img = Image.new('RGBA', size, bg_color)
    draw = ImageDraw.Draw(img)
    
    # Try to load a font, otherwise use default
    font = None
    try:
        # Windows
        font = ImageFont.truetype("arialbd.ttf", 250)
    except IOError:
        try:
            # Mac
            font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 250)
        except IOError:
            font = ImageFont.load_default()

    # Draw text centered
    try:
        draw.text((256, 256), text, fill=text_color, font=font, anchor="mm")
    except TypeError:
        # Fallback for older Pillow versions
        w, h = draw.textsize(text, font=font)
        draw.text(((512-w)/2, (512-h)/2), text, fill=text_color, font=font)

    # Save paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    png_path = os.path.join(script_dir, "icon.png")
    ico_path = os.path.join(script_dir, "icon.ico")
    icns_path = os.path.join(script_dir, "icon.icns")
    
    # Save PNG
    img.save(png_path, "PNG")
    print(f"Created {png_path}")
    
    # Save ICO
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(ico_path, format="ICO", sizes=icon_sizes)
    print(f"Created {ico_path}")
    
    # Save ICNS
    try:
        img.save(icns_path, format="ICNS")
        print(f"Created {icns_path}")
    except Exception as e:
        print(f"Note: Could not create ICNS via Pillow ({e}).")
        print("CI pipeline will generate it using sips/iconutil instead if needed.")

if __name__ == "__main__":
    create_icon()
