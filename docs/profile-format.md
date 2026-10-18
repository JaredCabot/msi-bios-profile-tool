# MSI OC profile format (.ocb)

As found on the MSI MPG X870E CARBON MAX WIFI (MS-7E49) with BIOS 2.A20 and 2.A22. MSI doesn't document the format; this is what the files show. All numbers are little-endian.

## Layout

| Offset | Size | Contents |
|---|---|---|
| 0x00 | 5 | `$MOS$` |
| 0x05 | 9 | Board ID, `E7E49AMSI` |
| 0x0E | 1 | `.` |
| 0x0F | 4 | BIOS version, `2A22` |
| 0x13 | 4 | Checksum |
| 0x17 | 4 | Number of entries (112 on the MS-7E49) |
| 0x1B | | Entries |
| after the entries | 256 | Copy of CMOS RAM. Bytes 0 to 9 are the real-time clock in BCD, so they give the save time. |
| then | | `$OCI$` block |

The tool doesn't assume the board ID is 9 characters long: it finds the `.` and reads the version and checksum after it.

### Checksum

The u32 at 0x13 makes the sum of the whole file, with the checksum field counted as zero, plus the checksum come to zero mod 2^32:

```
checksum = -(sum of every byte except the 4 checksum bytes) mod 2^32
```

### Entries

```
u32 index        entry number, not always consecutive
u32 id           stands for the settings store; the same in 2.A20 and 2.A22 files
u32 attributes   1, 2, 3 or 7 (7 for most stores); 0 for AMD_PBS_SETUP and AodSetupRpl
u16 size         0 for stores that were empty or absent
u8  data[size]   the store, byte for byte
```

The ID is a 32-bit value derived from the store name; how it is derived hasn't been worked out. CRC-32 variants, FNV and the other usual hashes of the name or name plus GUID don't produce it. The tool knows the IDs below and matches other entries to the BIOS's stores by size, preferring the candidate whose bytes look most like that store's factory defaults.

| ID | Store | Vendor GUID |
|---|---|---|
| 0x417276EE | Setup | EC87D643-EBA4-4BB5-A1E5-3F3E36B20DA9 |
| 0xFFFCC9C3 | PlatformLang | 8BE4DF61-93CA-11D2-AA0D-00E098032B8C |
| 0x5BE4FD77 | Timeout | 8BE4DF61-93CA-11D2-AA0D-00E098032B8C |
| 0x769DC2FB | AMITSESetup | C811FA38-42C8-4579-A9BB-60E94EDDFB34 |
| 0xDA6C8969 | MsiOcInfoFlag | 48419251-DD85-4597-84B4-11182014ADDE |
| 0x24ACE52B | UsbSupport | EC87D643-EBA4-4BB5-A1E5-3F3E36B20DA9 |
| 0xFF1F5B74 | NetworkStackVar | D1405D16-7AFC-4695-BB12-41459D3695A2 |
| 0x6B6125A9 | MemoryZCoreSetupData | 521EA100-F3B7-4BDD-9193-57F917D6FE79 |
| 0x4E602232 | HwmSetupData (fan control) | B4B6D1E7-039D-4CEF-8742-BA34DA443ECE |
| 0x538A16BC | IpConfiguration | 6E049A5E-0EED-4ABF-A39F-8ABB159EE7E7 |
| 0x3EB725D4 | SecureBootSetup | 7B59104A-C00D-4158-87FF-F04D6396A915 |
| 0x5C69FAA8 | ROM_CMN | 97CDC6BE-7792-4782-BA6D-E6E3BB56ACD8 |
| 0x1A34E05A | AmdSetupPHX (AMD CBS, Phoenix) | 3A997502-647A-4C82-998E-52EF9486A247 |
| 0x53496D3C | AmdSetupRPL (AMD CBS, Raphael and Granite Ridge) | 3A997502-647A-4C82-998E-52EF9486A247 |
| 0x5AE4D5E9 | AmdSetupSTXKRK (AMD CBS, Strix and Krackan) | 3A997502-647A-4C82-998E-52EF9486A247 |
| 0x291DC81E | FixedBoot | DE8AB926-EFDA-4C23-BBC4-98FD29AA0069 |
| 0x49C58225 | AMD_PBS_SETUP | A339D746-F678-49B3-9FC7-54CE0F9DF226 |
| 0x6467632A | AodSetupRpl (AMD Overclocking) | 5ED15DC0-EDEF-4161-9151-6014C4CC630C |

Matched by size on the MS-7E49: FixedBootGroup (14 bytes), UsbMassDevValid (32), HddSecDynamicSetup (44), PcieSataModVar (3) and PcieSataSetupVar (18). About 30 small entries (1 to 74 bytes) stay unidentified; the tool copies them unchanged.

Only the store for the CPU family in use is filled in properly. The others hold defaults with a blank header (see the AMD CBS layout ID in [how-conversion-works.md](how-conversion-works.md)).

### $OCI$ block

```
"$OCI$" 00
board ID 00            E7E49AMSI
BIOS version 00        2A22
CPU name 00            as reported by the CPU, padded with spaces
save time 00           yyyymmddhhmmss
u32 x 4                10000, 43, 1348 (or similar), 6200 on the MS-7E49
zero padding
```

The four numbers look like reference clock (100.00 MHz), a multiplier, a voltage in mV and the memory speed, but this hasn't been checked.

## What the BIOS checks

The BIOS refuses a profile whose version (at 0x0F, and in the `$OCI$` block) differs from its own. A profile re-labelled to the right version with a correct checksum is expected to load; whether the BIOS checks anything else hasn't been confirmed on a board yet.

## Factory defaults in the BIOS image

The defaults that "Load Optimized Defaults" applies are in the NVRAM store inside the image (a raw FFS file, GUID `CEF5B9A3-476D-497F-9FDC-E98143E0422C`), in an AMI NVAR entry named `StdDefaults`. Its data is itself a list of NVAR entries, one per settings store. Those nested entries give their vendor GUID as an index into a GUID table at the end of the `StdDefaults` data (16 bytes per GUID, index 0 last), not into the outer store's table.
