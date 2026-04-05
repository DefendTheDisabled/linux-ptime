# provenance_time (ptime) -- Linux Kernel Patch

A new settable inode timestamp for the Linux kernel that preserves file provenance (original creation dates) across copies, moves, application saves, and filesystem transitions.

**Status**: Running on EndeavourOS (Arch), kernel 6.19.11. 5 filesystems (Btrfs, ext4, ntfs3, FAT32, exFAT), 4 patched userspace tools, KDE Dolphin GUI integration. All runtime tests passing.

**RFC**: [Proposal on linux-fsdevel](https://lore.kernel.org/linux-fsdevel/CAOx6djP4hb-Cd1Zk07SNfFfLc8irjNmbVqq+58h1Whz+h1wSFA@mail.gmail.com/T/#u) (March 2026)

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
| **Sandoval's AT_UTIME_BTIME (2019)** | ptime uses the same utimensat extension pattern but targets a new field, sidestepping the btime mutability dispute entirely |
| **Ts'o's btime/crtime split (March 2025)** | ext4 ptime implements his concept -- dedicated i_ptime alongside immutable i_crtime. "crtime which *can* be changed by a system call interface." |
| **Chinner's forensic btime objection (2019)** | ptime is a separate field on native filesystems -- btime remains immutable; no forensic semantics are changed |
| **Sterba's Btrfs otime / send v2** | ptime infrastructure serves the settable-timestamp need for send/receive |
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
| **Mapped** | ntfs3, FAT32, exFAT | ptime reads/writes the existing creation time field | Creation time becomes settable (matches Windows/macOS behavior) |

Linux-native filesystems preserve forensic btime alongside the settable ptime. Bridge filesystems (NTFS, FAT) already treat creation time as mutable on Windows and macOS; Linux gains parity.

## Use Case

This patch was created to solve a concrete problem: preserving document creation dates during migration between Windows (NTFS) and Linux (Btrfs). Workflows involving legal, archival, and forensic documents require provenance metadata to survive filesystem transitions. The ptime field carries original creation dates through any supported filesystem, tool, or application save operation.

## API Design

**Setting ptime**: The current implementation extends utimensat() with a third element in the times[] array, gated by the AT_UTIME_PTIME flag (0x20000). Userspace tools use raw syscall() since glibc's utimensat() wrapper only passes two timespec values.

For upstream, a new extensible-struct syscall (utimensat2, following the clone3/openat2 pattern) is the preferred long-term approach. The utimensat extension is used here to demonstrate and validate the VFS semantics with minimal kernel surface change.

**Reading ptime**: statx() returns ptime via STATX_PTIME (0x00040000U) in the stx_ptime field.

**Permissions**: Setting ptime requires file ownership or CAP_FOWNER (same model as utimensat for atime/mtime). Tested in xfstests generic/803.

**Unsupported filesystems**: statx() returns 0 for ptime (STATX_PTIME not set in stx_mask). utimensat with AT_UTIME_PTIME returns -EOPNOTSUPP or is silently ignored depending on the filesystem's setattr implementation.

## What's Implemented

### Kernel Patches (6 commits, 27 files, +239/-26 lines)

| # | Patch | Scope |
|---|-------|-------|
| 1 | VFS: ptime infrastructure | ATTR_PTIME (bit 19/20), STATX_PTIME, AT_UTIME_PTIME, ia_ptime in iattr, ptime in kstat, utimensat extension, setattr_prepare |
| 2 | Btrfs: full ptime support | New field in reserved inode space, delayed-inode read/write, tree-log preservation, rename-over (zero-sentinel), new inode init |
| 3 | ntfs3: mapped ptime | ptime maps to NTFS Date Created ($STANDARD_INFORMATION cr_time), rename-over |
| 4 | ext4: native ptime | Dedicated i_ptime + i_ptime_extra in extended inode area (alongside immutable i_crtime), rename-over, EXT4_FITS_IN_INODE graceful degradation |
| 5 | FAT32 (vfat): mapped ptime | ptime maps to FAT creation time, rename-over |
| 6 | exFAT: mapped ptime | ptime maps to exFAT creation time, rename-over |

Note: The Arch Linux PKGBUILD version is 717 lines / 28 files. The extra file (disk-io.c) contains local-deployment code that clears a Btrfs compat_ro flag on mount to maintain three-kernel boot compatibility. This is excluded from the upstream submission.

### Patched Userspace Tools

| Tool | Mechanism |
|------|-----------|
| **coreutils** (cp, mv) | Raw statx + utimensat syscalls (x86_64: NR 332, 280) |
| **KDE KIO** (Dolphin) | Same raw syscalls, Q_OS_LINUX guard |
| **rsync** (--crtimes) | Added Linux backend to existing macOS/Cygwin crtimes infrastructure |
| **GNU tar** (--posix) | SCHILY.ptime PAX extended header, create + extract |

All patched packages protected from rolling updates via IgnorePkg in pacman.conf.

### KDE Dolphin GUI

- **Properties dialog**: "Provenance Time:" label for files/directories with ptime
- **Details view column**: Optional sortable "Provenance Time" column
- **Directory ptime**: Dolphin drag-and-drop preserves ptime on directories (copyjob.cpp fix)

### Userspace Utilities

- ptime_set, ptime_get -- Raw syscall set/read (test helpers and xfstests infrastructure)
- ptime-read -- Human-readable ptime display
- ptime-atomic-test -- Rename-over verification
- ptime-ntfs-test -- NTFS Date Created mapping verification

## Test Results

### Multi-Filesystem Runtime Tests (24/24 passing)

Tested on USB drive with 4 partitions (ext4, exFAT, FAT32, Btrfs) plus NVMe root (Btrfs). All operations use patched coreutils:

| Test | ext4 | exFAT | FAT32 | Btrfs (USB) | Btrfs (NVMe) |
|------|------|-------|-------|-------------|--------------|
| Set + read ptime | PASS | PASS | PASS | PASS | PASS |
| Rename-over (atomic save) | PASS | PASS | PASS | PASS | PASS |
| cp -a preserves ptime | PASS | PASS | PASS | PASS | PASS |
| Truncate doesn't corrupt | PASS | PASS | PASS | PASS | PASS |
| Cross-FS: Btrfs NVMe to USB | PASS | PASS | PASS | PASS | -- |
| Cross-FS: USB to Btrfs NVMe | PASS | PASS | PASS | PASS | -- |

**NTFS**: Verified separately on internal NVMe NTFS partition -- set/read, rename-over, cp -a Btrfs-to-NTFS and NTFS-to-Btrfs, Dolphin GUI round-trips all confirmed working. NTFS tests use ptime-ntfs-test utility.

**Precision**: ext4 and Btrfs preserve full nanosecond precision. exFAT rounds to 10ms. FAT32 centisecond field provides ~10ms on-disk precision.

### xfstests (10/10 passing)

| ID | Test | Scope |
|----|------|-------|
| generic/800 | Basic set/read ptime | VFS |
| generic/801 | Ptime survives unmount/remount | Persistence |
| generic/802 | Rename-over preserves ptime | Atomic save |
| generic/803 | Root-only ptime setting | Permissions |
| generic/804 | Omitting ptime in utimensat | UTIME_OMIT |
| generic/805 | chmod doesn't corrupt ptime | setattr safety |
| generic/806 | truncate doesn't corrupt ptime | setattr safety |
| btrfs/350 | Ptime in Btrfs snapshots | Snapshot inheritance |
| btrfs/351 | Source nlink guard for rename-over | Hardlink safety |
| btrfs/352 | COMPAT_RO flag behavior | Feature flag |

Tests run against the 28-file PKGBUILD variant (includes local compat_ro clearing). The 27-file upstream patch set is functionally identical for all test paths except btrfs/352.

## Known Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Btrfs COMPAT_RO flag | Once ptime is written to a Btrfs volume, unpatched kernels refuse read-write mount | Correct compat_ro behavior per Btrfs convention; LTS kernel as safety net (noatime prevents ptime writes). Local deployment clears flag on mount for three-kernel compatibility. |
| XFS: deferred | No ptime on XFS | Deferred to post-initial-acceptance; XFS inode structure requires separate analysis |
| ext4 128-byte inodes | ptime silently unavailable on legacy ext4 | Modern default is 256 bytes; EXT4_FITS_IN_INODE degrades gracefully (same behavior as i_crtime) |
| FAT32/exFAT precision | ~10ms granularity | Inherent to FAT/exFAT creation time fields; sufficient for provenance dates |
| Btrfs send/receive | Not yet patched for ptime | Use rsync --crtimes for remote backup |
| tar pipe extraction | ptime lost through pipe | Use file-based tar extraction |
| rsync precision | Seconds-only (no nsec) | Sufficient for provenance dates |
| glibc utimensat wrapper | Cannot pass ptime | Tools use raw syscall(); utimensat2 or glibc update for upstream |
| tmpfs | No ptime support | tmpfs has no persistent inode storage |
| Unpatched tools | Silent ptime loss with stock cp/rsync/tar | Deploy patched packages; IgnorePkg protects from rolling updates |
| NFS/CIFS/FUSE | Not tested | Network and FUSE filesystem support is out of initial scope |
| Custom kernel maintenance | Periodic rebase | Upstream patch is +239/-26 lines; LTS kernel as fallback |

## Build Instructions

### Apply to Vanilla Kernel Tree

```
git clone --depth=1 --branch=v6.19.11 https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
cd linux
git am kernel/patches/000[1-6]-*.patch
# Configure, build, install per your distribution's process
```

### Arch Linux / EndeavourOS (PKGBUILD method)

```
pkgctl repo clone --protocol=https linux
cd linux
sed -i 's/^pkgbase=linux$/pkgbase=linux-ptime/' PKGBUILD
cp /path/to/ptime-kernel-v5-full.patch .
# Add ptime-kernel-v5-full.patch to PKGBUILD source=() array
# Add 'SKIP' to sha256sums=() array for the new entry
makepkg -s
sudo pacman -U linux-ptime-*.pkg.tar.zst linux-ptime-headers-*.pkg.tar.zst
sudo grub-mkconfig -o /boot/grub/grub.cfg
```

### Recommended: Three-Kernel Strategy

linux-lts (safety net) + linux (mainline, rolls normally) + linux-ptime (custom, manual updates). GRUB offers all three at boot. linux-ptime updates only on rebuild; others roll via pacman -Syu.

### Patched Tools

Same PKGBUILD clone-and-patch approach for each tool. Patch details in tools/ directory.

## Development

Developed using AI-assisted tooling (multi-agent framework) for implementation, iterative code review, and testing infrastructure. 5 independent review rounds identified and fixed 6 bugs before convergence. Human maintainer is responsible for review, testing, sign-off, and follow-up.

Kernel 6.19.11, EndeavourOS, AMD Ryzen 9 9900X, Samsung 9100 PRO NVMe.

## Repository Structure

```
ptime-submission/
+-- README.md
+-- kernel/
|   +-- patches/                    # git format-patch v5 (6 commits)
|   +-- ptime-kernel-v5-full.patch  # Combined patch
+-- spec/
|   +-- kernel-ptime-spec-v5.md     # Technical specification
+-- tests/
|   +-- xfstests/                   # 10 xfstests (7 generic + 3 btrfs)
|   +-- ptime-test-suite.sh
|   +-- ptime-adversarial-tests.sh
+-- tools/
|   +-- README.md                   # Tool patch descriptions
+-- userspace/
    +-- ptime_set.c, ptime_get.c
    +-- ptime-read.c
    +-- ptime-atomic-test.c
    +-- ptime-ntfs-test.c
```

## License

Kernel patches: GPL-2.0-only (matching Linux kernel)
Userspace tools: GPL-3.0-or-later
