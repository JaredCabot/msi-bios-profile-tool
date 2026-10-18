# MSI BIOS Profile Tool

Reads MSI Click BIOS overclocking profiles (`.ocb`), lists every setting in them with MSI's own help text, and moves a profile to a newer (or older) BIOS version.

**Download:** [Windows](https://github.com/JaredCabot/msi-bios-profile-tool/releases/latest/download/MSI-BIOS-Profile-Tool-windows-x86_64.exe) or [Linux](https://github.com/JaredCabot/msi-bios-profile-tool/releases/latest/download/msi-bios-profile-tool-linux-x86_64), from the [latest release](https://github.com/JaredCabot/msi-bios-profile-tool/releases/latest). Each is a single program that needs no Python and no installer.

MSI boards refuse to load a profile saved under another BIOS version, so after a BIOS update every setting has to be entered again by hand. This tool reads the setup menus out of both BIOS files, works out where each setting lives in each version, and rebuilds the profile for the new BIOS. When you'd rather enter the settings yourself, it gives you a checklist of exactly what differs from the factory defaults.

Written for the MSI MPG X870E CARBON MAX WIFI (MS-7E49) and tested with its BIOS versions 2.A20, 2.A22 and 2.A25. The menu layout was checked against screenshots of the Advanced, Overclocking, Security and Boot menus of the 2.A22 BIOS: the pages, the settings on them, their order and their values match, except for a few entries the BIOS builds at run time (such as Memory OC Mode and the boot device lists). The Hardware Monitor page was checked the same way on 2.A25. Every value matches; the page also shows a few inactive values greyed out (the fan curve of a fan with Smart Fan off, the fixed speed of a fan with Smart Fan on, and the fan group), which the tool leaves out. The System Status page wasn't captured. Other MSI AM5 boards that use the same profile format and Click BIOS X should work, but haven't been tried. Reports on other boards are welcome.

On a BIOS that lays out its menus differently (Click BIOS 5, for example), the report names the menus the tool couldn't find and lists their settings out of screen order. Conversion doesn't depend on the menu layout.

> **A converted profile has not been checked by MSI.** Load it, check the setup screens against the conversion report, and only then press F10. Loading a profile only fills in the setup screens; nothing is saved until F10. If a board ever fails to start after saving settings, Clear CMOS (a button on the rear panel of many MSI boards, or the JBAT1 jumper) returns it to factory defaults.

## What it does

- **Decode a profile** into an HTML page and a CSV. The page lists the settings that differ from the factory defaults (the ones to re-enter after "Load Optimized Defaults"), or every setting on MSI's pages. The settings are listed under the menus of MSI Click BIOS X (Advanced, Overclocking, Security, Boot and Hardware Monitor), in the order the BIOS shows them, and only pages the BIOS shows with your settings and CPU are included. Each setting shows its menu path, its value, the factory default, MSI's help text and every option. It has a search box and tick boxes for working through the list at the BIOS screen, and works offline. It prints the way it looks on screen, on A4 or Letter, and the tick boxes print, so the printout works as a checklist.
- **Convert a profile** to another BIOS version, with a report of what moved, what is new, what has gone and which settings to check by hand.
- **Compare two profiles**, also across BIOS versions.
- **Read the live settings** through Windows (administrator prompt, read-only) and decode them into the same kind of report.

The tool only writes a profile by converting one the BIOS saved itself. It never builds one from scratch.

## Requirements

- Windows x64 or Linux x64.
- Nothing else to install for the ready-built program from the [Releases](https://github.com/JaredCabot/msi-bios-profile-tool/releases) page. To run from source instead, Python 3.9 or later, standard library only.
- The BIOS file the profile was saved on, and for conversion the target BIOS file, from MSI's download page for the board.
- Two free programs that unpack BIOS files. The tool offers to download them on first run; see [The two programs](#the-two-programs).

## Quick start

1. Download the program for your system from the [Releases](https://github.com/JaredCabot/msi-bios-profile-tool/releases) page and put it in a folder of its own (a USB stick works). It keeps its settings and downloads beside itself.
   - Windows: [`MSI-BIOS-Profile-Tool-windows-x86_64.exe`](https://github.com/JaredCabot/msi-bios-profile-tool/releases/latest/download/MSI-BIOS-Profile-Tool-windows-x86_64.exe). It isn't code signed, so SmartScreen asks on the first run: More info, then Run anyway.
   - Linux: [`msi-bios-profile-tool-linux-x86_64`](https://github.com/JaredCabot/msi-bios-profile-tool/releases/latest/download/msi-bios-profile-tool-linux-x86_64). Run `chmod +x` on it first.
2. Put your profiles and the unzipped BIOS files in one folder, arranged any way you like. This is the library.
3. Start the program. On first run it asks for the library folder, offering the folder the program is in, and offers to download the two programs. Keeping the program in the library folder means Enter is all it needs.
4. Choose an option from the menu. Reports are written to a `reports` folder inside the library.

To run from source instead, download or clone this repository and start `msibios.py` with Python: double-click it on Windows (the python.org installer sets this up), or run `py msibios.py`; on Linux, run `python3 msibios.py`.

The first time a BIOS file is used, the tool unpacks it and keeps what it needs in `cache`. This takes 20 to 60 seconds; after that it's instant.

## Menu

1. **Decode a profile into a readable report**
2. **Convert a profile to another BIOS version.** The new file goes next to the original with the version in its name changed (for example `7E49v2A22.ocb` becomes `7E49v2A25.ocb`) and a conversion report goes to `reports`. The original is never changed. If the conversion finds something it can't place with certainty, such as data it couldn't line up with the new layout or an AMD CBS layout ID it couldn't find, it shows the problem and writes nothing unless you answer yes.
3. **Compare two profiles.** Settings are matched by name and menu page. Saved as a text file in `reports`.
4. **Read the settings from this PC** (Windows only). Windows asks for administrator rights, which reading firmware settings needs. The script, `lib/biosread.ps1`, only reads and loads no driver. The raw read (`uefi-vars.json`) and a report go to `reports`. This gives a report only, not a profile: Windows can't read every settings store (the USB settings, for example), so a profile saved in the BIOS is the more complete record. The profiles kept in the BIOS's own OC PROFILE slots can't be read from Windows either; on the MS-7E49 the firmware variable that holds them isn't visible to the operating system.

The library folder is saved in `settings.json`. To change it, start the tool with `--library "<folder>"`, or delete `settings.json` and the tool asks again.

For scripts, `python msibios.py decode <profile.ocb>` writes the report without the menu. It exits with code 1 if no report was written, and stops instead of guessing when it would need to ask a question.

## How conversion works

Settings are matched between the two BIOS versions by name and type, in the order they are stored, never by position, so settings that moved inside a store land in their new place. Data that no menu setting covers is carried across where the two BIOS files' factory defaults line up. Settings that are new in the target BIOS get its factory default; settings it removed are reset to its default. An option is carried by its text, not its number, so if MSI renumbers a list the setting keeps its meaning. A value the target no longer accepts is replaced by the default, and every setting whose option text or range changed is listed in the report under "Check these settings". AMD CBS keeps a layout ID at the start of its settings store that differs between BIOS builds, and the tool writes the target's ID so the BIOS keeps the AMD CBS settings. Finally the version is changed in both places in the file and the checksum is recalculated.

[docs/how-conversion-works.md](docs/how-conversion-works.md) has the details and the tests. [docs/profile-format.md](docs/profile-format.md) describes the `.ocb` format.

After converting:

1. Flash the new BIOS. On the first restart, hold Del to enter setup.
2. Load the converted profile from **OC PROFILE**.
3. Go through the "Changed" list in the conversion report on the setup screens.
4. Press F10. MSI's save dialog lists every change; compare it with the report before confirming.
5. If the BIOS refuses the file, enter the "Changed" list by hand.
6. Once the new BIOS has booted, save a profile from it and compare it with the converted file (option 3) to confirm the settings stuck.

If MSI changes the profile format itself, the tool stops with a message instead of writing a file.

## The two programs

| Program | Version | Licence | Release page |
|---|---|---|---|
| UEFIExtract (part of UEFITool NE) | A75 | BSD 2-clause | [LongSoft/UEFITool](https://github.com/LongSoft/UEFITool/releases/tag/A75) |
| IFRExtractor-RS | 1.6.1 | BSD 2-clause | [LongSoft/IFRExtractor-RS](https://github.com/LongSoft/IFRExtractor-RS/releases/tag/v1.6.1) |

They are not included in this repository. When either is missing, the tool downloads the official release zip for your system, checks it against the SHA-256 value published on the release page, and only then unpacks the program into `bin/windows` or `bin/linux`. If the check fails, nothing is installed. The versions and hashes are fixed in `lib/deps.py`, so a new release can't change the results without a change here.

Without internet access, download the zip on another computer, check it against the SHA-256 value on the release page, and put the program from it (`uefiextract` and `ifrextractor`, with `.exe` on Windows) in `bin/windows` or `bin/linux` beside the tool. The tool doesn't use copies on the system PATH, because their version decides how the BIOS menus are read.

## Files

| Path | Contents |
|---|---|
| `msibios.py` | The menu; start the tool from source with this file |
| `lib/__init__.py` | The version number |
| `lib/ocb.py` | Reads and writes the profile format |
| `lib/firmware.py` | Unpacks a BIOS file: menus, factory defaults, AMD CBS layout ID |
| `lib/ifrparse.py` | Parses the menu text from IFRExtractor-RS |
| `lib/model.py` | Works out which settings are on screen and decodes values |
| `lib/convert.py` | The conversion |
| `lib/report.py` | The HTML and CSV reports |
| `lib/deps.py` | Finds, downloads and checks the two programs |
| `lib/biosread.ps1`, `lib/varlist.txt` | Reads the live settings through Windows, and the list of settings stores to read |
| `lib/paths.py` | Where the tool keeps its files, run from source or as a built program |
| `tests/` | Tests that need no firmware: `python -m unittest discover tests` |
| `MSI BIOS Profile Tool.spec`, `version_info.txt` | The PyInstaller recipe for the built program, and its Windows version details |
| `.github/workflows/release.yml` | Builds the Windows and Linux programs when a version tag is pushed, and attaches them to the release |

Made by the tool beside itself (beside the program, or beside `msibios.py` when run from source), and kept out of the repository: `bin/` (the two programs), `cache/` (unpacked BIOS data, safe to delete) and `settings.json` (the library folder).

## Building the program

The release workflow builds both programs on GitHub. To build one yourself, on the system it is for:

```
python -m pip install pyinstaller==6.22.3
pyinstaller --noconfirm --clean "MSI BIOS Profile Tool.spec"
```

The result is in `dist/`. `"MSI BIOS Profile Tool" --check` confirms that it starts and carries the files it needs.

## Credits

Written by Jared Cabot, with Claude (Anthropic).

## Licence

MIT, see [LICENSE](LICENSE). This project is not affiliated with or endorsed by MSI, AMI or AMD. Product names are trademarks of their owners. Nothing from a BIOS image is included in this repository; the tool reads the BIOS files you supply.
