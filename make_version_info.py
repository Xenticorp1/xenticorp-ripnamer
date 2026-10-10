"""Writes version_info.txt (the Windows exe's Properties → Details) from ripnamer_app.VERSION,
so a release only needs the version changed in one place. Run by build.bat and the release workflow."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ripnamer_app import VERSION  # noqa: E402


def render(version: str) -> str:
    parts = [int(p) for p in version.split(".")][:4]
    nums = tuple(parts + [0] * (4 - len(parts)))
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Xenticorp'),
      StringStruct('FileDescription', 'Xenticorp Ripnamer v{version}'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'RipNamer'),
      StringStruct('LegalCopyright', 'Xenticorp'),
      StringStruct('OriginalFilename', 'Xenticorp Ripnamer v{version}.exe'),
      StringStruct('ProductName', 'Xenticorp Ripnamer'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "version_info.txt"
    out.write_text(render(VERSION), encoding="utf-8")
    print(f"Wrote {out.name} for v{VERSION}")
