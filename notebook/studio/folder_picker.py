"""Run the native folder picker in its own main-thread process."""
import json
import sys
import tkinter as tk
from tkinter import filedialog

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        result = filedialog.askdirectory(parent=root, title="Referenzordner für Studio auswählen",
                                         initialdir=sys.argv[1], mustexist=True)
        sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    finally:
        root.destroy()
