import sys
import time

sys.path.append("/Users/aaditeshkadu/Desktop/Dev Projects/RPA/RPA/python_agent")
import rust_core

print("Moving mouse to 466, 758 (logical Samsung center)...")
rust_core.click_mouse(466, 758)
time.sleep(2)
w, h, p = rust_core.capture_screen()
from PIL import Image
Image.frombytes("RGBA", (w, h), p, "raw", "BGRA").save("test1.png")

print("Moving mouse to 975, 375 (logical Technoblade center)...")
rust_core.click_mouse(975, 375)
time.sleep(2)
w, h, p = rust_core.capture_screen()
Image.frombytes("RGBA", (w, h), p, "raw", "BGRA").save("test2.png")
