# provenance_time (ptime) -- Linux Kernel Patch

A new settable inode timestamp for the Linux kernel that preserves file provenance (original creation dates) across copies, moves, application saves, btrfs send/receive, and filesystem transitions.

**Status**: Running on EndeavourOS (Arch), kernel 6.19.11. 5 filesystems (Btrfs, ext4, ntfs3, FAT32, exFAT), btrfs send/receive with ptime TLV, 6 patched userspace tools + patched btrfs-progs, KDE Dolphin GUI integration. All runtime tests passing. Automated daily btrbk backups with ptime preservation verified end-to-end.

**RFC**: [Proposal on linux-fsdevel](https://lore.kernel.org/linux-fsdevel/CAOx6djP4hb-Cd1Zk07SNfFfLc8irjNmbVqq+58h1Whz+h1wSFA@mail.gmail.com/T/#u) (March 2026)

## Quick Start

### Just the patches (apply to upstream source)

All patches are in the `patches/` directory, organized by component:

| Component | Patch | Applies to |
|-----------|-------|------------|
| **Linux kernel** | `patches/kernel/ptime-v6.1.patch` (monolithic, 744 lines) | Vanilla 6.19.11 (`patch -Np1`) |
| **Linux kernel** | `patches/kernel/format-patches-v6.1/` (16 individual commits) | Vanilla 6.19.11 (`git am`) |
| **btrfs-progs** | `patches/btrfs-progs/btrfs-progs-ptime.patch` (263 lines) | btrfs-progs v6.19.1 (`patch -Np1`) |
| **coreutils** (cp, mv) | `patches/coreutils/patch-cp-v2.py` | coreutils 9.6 (Python script) |
| **rsync** | `patches/rsync/patch-rsync-v2.py` | rsync 3.4.1 (Python script) |
| **GNU tar** | `patches/tar/patch-tar.py` | tar 1.35 (Python script) |
| **KDE KIO** | `patches/kio/kio-ptime.patch` | kio 6.24.0 (`patch -Np1`) |
| **KDE Dolphin** | `patches/dolphin/dolphin-ptime.patch` | dolphin 25.12.3 (`patch -Np1`) |
| **BorgBackup** | `patches/borg/patch-borg-ptime.py` | borg 1.4.4 (Python script) |

Python patch scripts modify source files in-place and are applied via `python3 script.py [path/to/file]` during PKGBUILD `prepare()`. Clean `.patch` files are standard unified diffs applied via `patch -Np1`.

### Full source forks (for development or detailed inspection)

For people who want the complete patched source trees with commit history:

| Component | Upstream | Our Fork | Branch |
|-----------|----------|----------|--------|
| Linux kernel | [gregkh/linux](https://github.com/gregkh/linux) | **[DefendTheDisabled/linux](https://github.com/DefendTheDisabled/linux/tree/ptime-v6-base)** | `ptime-v6-base` (16 commits on v6.19.11) |
| btrfs-progs | [kdave/btrfs-progs](https://github.com/kdave/btrfs-progs) | **[DefendTheDisabled/btrfs-progs](https://github.com/DefendTheDisabled/btrfs-progs/tree/ptime-send-receive)** | `ptime-send-receive` (5 commits on v6.19.1) |

Userspace tool patches (coreutils, rsync, tar, kio, dolphin, borg) are single-file modifications to upstream releases. The patch files in `patches/<tool>/` are the authoritative source; dedicated forks are not maintained for these.

## The Problem

Linux has no syscall to set file birth time (btime). Every file copy resets the creation date to "now." This has been an acknowledged and unresolved kernel limitation since 2019, where proposals to make btime settable stalled over the question of whether btime's forensic semantics should be preserved.

An xattr-based workaround (user.provenance_time) was attempted and found **structurally unworkable**:

1. **Atomic saves destroy xattrs** -- Applications save via write-to-temp + rename(), replacing the inode. All xattrs are permanently destroyed. Only the kernel sees both inodes during rename() -- no userspace wrapper, daemon, or hook can copy metadata across this boundary.
2. **Silent opt-in failure** -- Each tool must explicitly preserve xattrs (cp needs --preserve=xattr, rsync needs -X, tar needs --xattrs). Any missing flag causes silent metadata loss. Transparent preservation through arbitrary tool flows is not achievable in userspace.

Atomic saves are the default behavior of mainstream applications (LibreOffice, Vim, Kate, etc.). These are architectural limitations of the xattr approach, not fixable implementation bugs.

## Relationship to Existing Proposals

ptime builds directly on prior kernel work and resolves the semantic impasse:

| Proposal | How ptime relates |
|----------|-------------------|
| **Sandoval's AT_UTIME_BTIME (2019)** | ptime addresses the same need (settable creation date) via file_setattr, sidestepping both the btime mutability dispute and the glibc wrapper limitation that blocked Sandoval's utimensat approach |
| **Ts'o's btime/crtime split (March 2025)** | ext4 ptime implements his concept -- dedicated i_ptime alongside immutable i_crtime. "crtime which *can* be changed by a system call interface." |
| **Chinner's forensic btime objection (2019)** | ptime is a separate field on native filesystems -- btime remains immutable; no forensic semantics are changed |
| **Sterba's Btrfs otime / send v2** | ptime infrastructure serves the settable-timestamp need for send/receive; ptime TLV is now implemented in the send stream |
| **Boaz Harrosh's "Author creation time" (2019)** | ptime formalizes the distinction between globally-carried author creation time and local filesystem creation time |

The core design insight: btime and ptime answer different questions. btime is forensic ("when was this inode born on this disk?"). ptime is provenance ("when was this file's content first created, anywhere?"). Making them separate fields resolves the dispute -- forensic btime stays immutable, and provenance data gets its own settable channel.

## The Solution

provenance_time (ptime) is a new inode timestamp:

| Timestamp | Purpose | Settable? |
|-----------|---------|-----------|
| **btime** | When this inode was born on THIS filesystem | No (forensic -- immutable) |
| **ptime** | When this file's content was first created, anywhere | **Yes** (travels with data) |

The key capability that only the kernel can provide: **rename-over preservation**. When applications save via write-to-temp + rename(), the kernel copies ptime from the overwritten file to the new file. This is implemented on all 5 supported filesystems.

### Architecture: Native vs Mapped

| Category | Filesystems | Mechanism | btime impact |
|----------|-------------|-----------|-------------|
| **Native** | Btrfs, ext4 | Dedicated on-disk ptime field | btime remains immutable |
| **Mapped** | ntfs3, FAT32, exFAT | ptime reads/writes the existing creation time field | Creation time becomes settable (matches Windows behavior) |

Linux-native filesystems preserve forensic btime alongside the settable ptime. Bridge filesystems (NTFS, FAT) already treat creation time as mutable on Windows; Linux gains parity.

## Use Case

This patch was created to solve a concrete problem: preserving document creation dates during migration between Windows (NTFS) and Linux (Btrfs). Workflows involving legal, archival, and forensic documents require provenance metadata to survive filesystem transitions. The ptime field carries original creation dates through any supported filesystem, tool, or application save operation.

Additionally, ptime preservation through **btrfs send/receive** enables automated backup systems like btrbk to maintain file provenance across snapshots and incremental transfers -- without ptime in the send stream, every btrbk backup silently strips creation dates.

## API Design

**Setting ptime**: Uses the file_setattr syscall (469, merged Linux 6.17 by Andrey Albershteyn of Red Hat). ptime fields are added to `struct file_attr` as a VER1 extension (40 bytes). The size-versioned struct is forward/backward compatible -- same pattern as clone_args and mount_attr. No glibc wrapper conflicts; tools pass a struct pointer. Suggested by Darrick J. Wong (XFS maintainer) during RFC review.

Internally, the kernel dispatches ptime writes through `notify_change()` (the standard iattr/setattr path), reusing all existing per-filesystem ptime handlers unchanged. The file_setattr syscall validates `fa_ptime_nsec < NSEC_PER_SEC` and `fa_ptime_pad == 0` for safety and forward compatibility.

**Reading ptime**: statx() returns ptime via STATX_PTIME (0x00040000U) in the stx_ptime field.

**Btrfs send/receive**: Patched kernel emits `BTRFS_SEND_A_PTIME` TLV in the send stream when `send_protocol >= 2`. Patched btrfs-progs parses the TLV and applies ptime via file_setattr on receive. The attribute is emitted unconditionally on proto >= 2 (even for zero values) so incremental receive can distinguish "ptime unchanged from parent" from "ptime explicitly cleared."

**Permissions**: Setting ptime requires file ownership or CAP_FOWNER (same model as utimensat for atime/mtime). Tested in xfstests generic/803.

**Unsupported filesystems**: statx() returns 0 for ptime (STATX_PTIME not set in stx_mask). file_setattr with ptime on unsupported FS may succeed silently (the filesystem's setattr ignores the unknown ATTR_PTIME bit). tmpfs is a known example.

## What's Implemented

### Kernel Patches (16 commits, 28 files, 744 lines)

| Phase | # | Patch | Scope |
|-------|---|-------|-------|
| VFS | 1-3 | VFS ptime infrastructure | ATTR_PTIME bits, STATX_PTIME, file_attr VER1 extension, dual-dispatch |
| Btrfs | 4-8 | Full Btrfs ptime support | On-disk field, COMPAT_RO flag, delayed-inode, setattr/getattr, rename-over, tree-log |
| ntfs3 | 9-10 | Mapped ptime for NTFS | Maps to NTFS Date Created, rename-over |
| ext4 | 11-12 | Native ptime for ext4 | Dedicated i_ptime field, rename-over |
| FAT32 | 13 | Mapped ptime for FAT32 | Maps to creation time, rename-over |
| exFAT | 14 | Mapped ptime for exFAT | Maps to creation time, rename-over |
| **send/receive** | **15-16** | **Btrfs send/receive ptime** | **BTRFS_SEND_A_PTIME TLV emission in send_utimes(), gated on proto >= 2** |

### btrfs-progs Patches (5 commits)

| # | Patch | Scope |
|---|-------|-------|
| 1 | Mirror BTRFS_SEND_A_PTIME enum | kernel-shared/send.h (libbtrfs/send.h intentionally frozen) |
| 2 | Extend utimes callback | Nullable `struct timespec *pt` argument (NULL = absent, non-NULL = explicit) |
| 3 | Parse optional PTIME TLV | cmd_attrs[].data presence check in send-stream.c |
| 4 | Apply ptime via file_setattr | Dual syscall (utimensat + file_setattr 469), symlink-skip, ENOSYS soft-fail |
| 5 | Display ptime in --dump | Three render cases: absent / unset / timespec |

### Patched Userspace Tools

| Tool | Mechanism | Patch format |
|------|-----------|-------------|
| **coreutils** (cp, mv) | Raw statx (NR 332) + file_setattr (NR 469) syscalls | Python script |
| **KDE KIO** (Dolphin) | Same raw syscalls, Q_OS_LINUX guard | `.patch` file |
| **rsync** (--crtimes) | Added Linux backend to existing macOS/Cygwin crtimes infrastructure | Python script |
| **GNU tar** (--posix) | SCHILY.ptime PAX extended header, create + extract | Python script |
| **BorgBackup** | Cython statx/file_setattr via ctypes, ptime in archive metadata | Python script |
| **KDE Dolphin** | Properties dialog + sortable column + directory ptime | `.patch` file |

All patched packages protected from rolling updates via IgnorePkg in pacman.conf. The system-wide IgnorePkg list has 8 entries (includes one unrelated local patch; the ptime-relevant entries are: coreutils, kio, rsync, tar, dolphin, borg, btrfs-progs).

### KDE Dolphin GUI

- **Properties dialog**: "Provenance Time:" label for files/directories with ptime
- **Details view column**: Optional sortable "Provenance Time" column
- **Directory ptime**: Dolphin drag-and-drop preserves ptime on directories (copyjob.cpp fix)

### Backup Integration

- **btrbk**: Daily automated btrfs send/receive backups to external Btrfs partition with `send_protocol: 2`. Ptime preserved with full nanosecond precision across incremental snapshots.
- **BorgBackup**: Patched for ptime read/write. Borgmatic daily timer.
- **GNU tar**: Compressed `.tar.zst` archives with SCHILY.ptime PAX headers for NTFS-portable storage.
- **Snapper**: Hourly local Btrfs snapshots (ptime naturally preserved within Btrfs).

## Test Results

### Multi-Filesystem Runtime Tests (12/12 passing, 4 skipped USB)

Tested on USB drive with 4 partitions (ext4, exFAT, FAT32, Btrfs) plus NVMe root (Btrfs). All operations use patched coreutils:

| Test | ext4 | exFAT | FAT32 | Btrfs (USB) | Btrfs (NVMe) |
|------|------|-------|-------|-------------|--------------|
| Set + read ptime | PASS | PASS | PASS | PASS | PASS |
| Rename-over (atomic save) | PASS | PASS | PASS | PASS | PASS |
| cp -a preserves ptime | PASS | PASS | PASS | PASS | PASS |
| Truncate doesn't corrupt | PASS | PASS | PASS | PASS | PASS |
| Cross-FS: Btrfs NVMe to USB | PASS | PASS | PASS | PASS | -- |
| Cross-FS: USB to Btrfs NVMe | PASS | PASS | PASS | PASS | -- |

**NTFS**: Verified separately on internal NVMe NTFS partition -- set/read, rename-over, cp -a Btrfs-to-NTFS and NTFS-to-Btrfs, Dolphin GUI round-trips all confirmed working.

**Precision**: ext4 and Btrfs preserve full nanosecond precision. exFAT rounds to 10ms. FAT32 centisecond field provides ~10ms on-disk precision.

### Btrfs Send/Receive Tests (9 tests, all passing)

| Test | Description | Result |
|------|-------------|--------|
| Full send (proto 2) | A=1600000000, B=unset, C=1700000000 | PASS |
| Proto 1 regression | No ptime= in dump; proto 2 has ptime= | PASS |
| Incremental send -p | Updated/new/removed files, ptimes correct | PASS |
| **Explicit ptime clear** | A cleared from 2000000000 to 0 across incremental | **PASS** |
| Directory ptime | dir with ptime=1500000000 preserved | PASS |
| Symlink handling | Skipped with warning, targets unaffected | PASS |
| Rename-over + send | Atomic save ptime preserved through send/receive | PASS |
| Negative compat | Unpatched receiver rejects TLV 36 | PASS |
| Cross-device | NVMe source → USB SSD target, nsec precision | PASS |

The "explicit ptime clear" test is critical: it verifies that incremental receive correctly distinguishes "ptime unchanged from parent snapshot" (no UTIMES emitted) from "ptime explicitly cleared to zero" (UTIMES emitted with ptime=0). This required the sender to emit ptime unconditionally on proto >= 2, even for zero values.

### xfstests (10/10 passing)

| ID | Test | Scope |
|----|------|-------|
| generic/800 | Basic set/read ptime | VFS |
| generic/801 | Ptime survives unmount/remount | Persistence |
| generic/802 | Rename-over preserves ptime | Atomic save |
| generic/803 | Root-only ptime setting | Permissions |
| generic/804 | VER0-only file_setattr (ptime unchanged) | Size versioning |
| generic/805 | chmod doesn't corrupt ptime | setattr safety |
| generic/806 | truncate doesn't corrupt ptime | setattr safety |
| btrfs/350 | Ptime in Btrfs snapshots | Snapshot inheritance |
| btrfs/351 | Source nlink guard for rename-over | Hardlink safety |
| btrfs/352 | COMPAT_RO flag behavior | Feature flag |

## Known Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Btrfs COMPAT_RO flag | Once ptime is written to a Btrfs volume, unpatched kernels refuse read-write mount | Local deployment clears the compat_ro flag on mount, preserving three-kernel boot compatibility. LTS kernel as safety net. |
| XFS: deferred | No ptime on XFS | Out of current scope; XFS inode layout work would require separate analysis |
| ext4 128-byte inodes | ptime silently unavailable on legacy ext4 | Modern default is 256 bytes; EXT4_FITS_IN_INODE degrades gracefully |
| FAT32/exFAT precision | ~10ms granularity | Inherent to FAT/exFAT creation time fields; sufficient for provenance dates |
| Btrfs send/receive compat | Patched sender + unpatched receiver = hard failure (TLV type 36 rejected) | Use patched btrfs-progs on both sides; unpatched sender + patched receiver is backward compatible |
| tar -C flag + ptime | Patched tar's ptime statx doesn't respect -C flag | Workaround: `cd /target && tar -cf -` instead of `tar -C /target` |
| rsync precision | Seconds-only (no nsec) | Sufficient for provenance dates |
| glibc file_attr headers | System headers may not define VER1 struct with ptime fields | Tools use raw buffer+memcpy; glibc update will add native support |
| tmpfs | No ptime support | tmpfs has no persistent inode storage |
| Unpatched tools | Silent ptime loss with stock cp/rsync/tar | Deploy patched packages; IgnorePkg protects from rolling updates |
| Custom kernel maintenance | Periodic rebase on kernel updates | linux-ptime branch must be rebased manually on each new kernel release; LTS kernel provides safety fallback |
| NFS/CIFS/FUSE | Not tested | Network and FUSE filesystem support is out of initial scope |

## Build Instructions

### Apply Kernel Patches to Vanilla Kernel Tree

```bash
git clone --depth=1 --branch=v6.19.11 https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
cd linux
# Option A: monolithic patch
patch -Np1 < /path/to/patches/kernel/ptime-v6.1.patch

# Option B: individual commits (16 patches)
git am /path/to/patches/kernel/format-patches-v6.1/0*.patch

# Configure, build, install per your distribution's process
```

### Apply btrfs-progs Patches

```bash
git clone --branch=v6.19.1 https://github.com/kdave/btrfs-progs.git
cd btrfs-progs
patch -Np1 < /path/to/patches/btrfs-progs/btrfs-progs-ptime.patch
./autogen.sh && ./configure && make
sudo make install
```

### Arch Linux / EndeavourOS (PKGBUILD method)

```bash
# Kernel
pkgctl repo clone --protocol=https linux
cd linux
sed -i 's/^pkgbase=linux$/pkgbase=linux-ptime/' PKGBUILD
cp /path/to/patches/kernel/ptime-v6.1.patch .
# Add ptime-v6.1.patch to PKGBUILD source=() array; add 'SKIP' to checksums
makepkg -s
sudo pacman -U linux-ptime-*.pkg.tar.zst linux-ptime-headers-*.pkg.tar.zst
sudo grub-mkconfig -o /boot/grub/grub.cfg
```

Same PKGBUILD clone-and-patch approach for btrfs-progs and each userspace tool. Add patched packages to `IgnorePkg` in `/etc/pacman.conf` to prevent overwrite on system update.

### Recommended: Three-Kernel Strategy

linux-lts (safety net) + linux (mainline, rolls normally) + linux-ptime (custom, manual updates). GRUB offers all three at boot. linux-ptime updates only on rebuild; others roll via pacman -Syu.

### btrbk Configuration

After installing the patched kernel and btrfs-progs, configure btrbk with:

```
send_protocol  2
```

This is **required** for ptime preservation. The default (`send_protocol 1`) omits the BTRFS_SEND_A_PTIME TLV entirely.

## Development

Developed using AI-assisted tooling (multi-agent framework) for implementation, iterative code review, and testing infrastructure. Multiple independent review rounds identified and fixed critical bugs before each phase. Human maintainer is responsible for review, testing, sign-off, and follow-up.

Kernel 6.19.11, EndeavourOS, AMD Ryzen 9 9900X, Samsung 9100 PRO NVMe.

## Repository Structure

```
linux-ptime/
├── README.md
├── LICENSE                                    # GPL-2.0
├── patches/
│   ├── kernel/
│   │   ├── ptime-v6.1.patch                  # Monolithic (16 commits, 744 lines)
│   │   ├── ptime-v6.patch                    # Prior version (14 commits, 648 lines)
│   │   ├── ptime-kernel-v5-full.patch         # Historical v5
│   │   ├── format-patches-v6.1/              # 16 individual git format-patches (current)
│   │   ├── format-patches-v6-rfc/            # 6-commit RFC v2 candidate (never submitted)
│   │   └── format-patches-v5-rfc/            # 6-commit RFC v1 (submitted to LKML)
│   ├── btrfs-progs/
│   │   └── btrfs-progs-ptime.patch           # 5 commits: send/receive ptime
│   ├── coreutils/
│   │   └── patch-cp-v2.py                    # cp ptime preservation (Python script)
│   ├── rsync/
│   │   └── patch-rsync-v2.py                 # rsync --crtimes Linux backend
│   ├── tar/
│   │   └── patch-tar.py                      # SCHILY.ptime PAX header
│   ├── kio/
│   │   └── kio-ptime.patch                   # KDE KIO ptime support
│   ├── dolphin/
│   │   └── dolphin-ptime.patch               # Dolphin ptime column + properties
│   └── borg/
│       └── patch-borg-ptime.py               # BorgBackup ptime backup/restore
├── spec/
│   ├── kernel-ptime-spec-v6.md               # Current specification
│   └── kernel-ptime-spec-v5.md               # Historical
├── tests/
│   ├── xfstests/                             # 10 xfstests (7 generic + 3 btrfs)
│   │   ├── src/ptime_set.c, ptime_get.c
│   │   ├── common/ptime
│   │   ├── generic/800-806
│   │   └── btrfs/350-352
│   ├── ptime-test-suite.sh
│   └── ptime-adversarial-tests.sh
└── tools/
    ├── README.md
    ├── ptime-read.c                          # Human-readable ptime display
    ├── ptime-set-simple.c                    # Simple ptime setter
    ├── ptime-atomic-test.c                   # Rename-over verification
    └── ptime-ntfs-test.c                     # NTFS mapping verification
```

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v1.0 | 2026-04-05 | Initial release: 5 FS, utimensat API, xfstests, 4 tool patches |
| v2.0 | 2026-04-07 | file_setattr API migration (per Wong suggestion), KDE Dolphin GUI |
| **v2.1** | **2026-04-09** | **Btrfs send/receive ptime (16 kernel commits + 5 btrfs-progs commits), BorgBackup patch, btrbk integration, tar archive automation** |

## License

Kernel patches: GPL-2.0-only (matching Linux kernel)
btrfs-progs patches: GPL-2.0-only (matching btrfs-progs)
coreutils/tar patches: GPL-3.0-or-later (matching upstream)
rsync patches: GPL-3.0-or-later (matching upstream)
BorgBackup patches: BSD-3-Clause (matching upstream)
KDE KIO/Dolphin patches: LGPL-2.0-or-later (matching upstream)
