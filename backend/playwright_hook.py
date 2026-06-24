import os
import sys
import pathlib

if getattr(sys, 'frozen', False):
    # When bundled by PyInstaller, Playwright browsers aren't inside the bundle.
    # Point Playwright at the user's system-installed browser cache instead.
    mac_path = pathlib.Path.home() / 'Library' / 'Caches' / 'ms-playwright'
    linux_path = pathlib.Path.home() / '.cache' / 'ms-playwright'
    if mac_path.exists():
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(mac_path)
    elif linux_path.exists():
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(linux_path)
