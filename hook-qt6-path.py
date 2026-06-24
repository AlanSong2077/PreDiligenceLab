"""
PyInstaller runtime hook for PyQt6 on macOS.
Fixes SIGSEGV crash during Qt initialization by ensuring
the correct plugin paths are set before any Qt module loads.
"""
import sys
import os

if sys.platform == 'darwin':
    # When running inside a .app bundle, sys.executable points to
    # the binary inside Contents/MacOS/, and Resources are at
    # Contents/Resources/ which is where PyInstaller puts data files.
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)  # Contents/MacOS/
        resources = os.path.join(os.path.dirname(base), 'Resources')
        qt_plugins = os.path.join(resources, 'PyQt6', 'Qt6', 'plugins')
        if os.path.isdir(qt_plugins):
            os.environ['QT_PLUGIN_PATH'] = qt_plugins
        qt_lib = os.path.join(resources, 'PyQt6', 'Qt6', 'lib')
        if os.path.isdir(qt_lib):
            os.environ['DYLD_LIBRARY_PATH'] = qt_lib + ':' + os.environ.get('DYLD_LIBRARY_PATH', '')
