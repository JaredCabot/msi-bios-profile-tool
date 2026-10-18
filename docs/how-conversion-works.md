# How conversion works

An MSI OC profile is a copy of the BIOS's settings stores (UEFI variables such as `Setup`, `AmdSetupRPL` and `HwmSetupData`), byte for byte, stamped with the BIOS version and a checksum. Each setting is a byte or two at a fixed offset in one of those stores, and the offsets come from the BIOS's setup menu definitions (HII forms). When MSI adds a setting, later settings in the same store can move. Between 2.A20 and 2.A22 on the MS-7E49, the main `Setup` store grew from 2,553 to 2,632 bytes and 339 settings moved. That is why the BIOS refuses a profile from another version.

The tool reads the setup menus out of both BIOS files with UEFIExtract and IFRExtractor-RS, so it knows where every setting is stored in each version, and rebuilds each store for the target BIOS.

## 1. Read both BIOS files

- **Menus.** UEFIExtract unpacks the image in its flat `unpack` mode, which keeps file paths short enough for Windows. Every module with HII forms is turned into text by IFRExtractor-RS and parsed into forms, settings, storage offsets, options, defaults and the show/hide conditions (`SuppressIf`, `GrayOutIf`, `DisableIf`). If IFRExtractor-RS can't read a module, the tool names it in the console and at the top of every report made with that BIOS.
- **Factory defaults.** Read from the `StdDefaults` entry of the image's NVRAM store, which is what "Load Optimized Defaults" applies. Its nested entries refer to a GUID table at the end of the `StdDefaults` data itself, not to the outer store's table.
- **AMD CBS layout ID.** See below.

What the tool reads is cached per BIOS file in `cache/`. A new version of the tool reads each BIOS file again, so a fix to the parsers takes effect without deleting the cache by hand.

## 2. Match the settings

For each store in the profile, the settings of both versions are listed in offset order and matched in four passes:

1. The two lists are lined up by setting name and type (`difflib.SequenceMatcher`), and runs that match are paired. This copes with settings inserted or removed in between, and with names that repeat. MSI's OC pages, for example, exist in three copies, one per CPU family, at different offsets.
2. In the stretches that don't line up, settings whose name and type occur the same number of times on both sides are paired in order.
3. What is left is paired where a name and type occurs exactly once on each side, which catches settings moved to another page (2.A22 moved TSME and Data Scramble from Advanced DRAM Configuration to the AMD CBS page).
4. Unnamed settings left over at exactly the same offset, type and size are paired as they are.

## 3. Rebuild each store

- **Same layout.** If the store is the same size and every paired setting is at the same offset, the old bytes are kept as they are.
- **Changed layout.** The store starts from the target's factory defaults. Bytes that no menu setting covers, such as CPU detection data and internal values, are carried across wherever the two versions' factory defaults line up. For a store with no factory defaults, the gaps between paired settings are carried across when they are the same size in both versions; gaps that differ only by trailing padding are carried too. Anything that still can't be placed is listed in the report.
- **Settings in both versions** get their old value at the new offset. An option is carried by its text: if the old value's option has a different number in the target, the setting gets the new number and is flagged "Check". If the same number now has a different text (2.A22 renamed IOMMU's "Auto" to "Compatible Mode"), the value is kept and flagged, because the tool can't tell a new name from a new meaning. A number whose range changed between versions is kept if the target accepts it, and flagged.
- **New settings** get the target's factory default, or the default from the menu definition when the store has no factory defaults.
- **Removed settings** are reset to the target's factory default where it has one and no new setting uses those bytes, because no menu can change them any more. On the MS-7E49, 2.A25 removed the two SecureBio settings and made Disabled their default.
- **Values the target doesn't accept.** A value that was valid in the old version but has no matching option in the target, or is outside its range, is replaced by the target's default and flagged "Check". Values that were already outside the options in the old version are left alone: the BIOS wrote them, so they mean something to it.
- **Stores the menus don't describe** are copied unchanged.

## 4. AMD CBS layout ID

The AMD CBS settings store (`AmdSetupRPL`, and `AmdSetupPHX` / `AmdSetupSTXKRK` for other CPU families) starts with two 32-bit values at offsets 0 and 8. AMD's `CbsBaseDxe` and `CbsSetupDxe` modules write them as constants when they load the CBS defaults (`mov dword [rcx], A` / `mov dword [rcx+8], B`). Each BIOS build has its own pair:

| BIOS (MS-7E49) | Offset 0 | Offset 8 |
|---|---|---|
| 2.A20 | `db c3 f3 71` | `87 14 98 bf` |
| 2.A22 | `83 26 f0 09` | `6e fe 61 b7` |
| 2.A25 | `25 bf e4 d1` | `99 8b a2 50` |

A store whose values don't match the running BIOS is replaced with CBS defaults at boot, so a profile that kept the old ID would lose every AMD CBS setting without warning. The tool reads the pair from each BIOS file by that instruction pattern and writes the target's values. Stores of CPU families not in use have a blank header and are left alone.

## 5. Finish the file

The BIOS version is changed in the header and in the `$OCI$` block at the end, and the checksum is recalculated. The tool reads the new file back and checks its checksum, both version fields, the board ID, and that every entry kept its number, store ID and attributes. If any check fails, nothing is written.

The entries themselves come from the old profile. If the target BIOS has a settings store the old one didn't, the profile has no entry for it, and the report says so: loading the profile leaves that store as it is on the board.

Some problems don't stop the conversion but make the result less certain: bytes that couldn't be lined up with a rebuilt layout, an AMD CBS layout ID that couldn't be found in a BIOS file, or a store whose size the target BIOS doesn't expect. The tool shows each one and writes the file only if you answer yes.

The converted file is then decoded with the target BIOS's menus for the conversion report.

## The conversion report

The report is the converted profile decoded with the target BIOS's menus. At the top it says what the conversion did and lists:

- the settings to check: options that were renumbered or renamed, ranges that changed and values that were replaced (copies of these on pages the BIOS hides with the current settings are only counted),
- the settings on screen that are new in the target BIOS, with the default they were given,
- the settings the target BIOS no longer has, with their old value,
- renamed settings,
- any store data that could not be placed,
- how many entries were copied because the tool can't tell which settings store they belong to (26 small entries, 149 bytes, on the MS-7E49).

Below that are the usual "Changed" and "All settings" views. Settings the conversion flagged are marked in the list.

## Tests

`tests/` checks the profile format, the matching, how values are carried, the NVRAM and menu-text parsers, the menu order and value formats of the reports, with small made-up inputs, so it needs no firmware. The tests below were run with real profiles and BIOS files from an MS-7E49, which can't be published.

- **2.A22 to 2.A25.** Every setting carried across in place. The only differences from the source file are the version (2 places), the checksum, the SecureBio settings (6 bytes) and the AMD CBS layout ID (8 bytes). The result was byte-identical on Windows and Linux. Converting the result back to 2.A22 gives the original file byte for byte.
- **2.A20 to 2.A22.** A profile saved on 2.A20 in June 2026 was converted and compared with a profile saved on 2.A22 in October 2026 on the same PC. Every setting matched except the ones changed by hand between those dates, and the AMD CBS layout ID matched the one the 2.A22 BIOS had written itself. The three AMD Overclocking timings new in 2.A22 (tCCD_L, tCCD_L_WR and tCCD_L_WR2) got the values 8, 32 and 16 from the menu definitions, the same as in the profile 2.A22 saved.
- **Menus and defaults.** What the tool reads from the 2.A20, 2.A22 and 2.A25 images is identical to an independent extraction with the UEFITool tree dump.
- **Decoding.** For a 2.A22 profile, the list of settings that differ from the factory defaults matched, setting for setting, a decode of the same settings read through Windows.
