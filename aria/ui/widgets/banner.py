import os

from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from aria.core.paths import ASSETS_DIR as SCRIPT_DIR

class Banner(Static):
    def render(self) -> Table:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(justify="left", vertical="middle") 
        grid.add_column(justify="left", vertical="middle")  
        
        logo = Text()
        icon_path = os.path.join(SCRIPT_DIR, "banner.png")
        
        try:
            from PIL import Image
            img = Image.open(icon_path).convert("RGBA")
            width, height = img.size
            
            braille_map = {
                (0, 0): 0x01, (1, 0): 0x08,
                (0, 1): 0x02, (1, 1): 0x10,
                (0, 2): 0x04, (1, 2): 0x20,
                (0, 3): 0x40, (1, 3): 0x80
            }
                
            pixels = img.load()
            
            for cy in range(0, height, 4):
                for cx in range(0, width, 2):
                    char_val = 0x2800 
                    r_sum, g_sum, b_sum, count = 0, 0, 0, 0
                    
                    for dx in range(2):
                        for dy in range(4):
                            px, py = cx + dx, cy + dy
                            if px < width and py < height:
                                r, g, b, a = pixels[px, py]
                                if a > 128: #
                                    char_val += braille_map[(dx, dy)]
                                    r_sum += r; g_sum += g; b_sum += b
                                    count += 1
                    
                    if count > 0:
                        r_avg, g_avg, b_avg = r_sum // count, g_sum // count, b_sum // count
                        logo.append(chr(char_val), style=f"rgb({r_avg},{g_avg},{b_avg})")
                    else:
                        logo.append(" ")
                
                if cy < height - 4:
                    logo.append("\n")
                    
        except ImportError:
            logo.append("[Pillow belum diinstall]\nKetik: pip install Pillow", style="bold red")
        except Exception as e:
            logo.append(f"[Gagal memuat icon.png]\n{e}", style="bold red")

        teks = Text()
        mode_label = getattr(self.app, "mode_label", "Local")
        mode_style = "#71d1d1 bold" if mode_label == "Cloud" else "#c97fd4 bold"
        teks.append("Aria", style="#c97fd4 bold")
        teks.append(" | ", style="#7b6b9a")
        teks.append(mode_label, style=mode_style)
        teks.append("\n")
        teks.append("Hadir untuk Membantu\n", style="#c6bbd8 bold")
        teks.append("Dariku untukmu ♡", style="#7b6b9a")
        
        grid.add_row(logo, teks)
        return grid

