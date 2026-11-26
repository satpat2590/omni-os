"""Build per-user Mac apps pointing at the checkout that owns the runtime."""
import plistlib
import shutil
import subprocess
from pathlib import Path


def install_apps(root, state):
    binary = state/"OmniDesktop"
    subprocess.run(["xcrun","swiftc","-parse-as-library","-target",
                    __import__("platform").machine()+"-apple-macos13.0",
                    str(root/"mac/Desktop.swift"),"-o",str(binary)],check=True)
    for name, identifier in (("Omni","dev.omni.platform"),("Atma","dev.omni.atma")):
        bundle = Path.home()/"Applications"/(name+".app")
        info = bundle/"Contents/Info.plist"
        if bundle.exists() and (not info.is_file() or plistlib.loads(info.read_bytes()).get("CFBundleIdentifier") != identifier):
            raise RuntimeError(f"Another application already exists at {bundle}")
        executable = bundle/"Contents/MacOS"/name
        executable.parent.mkdir(parents=True,exist_ok=True)
        replacement = executable.with_suffix(".new")
        shutil.copy2(binary,replacement)
        replacement.replace(executable)
        info.write_bytes(plistlib.dumps(dict(CFBundleName=name,CFBundleIdentifier=identifier,
            CFBundlePackageType="APPL",CFBundleExecutable=name,CFBundleVersion="1",
            CFBundleShortVersionString="0.1",LSMinimumSystemVersion="13.0",OmniCheckout=str(root))))
        subprocess.run(["codesign","--force","--sign","-",str(bundle)],check=True)
        print(f"Installed {bundle}")
