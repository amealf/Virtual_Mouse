from PyInstaller.utils.hooks import collect_all

mp_data, mp_bins, mp_imports = collect_all('mediapipe')
a = Analysis(['main.py'],
    datas=mp_data + [('hand_landmarker.task', '.'), ('LICENSE', '.')],
    binaries=mp_bins, hiddenimports=mp_imports,
    excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
    name='GestureController', console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name='GestureController', upx=False)
