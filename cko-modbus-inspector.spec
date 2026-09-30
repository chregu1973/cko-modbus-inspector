from pathlib import Path

root = Path(SPEC).resolve().parent

a = Analysis(
    [str(root / "launcher.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "templates"), "templates"),
        (str(root / "static"), "static"),
        (str(root / "device-catalog-entries"), "device-catalog-entries"),
    ],
    hiddenimports=["app"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CKO-Modbus-Inspector",
    console=False,
    icon=str(root / "cko_logo.ico"),
    version=str(root / "installer" / "version-info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name="CKO-Modbus-Inspector")
