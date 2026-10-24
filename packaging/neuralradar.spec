# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller (dạng thư mục, không console). Build: `python scripts/build_exe.py`.

Model embedding KHÔNG đóng gói: app tự tải về %APPDATA%\\NeuralRadar\\models ở lần chạy đầu.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH do PyInstaller cung cấp)

datas = [
    # Alembic nạp env.py và các file migration theo đường dẫn nên phải có dạng file, không phải module
    (str(ROOT / "app" / "storage" / "migrations"), "app/storage/migrations"),
    (str(ROOT / "app" / "pipeline" / "prompts"), "app/pipeline/prompts"),
]
binaries = []
hiddenimports = [
    "pystray._win32",
    "keyring.backends.Windows",
    "aiosqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "tzdata",
]

datas += collect_data_files("customtkinter")
for package in ("fastembed", "onnxruntime", "tokenizers", "google.genai", "feedparser"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["sklearn", "pytest", "mypy", "ruff", "pre_commit", "scipy.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NeuralRadar",
    console=False,
    icon=str(ROOT / "packaging" / "neuralradar.ico"),
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="NeuralRadar",
)
