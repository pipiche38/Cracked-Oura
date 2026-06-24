# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

a = Analysis(
    ['src/api/main.py'],
    pathex=['..'],  # allow resolving 'backend' package from repo root
    binaries=[],
    datas=[
        ('src', 'backend/src'),  # backend.src.* imports
        # Playwright browsers are NOT bundled here — they live in the user's
        # ~/Library/Caches/ms-playwright and the runtime hook points there.
    ],
    hiddenimports=[
        # uvicorn internals not auto-detected
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # other deps
        'sqlalchemy.dialects.sqlite',
        'playwright',
        'uvloop',
        'anthropic',
        'httpx',
        'anyio',
        'anyio._backends._asyncio',
        'anyio._backends._trio',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['playwright_hook.py'],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='backend',
)
