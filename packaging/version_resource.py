"""The version resource Windows shows in a file's Properties, made from rollcall.VERSION.

Both specs build theirs here, so a release changes the version in one place, `rollcall/__init__.py`.
The first build kept this as a text file with 0.1.0 typed into it twice more, which the next release
would have forgotten. No person's name appears in it: the studio ships Herewise.
"""
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct,
                                                 StringTable, VarFileInfo, VarStruct, VSVersionInfo)

COMPANY = "Emberfig"


def version_info(name: str, version: str, description: str, filename: str) -> VSVersionInfo:
    numbers = [int(part) for part in version.split(".")][:4]
    numbers += [0] * (4 - len(numbers))
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=tuple(numbers), prodvers=tuple(numbers), mask=0x3F, flags=0x0,
                          OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", COMPANY),
                StringStruct("FileDescription", description),
                StringStruct("FileVersion", version),
                StringStruct("InternalName", name),
                StringStruct("LegalCopyright", COMPANY),
                StringStruct("OriginalFilename", filename),
                StringStruct("ProductName", name),
                StringStruct("ProductVersion", version),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
