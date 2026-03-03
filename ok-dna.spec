# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
from PyInstaller.building.build_main import Tree

block_cipher = None

# 自动收集所有 ok 相关的子模块和数据文件
ok_hiddenimports = collect_submodules('ok')
ok_datas = collect_data_files('ok', include_py_files=True)

# 自动收集 onnxocr 相关的所有子模块
onnxocr_hiddenimports = collect_submodules('onnxocr')
onnxocr_hiddenimports += collect_submodules('onnxocr_ppocrv4')

# 收集 onnxocr 的数据文件（包括 .onnx 模型文件）
onnxocr_datas = collect_data_files('onnxocr')
onnxocr_datas += collect_data_files('onnxocr_ppocrv4')

# 收集 openvino 的数据文件
openvino_datas = collect_data_files('openvino', include_py_files=False)
openvino_hiddenimports = collect_submodules('openvino')

# 收集 OpenVINO 的二进制文件（DLL 插件）
import os
import sys
openvino_binaries = []
if sys.platform == 'win32':
    try:
        import openvino
        openvino_dir = os.path.dirname(openvino.__file__)
        openvino_libs = os.path.join(openvino_dir, 'libs')
        if os.path.exists(openvino_libs):
            for file in os.listdir(openvino_libs):
                if file.endswith('.dll'):
                    openvino_binaries.append((os.path.join(openvino_libs, file), 'openvino/libs'))
    except:
        pass

# 尝试收集 onnxruntime 数据文件（如果存在）
try:
    onnxruntime_datas = collect_data_files('onnxruntime', include_py_files=False)
except:
    onnxruntime_datas = []

# 收集所有需要的数据文件（这些会被打包进 _internal）
datas = [
    ('src', 'src'),
    ('configs', 'configs'),
    ('i18n', 'i18n'),
    ('assets', 'assets'),
    ('mod', 'mod'),
    ('icons', 'icons'),
]
datas += ok_datas
datas += onnxocr_datas
datas += openvino_datas
datas += onnxruntime_datas

# 收集所有隐藏导入（包括标准库和第三方库）
hiddenimports = [
    # 标准库
    'uuid',
    'queue',
    'threading',
    'json',
    'logging',
    'logging.handlers',
    'traceback',
    'pathlib',
    'subprocess',
    'ctypes',
    'ctypes.wintypes',
    'winsound',
    'importlib',
    # Playwright
    'playwright',
    'playwright.sync_api',
    # 图像处理
    'cv2',
    'PIL',
    'PIL.Image',
    'numpy',
    # OCR
    'onnxocr_ppocrv4',
    'onnxocr',
    'onnxruntime',
    'openvino',
    # Windows API
    'win32process',
    'win32gui',
    'win32con',
    'win32api',
    'pywintypes',
    'pythoncom',
    'win32com',
    'win32com.client',
    # 系统工具
    'psutil',
    'pycaw',
    'comtypes',
    'pydirectinput',
    'mouse',
    'pyappify',
    # GUI
    'PySide6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'darkdetect',
]
# 添加自动收集的 ok 模块
hiddenimports += ok_hiddenimports
# 添加自动收集的 onnxocr 模块
# 添加自动收集的 openvino 模块
hiddenimports += openvino_hiddenimports
hiddenimports += onnxocr_hiddenimports

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=openvino_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ok-DNA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icons\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    # 将这些文件夹复制到 exe 同级目录（运行时代码需要）
    Tree('mod', prefix='mod'),
    Tree('configs', prefix='configs'),
    Tree('assets', prefix='assets'),
    Tree('icons', prefix='icons'),
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ok-DNA',
)
