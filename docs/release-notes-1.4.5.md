# RadioMaster+ 1.4.5

A packaging release. How the program works has not changed.

## Windows Defender warning on 1.4.4
Windows Defender flagged the 1.4.4 `RadioMaster+.exe` as `Trojan:Win32/Bearfoos.A!ml`, a machine-learning detection.

The flagged file was audited and no sign of a virus was found:
- All 1,632 bundled Python modules and the startup scripts matched their source files, including all of RadioMaster+'s own.
- Compared with the standard PyInstaller launcher, only a 4-byte build timestamp differed, apart from the added icon and Windows manifest.

The audit covered the flagged program file, not every other file in the download.

## Changes
- The program file now carries its product name, publisher, copyright and version (Properties, then Details). 1.4.4 had none.
- The build never compresses program files with UPX.
- The built program folder, the portable zip and the installer were scanned with Windows Defender before release.

## If Defender removed your copy
Install 1.4.5, or extract the new portable zip over your existing folder. Do not add a Defender exclusion.

## Known limits
- The program is not code-signed, so antivirus programs or Windows SmartScreen may still warn about it. We cannot prove that the added details are what cleared the Defender warning, or that a later Defender update will not flag it again.
