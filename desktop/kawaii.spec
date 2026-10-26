# PyInstaller spec for the Mac app:  pyinstaller desktop/kawaii.spec  (from the repo root, after `npm run build` and
# `python desktop/make_icon.py`).  APP_VERSION=1.2.3 sets the version shown in Finder.
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
STUDIO, SCRIPTS = os.path.join(ROOT, 'studio'), os.path.join(ROOT, 'scripts')
VERSION = os.environ.get('APP_VERSION', '0.0.0').lstrip('v')
NAME = 'Kawaii Chaos Studio'

# The Studio's own modules + every script it runs (so their imports — numpy, cv2, scipy, PIL… — are bundled; the scripts
# themselves ship as files and run through the app binary, see desktop/main.py).
script_mods = [f[:-3] for f in os.listdir(SCRIPTS) if f.endswith('.py')]
hidden = (['server', 'config'] + collect_submodules('api') + collect_submodules('security') + collect_submodules('storage')
          + collect_submodules('uvicorn') + collect_submodules('scipy', filter=lambda n: '.tests' not in n) + collect_submodules('scipy._external')
          + collect_submodules('cv2') + script_mods + ['multipart', 'argon2', 'pyotp', 'boto3', 'botocore', 'webview'])

import imageio_ffmpeg                                           # bundled ffmpeg (used when none is installed)
ff = imageio_ffmpeg.get_ffmpeg_exe()

a = Analysis(
    [os.path.join(ROOT, 'desktop', 'main.py')],
    pathex=[STUDIO, SCRIPTS],
    binaries=[(ff, 'imageio_ffmpeg/binaries')],
    datas=[(os.path.join(STUDIO, 'web', 'dist'), 'studio/web/dist'), (SCRIPTS, 'scripts'),
           (os.path.join(ROOT, 'fonts'), 'fonts'), (os.path.join(ROOT, 'starter'), 'starter')]
          + collect_data_files('botocore') + collect_data_files('webview'),
    hiddenimports=hidden,
    excludes=['torch', 'transformers', 'diffusers', 'tkinter', 'matplotlib', 'IPython', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, codesign_identity=os.environ.get('CODESIGN_IDENTITY') or None,
          entitlements_file=None, target_arch=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=NAME)
app = BUNDLE(
    coll, name=f'{NAME}.app', icon=os.path.join(ROOT, 'desktop', 'build', 'icon.icns'),
    bundle_identifier='io.github.kawaiichaosstudio',
    version=VERSION,
    info_plist={
        'CFBundleName': NAME, 'CFBundleDisplayName': NAME,
        'CFBundleShortVersionString': VERSION, 'CFBundleVersion': VERSION,
        'LSMinimumSystemVersion': '12.0', 'NSHighResolutionCapable': True,
        'LSApplicationCategoryType': 'public.app-category.graphics-design',
        'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True},
        'NSDocumentsFolderUsageDescription': 'Your comics are kept in Documents/Kawaii Chaos Studio.',
        'NSDownloadsFolderUsageDescription': 'To import pictures you downloaded (Pictures → Import from Downloads).',
        'NSDesktopFolderUsageDescription': 'To copy finished files to your export folder.',
    },
)
