import base64
import io
from PIL import Image

try:
    from Quartz import (
        CGWindowListCreateImage,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
        CGRectInfinite,
    )
    from Quartz.CoreGraphics import (
        CGImageGetWidth,
        CGImageGetHeight,
        CGDataProviderCopyData,
        CGImageGetDataProvider,
    )
    _QUARTZ_AVAILABLE = True
except ImportError:
    _QUARTZ_AVAILABLE = False

def capture_to_bytes():
    """Captures the screen using macOS screencapture command and returns base64 encoded JPEG bytes."""
    import subprocess
    import tempfile
    import os
    
    try:
        # Create a temporary file for the screenshot
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
            temp_path = temp_file.name
        
        # Use macOS screencapture command to capture the main display
        result = subprocess.run([
            'screencapture', 
            '-x',  # Don't play camera sound
            '-t', 'png',  # PNG format
            temp_path
        ], capture_output=True, check=True)
        
        # Read the screenshot file
        with open(temp_path, 'rb') as f:
            png_data = f.read()
        
        # Clean up temp file
        os.unlink(temp_path)
        
        # Convert PNG to JPEG using PIL
        from PIL import Image
        import io
        
        # Open PNG data
        png_image = Image.open(io.BytesIO(png_data))
        
        # Convert to RGB (remove alpha channel if present)
        if png_image.mode in ('RGBA', 'LA'):
            rgb_image = Image.new('RGB', png_image.size, (255, 255, 255))
            rgb_image.paste(png_image, mask=png_image.split()[-1] if png_image.mode == 'RGBA' else None)
        else:
            rgb_image = png_image.convert('RGB')
        
        # Convert to JPEG bytes
        img_byte_arr = io.BytesIO()
        rgb_image.save(img_byte_arr, format="JPEG", quality=85)
        img_bytes = img_byte_arr.getvalue()
        
        # Return base64 encoded
        return base64.b64encode(img_bytes).decode('utf-8')
        
    except subprocess.CalledProcessError as e:
        print(f"screencapture command failed: {e}")
        return None
    except Exception as e:
        print(f"Screenshot error: {e}")
        return None