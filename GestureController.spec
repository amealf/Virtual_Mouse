from PyInstaller.utils.hooks import collect_all

mp_data, mp_bins, mp_imports = collect_all('mediapipe')
a = Analysis(['desktop_app.py'],
    datas=mp_data + [('hand_landmarker.task', '.'), ('LICENSE', '.')],
    binaries=mp_bins, hiddenimports=mp_imports,
    excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
    name='GestureController', console=False, upx=False, icon='assets/controller.ico')
coll = COLLECT(exe, a.binaries, a.datas, name='GestureController', upx=False)
