"""Build script for py2app — creates macOS .app bundle."""

from setuptools import setup

APP = ['src/optsnap/__main__.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': False,
    'plist': {
        'CFBundleName': 'OptSnap',
        'CFBundleDisplayName': 'OptSnap',
        'CFBundleGetInfoString': 'AltSnap-like window manager for macOS',
        'CFBundleIdentifier': 'com.optsnap.app',
        'CFBundleVersion': '0.1.0',
        'CFBundleShortVersionString': '0.1.0',
        'NSHumanReadableCopyright': 'OptSnap',
    },
    'packages': ['optsnap'],
    'iconfile': None,  # Add path to .icns file if you have one
    'includes': [
        'Quartz',
        'ApplicationServices',
        'CoreText',
        'Foundation',
        'rumps',
    ],
}

setup(
    app=APP,
    package_dir={'': 'src'},
    packages=['optsnap'],
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
