Pick the one for your system. Each is a single program: no Python, no installer, nothing written to the registry. It keeps its settings, the two programs it downloads and its cache beside itself, so put it in a folder you can write to, such as a folder of its own or a USB stick.

| File | For |
|---|---|
| `MSI-BIOS-Profile-Tool-windows-x86_64.exe` | Windows 10 or 11, 64-bit |
| `msi-bios-profile-tool-linux-x86_64` | Linux x86-64, glibc 2.35 or newer |

On Linux, `chmod +x` the file first.

On first run the tool asks for your library folder (where your profiles and BIOS files are) and offers to download UEFIExtract and IFRExtractor-RS from their GitHub release pages. Each download is checked against the SHA-256 published on its release page. See the README.

**A converted profile has not been checked by MSI.** Load it, check the setup screens against the conversion report, and only then press F10.

**The programs are not code signed.** Windows shows SmartScreen on the first run: choose More info, then Run anyway. Some virus scanners also flag programs packed with PyInstaller. The source is in this repository, and the build provenance below ties each file to the commit it was built from.

### Checking what you downloaded

`SHA256SUMS.txt` lists every file: `sha256sum -c SHA256SUMS.txt` on Linux, or `Get-FileHash <file>` in PowerShell. That catches a download that went wrong. It doesn't prove where a file came from, because the list sits on the same page. The build provenance, signed by GitHub, does:

    gh attestation verify <file> --repo JaredCabot/msi-bios-profile-tool
