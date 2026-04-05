# SPEC: Kernel provenance_time (ptime)
Author: Principal-Opus 2026-04-04
Edited by: Principal-Partner 2026-04-05
Reviewed by: Principal-Opus 2026-04-05 (cross-checked against verified implementation)
Status: v5 — Native/mapped architecture. ext4 separate ptime field. Rename-over on all 5 FS.

---

## Changelog

- **v1**: Initial spec. Btrfs-only. Overclaimed tool support as automatic.
- **v2**: Added ntfs3 mapping, ext4/f2fs support, tool patches as core deliverables, operational details. Honest "what works" table.
- **v3**: Fixed utimensat ABI (raw syscall for tools, note glibc limitation). Fixed ntfs3 write path (must build, not just setattr branch). Fixed ATTR bits (19/20). Resolved statx presence semantics. Aligned ext4 with Ts'o's Path A (reuse crtime). Consolidated VFS patches. Added btrfs-progs, coreutils stat, man-pages to deliverables. Expanded testing (crash recovery, concurrency, xfstests, RAID). Added rename-over helper function. Addressed ntfs3 btime/ptime semantic tension. Added forensic considerations and Kbase integration note.
- **v4**: Corrected AT_UTIME_PTIME to 0x20000 (was 0x10000 in v3 — implementation uses 0x20000 to avoid AT_EXECVE_CHECK overlap). Added FAT32/vfat and exFAT to filesystem implementations (were listed as "not feasible" in v2 — actually feasible by mapping to existing creation time fields). Corrected reflink claim from "Kernel only (COW)" to "coreutils patch (tool-level, not kernel-level)." Added Btrfs tree-log ptime write (found missing in audit R3). Added COMPAT_RO_PTIME flag (implemented then disabled locally — blocks LTS boot). Added Btrfs delayed-inode ptime path (was the persistence bug). Documented noatime as LTS fallback protection. Added known edge limitations: ext4 128-byte inode silent-drop, FAT32 precision truncation, tar basename resolution, rsync seconds-only precision. 5 audit rounds converged.
- **v5**: **Major architecture revision — native/mapped split.**
  - Two categories of ptime implementation: **native** (Btrfs, ext4 — separate ptime field, btime immutable) and **mapped** (ntfs3, FAT32/vfat, exFAT — ptime maps to existing creation time field).
  - **ext4 redesigned**: No longer reuses i_crtime (Ts'o Path A). New separate `i_ptime` (4 bytes) + `i_ptime_extra` (4 bytes) in ext4 extended inode area. i_crtime remains immutable btime. Requires 256+ byte inodes; graceful degradation on 128-byte inodes via `EXT4_FITS_IN_INODE`.
  - **Rename-over extended to all 5 filesystems**: Btrfs and ext4 use ptime-zero sentinel logic (native). ntfs3, FAT32, exFAT save/restore i_crtime across rename (mapped — replicates Windows behavior).
  - **FAT32/vfat and exFAT**: Full filesystem implementation sections added (were missing from v4 spec). Mapped ptime reads/writes existing creation time. FAT32: 2-second precision. exFAT: 10ms precision.
  - New Section 4.5: Native vs Mapped Architecture — explains the two-category design rationale and upstream argument.
  - Updated patch series: ext4 patch larger (new field). Rename-over logic included in each filesystem's patch (not separate patches). Total kernel patches: 6.
  - Removed Open Question Q7 (AT_UTIME_PTIME value confirmed as 0x20000). Added ext4 feature flag coordination question.
  - Updated Known Limitations: exFAT is implemented (mapped), not "not feasible." FAT32/exFAT precision documented as trade-off.

---

## 1. Overview

provenance_time (ptime) is a new inode timestamp for the Linux kernel. It records when a file's content first came into existence — its original creation date — and survives across copies, moves, saves, and filesystem transitions. Unlike btime (forensic, immutable, reset on every copy), ptime is settable and designed to travel with the file.

### 1.1 Why Not xattr

An xattr approach (`user.provenance_time`) was designed, implemented, and comprehensively reviewed. Fundamental fragility was identified:

1. **Application atomic saves destroy xattrs.** Most applications (LibreOffice, Vim, Kate) save via write-to-temp + rename(). The rename replaces the inode, destroying all xattrs. No userspace fix exists.
2. **Every tool must explicitly opt in.** `cp` needs `--preserve=xattr`, `rsync` needs `-X`, `tar` needs `--xattrs`. Each missing flag is silent data loss.
3. **KDE has bugs that silently drop xattrs.** KIO aborts NTFS→Btrfs xattr copies (Bug #418225). Ark doesn't restore xattrs on extraction (Bug #435001).

### 1.2 What the Kernel Provides

| Capability | How |
|---|---|
| **Atomic save survival** | Filesystem rename handler preserves ptime across rename-over — on ALL 5 supported filesystems (Btrfs, ext4, ntfs3, FAT32, exFAT) |
| **On-disk persistence** | ptime stored in filesystem-specific inode structures, survives reboots and crashes |
| **Standard API** | statx() to read, utimensat() to write — same pattern as mtime/atime |
| **Native ptime (Btrfs, ext4)** | Separate ptime field alongside btime/crtime — forensic btime immutability preserved |
| **Mapped ptime (ntfs3, FAT32, exFAT)** | ptime maps to existing creation time field — bridge filesystems where host OS treats creation time as mutable |

### 1.3 What Requires Tool Patches

Adding a new kernel timestamp does NOT cause existing tools to automatically preserve it. Each copy tool hardcodes which timestamps it reads and writes (typically atime + mtime only). Tool patches are required and are core deliverables of this project:

| Tool | Patch | Estimated Size |
|---|---|---|
| cp (coreutils) | Add statx PTIME read + utimensat write | ~30 lines |
| stat (coreutils) | Display ptime in output | ~20 lines |
| Dolphin/KIO | Add ptime to copy timestamp path | ~30 lines |
| rsync | Add ptime to timestamp sync | ~30 lines |
| tar | Add SCHILY.ptime PAX header | ~40 lines |
| btrfs-progs | Decode ptime in dump-tree | ~20 lines |

**Why tools don't auto-detect**: glibc's `utimensat()` wrapper declares `const struct timespec times[2]` — a fixed 2-element array. You can't pass a 3rd element through the standard C library function. Tool patches call `syscall(SYS_utimensat, ...)` directly with a 3-element array and the `AT_UTIME_PTIME` flag. This bypasses the glibc wrapper. For upstream tool adoption, either glibc updates its wrapper or a new `utimensat2()` syscall is introduced. For our local deployment, raw syscall works fine.

### 1.4 What "Just Works" After Full Deployment

Once kernel patches + tool patches are deployed:

| User action | ptime behavior | What makes it work |
|---|---|---|
| Copy files in Dolphin (any direction, any FS) | ptime preserved | KIO patch (reads/writes ptime via syscall) |
| Move files in Dolphin (same FS) | ptime preserved | Kernel — same inode, no timestamp operation |
| Move files across filesystems | ptime preserved | KIO patch (cross-FS move = copy+delete) |
| Save document in LibreOffice/Vim/Kate | **ptime preserved** | **Kernel rename-over** — the key win |
| Terminal `cp -a` | ptime preserved | coreutils patch |
| Terminal `stat` | ptime displayed | coreutils stat patch |
| `rsync -a` | ptime preserved | rsync patch |
| Archive with tar | ptime stored | tar patch (SCHILY.ptime PAX header) |
| Btrfs snapshots | ptime preserved | Kernel — COW preserves all inode fields |
| Btrfs reflink (`cp --reflink`) | ptime preserved | Kernel — COW, same inode data |
| Copy from NTFS to Btrfs | NTFS Date Created → Btrfs ptime | ntfs3 patch + cp/KIO patch |
| Copy from Btrfs to NTFS | Btrfs ptime → NTFS Date Created | ntfs3 patch + cp/KIO patch |
| Copy from/to FAT32 or exFAT | Creation time ↔ ptime | FAT/exFAT patch + cp/KIO patch |
| View Date Created in Windows Explorer | Shows correct date | ntfs3/FAT/exFAT writes creation time natively |

### 1.5 Known Limitations

| Limitation | Why | Mitigation |
|---|---|---|
| XFS: deferred | Maintainer resistance, rigid format | Add after upstream concept acceptance |
| tmpfs: volatile | In-memory only, ptime meaningless | Not applicable |
| FAT32: 2-second precision | FAT32 creation time field uses 2-second granularity (DOS heritage) | Documented trade-off; sub-second precision lost on FAT32 |
| exFAT: 10ms precision | exFAT timestamps have 10ms granularity | Documented trade-off; nanosecond precision lost on exFAT |
| Mapped FS: ptime conflated with creation time | ntfs3, FAT32, exFAT use same on-disk field for both ptime and creation time | Documented trade-off. Host OS treats creation time as mutable — no forensic integrity to protect. See §4.5. |
| scp/sftp | Wire protocol doesn't carry ptime | Use rsync instead |
| Cloud sync (Syncthing, Dropbox) | Proprietary protocols | Document as known limitation |
| Browser downloads | New file, correct btime, ptime=0 | Expected — no provenance to preserve |
| Backup-via-rename editors | Vim (`backupcopy=no`), Emacs rename original→.bak then create new | Configure editors: Vim `set backupcopy=yes` |
| Python os.stat() / shutil.copy2 | No ptime exposure until CPython patched | Use ptime-set/ptime-stat CLI, or ctypes |
| Rust std::fs::metadata | No ptime exposure until Rust std patched | Use raw syscall via libc crate |
| Unpatched cp/rsync/tar | Silently drops ptime | Deploy patched packages; ptime-doctor warns |

---

## 2. Definitions

| Term | Meaning |
|------|---------|
| **ptime** | Provenance time. Settable inode timestamp recording original creation date of file content. Survives copies, moves, renames. Stored in filesystem-specific inode structures. |
| **btime** | Birth time. When this inode was created on THIS filesystem. Immutable. Reset on every copy. Forensic metadata. |
| **otime** | Btrfs's name for btime. Stored in `btrfs_inode_item.otime`. Reported via statx as `stx_btime`. |
| **crtime** | ext4's name for btime. Stored on-disk as `i_crtime` + `i_crtime_extra`. Immutable — remains forensic btime even with ptime support. |
| **native ptime** | Implementation where ptime is a separate on-disk field alongside btime/crtime. Used by Btrfs and ext4. Forensic btime preserved. |
| **mapped ptime** | Implementation where ptime maps to the existing creation time field. Used by ntfs3, FAT32/vfat, exFAT. Setting ptime overwrites creation time. |
| **atomic save** | Application save: write to temp → rename() over original. Replaces inode. Kernel ptime survives via rename-over. |
| **rename-over** | When `rename(A, B)` replaces an existing file B with file A. B's inode is destroyed; A's inode takes B's path. |

---

## 3. Semantic Model

### 3.1 What ptime Represents

ptime answers: **"When was this file's content first created, on any filesystem, as reported by the earliest known source?"**

```
atime  — access time
mtime  — modification time
ctime  — change time (metadata)
btime  — birth time (inode, forensic, immutable)
ptime  — provenance time (content origin, settable, travels with file)
```

### 3.2 Lifecycle

| Event | ptime behavior |
|---|---|
| File created (new document) | ptime = 0 (unset). btime is the true creation date. |
| ptime set explicitly (migration tool) | ptime = specified value. |
| File copied (with patched tool) | Tool reads source ptime via statx, writes to dest via utimensat. |
| File renamed within same FS | Same inode. ptime unchanged. |
| **File renamed over existing file (atomic save)** | **Kernel preserves ptime. See §3.3.** |
| File content modified in-place | ptime unchanged. mtime updates. |
| Btrfs snapshot / reflink | ptime preserved (COW). |
| Copy from NTFS/FAT32/exFAT | Creation time → ptime on destination. |
| Copy to NTFS/FAT32/exFAT | ptime → creation time (Date Created). |

### 3.3 Rename-Over Preservation

When `rename(source, target)` replaces an existing file:
- `source` = new file (e.g., temp file from atomic save) — typically has no ptime/provenance set
- `target` = old file being replaced — may have ptime or creation time set

The rename-over mechanism varies by filesystem category but shares common guards.

#### Common Guards

All rename-over ptime preservation checks these conditions inline (each filesystem's rename handler):
- Both source and target are regular files (`S_ISREG`)
- Source has `nlink == 1` (prevents ptime mutation propagating to other hardlinks)
- Not RENAME_EXCHANGE (swap preserves both inodes — ptime stays with its inode)
- Not RENAME_WHITEOUT
- Implemented within the filesystem's rename transaction — atomic with the rename itself

#### Native Filesystems (Btrfs, ext4): ptime-Zero Sentinel

These filesystems have a dedicated ptime field. The rule:

**If source ptime is zero (both `tv_sec == 0 AND tv_nsec == 0`) and target ptime is non-zero, copy target's ptime to source before destroying target's inode. If source already has non-zero ptime, keep source's ptime.**

Each filesystem checks its own ptime fields (since ptime is stored in filesystem-specific structs, not VFS struct inode). For ext4:

```c
/* In ext4_rename(), after S_ISREG/nlink/flags guards */
struct ext4_inode_info *old_ei = EXT4_I(old.inode);
struct ext4_inode_info *new_ei = EXT4_I(new.inode);
if (!old_ei->i_ptime.tv_sec && !old_ei->i_ptime.tv_nsec &&
    (new_ei->i_ptime.tv_sec || new_ei->i_ptime.tv_nsec))
    old_ei->i_ptime = new_ei->i_ptime;
```

Btrfs uses the same logic but with `i_ptime_sec`/`i_ptime_nsec` fields (see §5.1).

#### Mapped Filesystems (ntfs3, FAT32/vfat, exFAT): Save/Restore i_crtime

These filesystems have no separate ptime field — ptime IS the creation time. The rename-over mechanism saves the target's creation time before the target inode is destroyed, then applies it to the source inode after the rename completes.

**Pattern**:
1. Before target inode destruction: save `target->i_crtime` to a local variable
2. Complete the rename (target inode destroyed, source inode takes target's path)
3. Apply saved creation time to source inode: `source->i_crtime = saved_crtime`

```c
/* In ntfs3/fat/exfat rename handler */
struct timespec64 saved_crtime = {};
bool inherit_crtime = false;

if (new_inode && S_ISREG(old_inode->i_mode) &&
    S_ISREG(new_inode->i_mode) && old_inode->i_nlink == 1) {
    saved_crtime = FS_I(new_inode)->i_crtime;
    inherit_crtime = true;
}

/* ... perform rename ... */

if (inherit_crtime)
    FS_I(old_inode)->i_crtime = saved_crtime;
```

**Unconditional save/restore**: On mapped filesystems, creation time is always non-zero. The save/restore is unconditional — if the target existed and guards pass, inherit its creation time. This is simpler than timestamp comparison and matches Windows behavior (creation time always transfers on rename-over).

**This replicates Windows behavior**: Windows NTFS preserves creation time across atomic saves. Applications using `MoveFileEx(MOVEFILE_REPLACE_EXISTING)` cause the same pattern — the replaced file's creation time transfers to the replacement. Linux ntfs3 matching this behavior is functionally correct for NTFS semantics.

#### Known Heuristic Limitation

Optimized for atomic saves. For unrelated file overwrites (`mv newfile existingfile`), could incorrectly stamp newfile with existingfile's ptime/crtime. The nlink=1 guard plus ptime-zero (native) / timestamp-comparison (mapped) checks minimize this. Acknowledged as acceptable — the atomic save path is the critical use case.

**Backup-via-rename editors**: Vim (`backupcopy=no`), Emacs rename original→.bak then create new file. No rename-over occurs; ptime stays on .bak. Fix: configure `set backupcopy=yes` in Vim.

### 3.4 Timestamp Format

Kernel: `struct timespec64` (seconds + nanoseconds since epoch).
Btrfs on-disk: `struct btrfs_timespec` = `{__le64 sec; __le32 nsec}` = 12 bytes.
ext4 on-disk: `__le32 i_ptime` + `__le32 i_ptime_extra` = 8 bytes with encoded nanoseconds.
NTFS on-disk: 64-bit 100ns intervals since 1601 (NTFS FILETIME, converted by ntfs3 driver).
FAT32 on-disk: 16-bit date + 16-bit time = 2-second precision. Creation time adds 1-byte centiseconds (10ms).
exFAT on-disk: 32-bit timestamp + 1-byte 10ms increment + 1-byte UTC offset.

### 3.5 Presence Semantics

ptime is "unset" when both `tv_sec == 0` and `tv_nsec == 0`. This makes epoch zero (1970-01-01T00:00:00.000000000Z) unrepresentable. No litigation documents predate 1970.

**statx reporting**: When filesystem supports ptime AND ptime is non-zero, set `STATX_PTIME` in `stx_result_mask` and fill `stx_ptime`. When ptime is zero (unset), do NOT set `STATX_PTIME` in `result_mask`. This lets userspace distinguish "filesystem doesn't support ptime" from "ptime not yet set" from "ptime is set."

**Mapped filesystem note**: On ntfs3, FAT32, and exFAT, the creation time field is always non-zero (set at file creation). When reading ptime from a mapped filesystem, it always appears "set" — the creation time IS the ptime. This is semantically correct: files on these filesystems always have a provenance timestamp (their creation time).

### 3.6 Permission Model

Same as mtime setting via utimensat():
- Setting to current time: write access, or owner, or CAP_FOWNER
- Setting to arbitrary value: owner or CAP_FOWNER

ptime is user-settable metadata, not forensic evidence. Any file owner can set it. This is identical to mtime, which is also freely settable and used in legal contexts.

### 3.7 Forensic Considerations

ptime is settable — any file owner can set it to any value. It must not be treated as forensic proof without corroborating evidence. For litigation:
- **Evidentiary originals**: Keep on NTFS partition. Windows Date Created is standard, legally defensible, set by standard APIs.
- **Working copies on Btrfs**: ptime provides convenient access to creation dates for agent-assisted document management.
- **Chain of custody**: Maintain metadata manifests and NTFS backups as authoritative reference.
- **Kbase integration**: When ingesting documents into knowledge base (PostgreSQL), capture ptime as a structured database field at ingest time. The database becomes the authoritative source — filesystem ptime is convenient but not the sole record.

### 3.8 Relationship to Existing Proposals

| Proposal | Relationship |
|---|---|
| Sandoval's AT_UTIME_BTIME (2019) | ptime uses the same utimensat extension pattern for a NEW field. Avoids btime mutability dispute. |
| Ts'o's btime/crtime split (March 2025) | **ptime IS Ts'o's "crtime" concept with clearer naming.** ext4 implements his vision — with dedicated fields rather than crtime reuse, giving both forensic btime and settable ptime their own space. |
| Sterba's Btrfs otime / send v2 | ptime infrastructure directly serves Sterba's send/receive use case. |
| Chinner's forensic btime position | ptime preserves btime immutability. Different field, different semantics. |
| Boaz Harrosh's 2019 "Author creation time" | ptime formalizes Harrosh's concept of a globally-carried author creation time vs. local filesystem creation time. |

---

## 4. Kernel Architecture

### 4.1 Design Principle: Filesystem-Specific Storage

ptime is stored in **filesystem-specific inode structures** (e.g., `struct btrfs_inode`, `struct ext4_inode_info`), NOT in VFS `struct inode`. This avoids adding 16 bytes to every in-memory inode across all filesystems — the primary VFS maintainer objection.

The VFS layer provides:
- `ATTR_PTIME` (bit 19) / `ATTR_PTIME_SET` (bit 20) in `struct iattr`
- `STATX_PTIME` (`0x00040000U`) in `struct statx`
- `AT_UTIME_PTIME` flag for utimensat()
- Rename-over guard logic (inlined per-filesystem; see §4.2)

Each filesystem implements ptime storage in its own `.setattr` and `.getattr` handlers.

### 4.2 VFS Layer Changes

**`include/linux/fs.h`**:
```c
#define ATTR_PTIME      (1 << 19)
#define ATTR_PTIME_SET  (1 << 20)
/* FS_HAS_PTIME not implemented — deferred to upstream coordination */

struct iattr {
    /* ... existing fields ... */
    struct timespec64   ia_ptime;
};
```

**`fs/attr.c`**: Handle ATTR_PTIME in `setattr_prepare()` (permission validation) and delegate to filesystem `.setattr`.

**Rename-over guards**: Each filesystem's rename handler checks `S_ISREG`, `nlink == 1`, and `!RENAME_EXCHANGE/WHITEOUT` inline — no shared helper function. This avoids adding a new header for a 3-line check that varies slightly per filesystem (native FS check ptime-zero; mapped FS unconditionally save/restore).

### 4.3 utimensat Extension

**`include/uapi/linux/fcntl.h`**:
```c
#define AT_UTIME_PTIME  0x20000
```

Note: `0x10000` is also used by `AT_EXECVE_CHECK`, but AT_* flags are per-syscall — reuse is acceptable. The spec should document this is valid for utimensat/utimensat_time32 only.

**`fs/utimes.c`**: When `AT_UTIME_PTIME` is set:
1. Read `times[2]` from userspace (3rd element of the array)
2. Handle `UTIME_NOW`: set ptime to current time
3. Handle `UTIME_OMIT`: leave ptime unchanged
4. Construct `iattr` with `ATTR_PTIME | ATTR_PTIME_SET`
5. Both native and compat (32-bit) syscall paths must be updated

Backward compatibility: old kernels reject unknown AT_* flags with `EINVAL`. Old userspace never sets `AT_UTIME_PTIME`, so `times[2]` is never read.

**glibc limitation**: glibc's `utimensat()` wrapper declares `times[2]`. Callers needing ptime must use `syscall(SYS_utimensat, ...)` directly with a 3-element array. This is acceptable for our custom tools. For upstream adoption, glibc can update its wrapper or a new `utimensat2()` syscall can be introduced.

### 4.4 statx Extension

**`include/uapi/linux/stat.h`**:
```c
#define STATX_PTIME     0x00040000U

struct statx {
    /* ... existing fields ... */
    struct statx_timestamp  stx_ptime;    /* in __spare3 area */
    __u64  __spare3[6];                   /* reduced from [8] */
};
```

Must include `static_assert(sizeof(struct statx) == 256)` and `static_assert(offsetof(struct statx, stx_ptime) == 0xC0)` to verify layout stability.

**`fs/stat.c`**: Pass STATX_PTIME through to filesystem `.getattr`.

### 4.5 Native vs Mapped Architecture

ptime implementations fall into two categories based on the filesystem's relationship to other operating systems and its on-disk format constraints.

#### Native ptime (Btrfs, ext4)

Linux-native filesystems that can and should separate forensic btime from settable ptime:

- **Separate on-disk fields**: ptime has its own dedicated storage space, distinct from btime/crtime
- **btime remains immutable**: No existing semantics are changed. `stx_btime` continues to report when the inode was created on this filesystem
- **ptime is independently settable**: Can be set, read, and preserved without affecting btime
- **Full nanosecond precision**: Both Btrfs (struct btrfs_timespec) and ext4 (epoch+extra encoding) support nanoseconds

**Rationale**: On Linux-native filesystems, there is no external OS modifying creation timestamps. btime has genuine forensic value. ptime deserves its own space to preserve that forensic integrity.

#### Mapped ptime (ntfs3, FAT32/vfat, exFAT)

Bridge filesystems shared with other operating systems where creation time is already mutable:

- **ptime maps to the existing creation time field**: No new on-disk storage. `i_crtime` / Date Created IS ptime
- **Setting ptime OVERWRITES creation time**: These are the same field
- **Justified by host OS behavior**: Windows treats creation time as mutable via `SetFileTime()`. macOS treats it as mutable via `setattrlist()`. Every OS that natively uses these formats can already modify creation time through standard APIs
- **Files originating on these FS**: creation time = ptime (same value, always)
- **Files transferred TO these FS**: ptime stamps to creation time (Windows Explorer shows correct Date Created)

**Rationale**: On bridge filesystems, "forensic integrity" of creation time does not exist — it is already modifiable by every OS that uses these formats. The only available field for provenance IS creation time. Linux should at minimum match the behavior of the host OS.

#### The Upstream Argument

> On filesystems where the host OS treats creation time as mutable (NTFS via SetFileTime, FAT via SetFileTime, exFAT via SetFileTime), Linux should at minimum match that behavior. This is not an expansion of capability — it is parity with existing cross-platform semantics. On Linux-native filesystems (Btrfs, ext4), ptime is a separate field that preserves btime immutability. Neither side compromises.

---

## 5. Filesystem Implementations

### 5.1 Btrfs (Native ptime)

#### On-Disk Storage

Modify `struct btrfs_inode_item` in `include/uapi/linux/btrfs_tree.h`:

```c
struct btrfs_inode_item {
    /* ... existing fields ... */
    struct btrfs_timespec ptime;  /* provenance time — 12 bytes */
    __le32 __reserved_pad;        /* alignment — 4 bytes */
    __le64 reserved[2];           /* 16 bytes remaining */
    struct btrfs_timespec atime;
    struct btrfs_timespec ctime;
    struct btrfs_timespec mtime;
    struct btrfs_timespec otime;
} __attribute__ ((__packed__));
```

32 bytes consumed (was `reserved[4]` = 32 bytes). Byte-compatible with old layout. Must include `static_assert` verifying field offsets match old layout.

Note: This is a UAPI struct rename. Existing userspace code referencing `reserved[4]` will need updating (primarily btrfs-progs). Binary compatibility is preserved.

**Feature flag**: `BTRFS_FEATURE_COMPAT_RO_PTIME`. Old kernels can mount read-only but cannot mount read-write (prevents silently zeroing ptime during inode updates). Note: if filesystem has a dirty log and old kernel attempts mount, it may fail even for RO unless `nologreplay` is specified.

#### In-Memory Storage

`struct btrfs_inode` (filesystem-specific, NOT VFS struct inode):
```c
struct btrfs_inode {
    /* ... existing fields ... */
    u64 i_ptime_sec;
    u32 i_ptime_nsec;
};
```

Note: Uses separate sec/nsec fields (not `struct timespec64`) to match the on-disk `btrfs_timespec` format and avoid padding waste. Read/write via the existing `btrfs_set_timespec_sec()`/`btrfs_set_timespec_nsec()` accessor pattern.

#### Inode Operations

| Function | Change |
|---|---|
| `btrfs_getattr()` | Read `i_ptime`, fill `stat->ptime`, set `STATX_PTIME` in result_mask (only if ptime non-zero) |
| `btrfs_setattr()` | Handle `ATTR_PTIME`: write `ia_ptime` to `BTRFS_I(inode)->i_ptime` |
| `btrfs_read_locked_inode()` | Load ptime from on-disk item to `i_ptime` |
| `fill_inode_item()` | **Write `i_ptime` to on-disk item** — critical: also used by tree-log replay (fsync crash recovery). If missing, crash after fsync restores file with ptime=0. |
| `btrfs_new_inode()` | Initialize `i_ptime = {0, 0}` |

#### Rename-Over Preservation

In `btrfs_rename()`, before target inode unlink, within the rename transaction:

```c
if (new_inode && S_ISREG(old_inode->i_mode) &&
    S_ISREG(new_inode->i_mode) && old_inode->i_nlink == 1 &&
    !(flags & (RENAME_EXCHANGE | RENAME_WHITEOUT))) {
    struct btrfs_inode *old_bi = BTRFS_I(old_inode);
    struct btrfs_inode *new_bi = BTRFS_I(new_inode);
    if (!old_bi->i_ptime_sec && !old_bi->i_ptime_nsec &&
        (new_bi->i_ptime_sec || new_bi->i_ptime_nsec)) {
        old_bi->i_ptime_sec = new_bi->i_ptime_sec;
        old_bi->i_ptime_nsec = new_bi->i_ptime_nsec;
        /* Dirty within transaction — atomic with rename */
    }
}
```

#### Send/Receive

`fs/btrfs/send.c`: Add `BTRFS_SEND_A_PTIME` to the send stream, following `BTRFS_SEND_A_OTIME` pattern. Receiving side writes ptime via setattr path.

### 5.2 ext4 (Native ptime) — Separate i_ptime Field

ext4 implements ptime as a **new, dedicated on-disk field** in the extended inode area. This aligns with Ts'o's March 2025 concept — distinguishing between forensic btime (immutable `i_crtime`) and settable creation time (now `i_ptime`) — but gives each its own storage rather than overloading a single field.

#### On-Disk Storage

New fields in `struct ext4_inode` (in the extended inode area, after `i_projid`):

```c
struct ext4_inode {
    /* ... existing fields (128 bytes) ... */
    /* Extended inode area (from offset 128): */
    __le32  i_ctime_extra;
    __le32  i_mtime_extra;
    __le32  i_atime_extra;
    __le32  i_crtime;          /* forensic btime — IMMUTABLE */
    __le32  i_crtime_extra;    /* forensic btime nsec — IMMUTABLE */
    __le32  i_version_hi;
    __le32  i_projid;
    __le32  i_ptime;           /* NEW: provenance time — settable */
    __le32  i_ptime_extra;     /* NEW: provenance time encoded nsec + epoch extension */
    /* ... remaining extended area ... */
};
```

**Space budget**: 256-byte inodes (modern default since ext4's introduction) have a 128-byte extended area. After existing extended fields consume ~32 bytes, approximately 96 bytes remain free. Adding `i_ptime` (4 bytes) + `i_ptime_extra` (4 bytes) = 8 bytes is trivial — ~8% of available extended space.

**128-byte inodes**: ptime silently unavailable. The `EXT4_FITS_IN_INODE` macro provides graceful degradation — the same mechanism ext4 uses for `i_crtime` on old 128-byte inodes. No error, no warning; getattr simply doesn't report STATX_PTIME, setattr returns silently (or EOPNOTSUPP — TBD with Ts'o).

**Encoding**: `i_ptime_extra` uses the same encoding as `i_crtime_extra` and other ext4 timestamp extras: bits 0-1 extend the epoch (seconds beyond 2^32), bits 2-31 store nanoseconds. This provides dates through 2446 with nanosecond precision.

#### In-Memory Storage

```c
struct ext4_inode_info {
    /* ... existing fields ... */
    struct timespec64 i_ptime;    /* provenance time */
};
```

#### Inode Operations

| Function | Change |
|---|---|
| `ext4_iget()` | Read `i_ptime` + `i_ptime_extra` from on-disk inode with `EXT4_FITS_IN_INODE` guard. Decode using `ext4_decode_extra_time()`. Store in `EXT4_I(inode)->i_ptime`. |
| `ext4_do_update_inode()` | Write `i_ptime` + `i_ptime_extra` to on-disk inode with `EXT4_FITS_IN_INODE` guard. Encode using `ext4_encode_extra_time()`. |
| `ext4_getattr()` | Read `EXT4_I(inode)->i_ptime`. If non-zero AND `EXT4_FITS_IN_INODE` is satisfied, fill `stat->ptime`, set `STATX_PTIME` in result_mask. |
| `ext4_setattr()` | Handle `ATTR_PTIME`: write `ia_ptime` to `EXT4_I(inode)->i_ptime`. Mark inode dirty. |
| `ext4_new_inode()` | Initialize `EXT4_I(inode)->i_ptime = {0, 0}`. |

**Critical distinction from v4**: `i_crtime` is NOT touched. It remains immutable btime. Getattr reads ptime from `i_ptime`, NOT `i_crtime`. Setattr writes ptime to `i_ptime`, NOT `i_crtime`. Rename-over preserves `i_ptime`, NOT `i_crtime`.

#### Rename-Over Preservation

In `ext4_rename()`, same native ptime-zero sentinel pattern as Btrfs. Inserted after `inode_set_ctime_current(old.inode)`, before `ext4_mark_inode_dirty()`:

```c
if (new.inode && S_ISREG(old.inode->i_mode) &&
    S_ISREG(new.inode->i_mode) && old.inode->i_nlink == 1 &&
    !(flags & RENAME_WHITEOUT)) {
    struct ext4_inode_info *old_ei = EXT4_I(old.inode);
    struct ext4_inode_info *new_ei = EXT4_I(new.inode);

    if (!old_ei->i_ptime.tv_sec && !old_ei->i_ptime.tv_nsec &&
        (new_ei->i_ptime.tv_sec || new_ei->i_ptime.tv_nsec))
        old_ei->i_ptime = new_ei->i_ptime;
}
```

#### Feature Flag

New ext4 compat flag enabling ptime fields. Exact flag name and bit position to be coordinated with Ts'o. Candidate: `EXT4_FEATURE_COMPAT_PTIME` or `EXT4_FEATURE_RO_COMPAT_PTIME`.

**Compat vs RO-compat**: A compat flag means old kernels can mount and operate normally (they simply ignore the ptime fields). An RO-compat flag means old kernels can mount read-only only (prevents silently zeroing ptime on writes). RO-compat is safer but more restrictive — coordinate with Ts'o on the right choice.

#### Why This Approach (vs v4's crtime reuse)

v4 mapped ptime onto ext4's existing `i_crtime` fields — reinterpreting the same on-disk bytes as either forensic btime or settable ptime based on a feature flag. This had two problems:

1. **Ambiguity**: The same bytes served two conflicting purposes depending on mount flags. Code reading `i_crtime` couldn't know whether it was immutable or settable without checking the feature flag.
2. **Incomplete separation**: Ts'o's 2025 concept distinguished between forensic btime and settable crtime. Reusing the same field doesn't achieve that distinction — it just changes the interpretation.

The v5 approach gives both concepts their own storage: `i_crtime` remains forensic btime (immutable, always available); `i_ptime` is the settable provenance timestamp. This is a cleaner implementation of Ts'o's vision.

### 5.3 f2fs

Follows ext4 pattern. `f2fs_inode` has `i_crtime` and substantial node block padding. Add dedicated ptime fields alongside existing crtime (same architecture as ext4 v5 — separate field, crtime remains immutable). Implementation details deferred to Phase 2.

### 5.4 ntfs3 (Mapped ptime) — Maps ptime ↔ NTFS Creation Time

#### Reading (getattr)

`ntfs3_getattr()`: When STATX_PTIME requested, read NTFS creation time from `$STANDARD_INFORMATION` attribute. Report as `stat->ptime`. This is the same value already reported as `stat->btime`.

#### Writing (setattr)

`ntfs3_setattr()`: When ATTR_PTIME set, write `ia_ptime` to NTFS creation time field in `$STANDARD_INFORMATION`.

**Important**: The current ntfs3 `ni_write_inode()` writes `m_time`, `c_time`, `a_time` but NOT `cr_time`. The write path for creation time must be built — updating `std->cr_time` in `$STANDARD_INFORMATION` during inode writeback. This follows the existing pattern for the other three timestamps but is new code, not just a setattr branch.

#### Rename-Over Preservation

In `ntfs_rename()`, save target's creation time before unlink (ntfs3 unlinks the target before the rename), then restore after rename succeeds:

```c
/* Before target unlink */
struct timespec64 saved_crtime = {};
bool inherit_crtime = false;
if (new_inode && S_ISREG(inode->i_mode) &&
    S_ISREG(new_inode->i_mode) && inode->i_nlink == 1) {
    saved_crtime = ntfs_i(new_inode)->i_crtime;
    inherit_crtime = true;
}

/* ... unlink target, perform rename ... */

if (!err && inherit_crtime)
    ni->i_crtime = saved_crtime;
```

This replicates Windows behavior: when an application uses `MoveFileEx(MOVEFILE_REPLACE_EXISTING)` on NTFS, the replaced file's creation time transfers to the replacement.

#### Semantic Tension (Documented)

This mapping conflates two concepts: NTFS creation time ("when this copy was created on this filesystem") and ptime ("when this content first existed anywhere"). The mapping is pragmatically correct because:
- Windows allows setting creation time via `SetFileTime()` — NTFS creation time was never truly immutable
- Backup/migration tools (robocopy, rsync) routinely write creation time during copies
- The user's intent is to see the original creation date in Windows Explorer
- For files originating on NTFS, creation time and ptime are identical

The gap only manifests for files that originate elsewhere and are written to NTFS — in which case the user explicitly wants the provenance date displayed as Date Created.

#### Forensic Detection Note

NTFS stores timestamps in two places: `$STANDARD_INFORMATION` (user-visible, modifiable by `SetFileTime`) and `$FILE_NAME` (managed by NTFS itself, NOT modifiable by user APIs). When `$STANDARD_INFORMATION.cr_time` is modified (by ptime setattr or by Windows SetFileTime), `$FILE_NAME` timestamps remain unchanged. Forensic tools CAN detect this discrepancy — but this is normal and expected behavior. Windows `SetFileTime()` creates the same discrepancy. This is not a ptime-specific artifact; it is inherent to NTFS's dual-timestamp architecture.

#### Round-Trip

```
NTFS (Date Created: 2019-06-15)
  → statx reads stx_ptime = 2019-06-15
  → patched cp writes to Btrfs via utimensat(AT_UTIME_PTIME)
  → Btrfs ptime = 2019-06-15

Btrfs (ptime: 2019-06-15)
  → statx reads stx_ptime = 2019-06-15
  → patched cp writes to NTFS via utimensat(AT_UTIME_PTIME)
  → ntfs3 writes cr_time = 2019-06-15
  → Windows Explorer shows: Date Created: 6/15/2019
```

### 5.5 FAT32/vfat (Mapped ptime)

FAT32 is a bridge filesystem with no space for new on-disk fields. ptime maps to the existing creation time (Date Created) field.

#### On-Disk Format

FAT32 directory entries include a creation timestamp:
- `ctime` (2 bytes): time in DOS format (hours/minutes/2-second granularity)
- `cdate` (2 bytes): date in DOS format
- `ctime_cs` (1 byte): creation time centiseconds (0-199, providing 10ms resolution)

**Precision**: 2-second base + 10ms centisecond field. Nanosecond-precision ptime values are truncated on write. This is inherent to FAT32's fixed format and cannot be improved.

#### Reading (getattr)

`fat_getattr()`: When STATX_PTIME requested, read creation time from FAT directory entry. Convert from DOS format to `struct timespec64`. Report as `stat->ptime`.

This is the same value already reported as `stat->btime`. On FAT32, btime and ptime are always identical (same underlying field).

#### Writing (setattr)

`fat_setattr()`: When ATTR_PTIME set, write `ia_ptime` to FAT creation time fields in directory entry. Convert from `struct timespec64` to DOS format with centisecond field.

**Note**: The existing vfat driver already reads creation time. The write path for creation time must be built, following the pattern of the existing mtime/atime write paths.

#### Rename-Over Preservation

In `vfat_rename()`, save target's creation time before `fat_detach`, restore after `fat_attach`:

```c
struct timespec64 saved_crtime = {};
bool inherit_crtime = false;
if (new_inode && S_ISREG(old_inode->i_mode) &&
    S_ISREG(new_inode->i_mode) && old_inode->i_nlink == 1) {
    saved_crtime = MSDOS_I(new_inode)->i_crtime;
    inherit_crtime = true;
}

fat_detach(old_inode);
fat_attach(old_inode, new_i_pos);

if (inherit_crtime)
    MSDOS_I(old_inode)->i_crtime = saved_crtime;
```

Note: `vfat_rename()` is called from `vfat_rename2()` which already rejects unsupported flags. FAT32 does not support RENAME_EXCHANGE or RENAME_WHITEOUT.

#### Feature Flag

None. FAT32 is a fixed format — no superblock feature flags. ptime support is always available when the vfat driver is loaded.

### 5.6 exFAT (Mapped ptime)

exFAT is a bridge filesystem designed for flash media. Like FAT32, ptime maps to the existing creation time field.

#### On-Disk Format

exFAT directory entries include creation timestamps:
- `create_tz` (1 byte): UTC offset
- `create_date` (2 bytes): date
- `create_time` (2 bytes): time (2-second granularity)
- `create_time_cs` (1 byte): 10ms increments (0-199)

**Precision**: 10ms. Better than FAT32's 2-second base but still far below nanosecond. ptime values are truncated on write.

#### Reading (getattr)

`exfat_getattr()`: When STATX_PTIME requested, read creation time from exFAT directory entry. Report as `stat->ptime`.

#### Writing (setattr)

`exfat_setattr()`: When ATTR_PTIME set, write `ia_ptime` to exFAT creation time fields in directory entry. The exFAT driver already has creation time read infrastructure; write path follows the existing mtime/atime pattern.

#### Rename-Over Preservation

In `exfat_rename()`, save target's creation time before `__exfat_rename`, restore after:

```c
struct timespec64 saved_crtime = {};
bool inherit_crtime = false;
if (new_inode && S_ISREG(old_inode->i_mode) &&
    S_ISREG(new_inode->i_mode) && old_inode->i_nlink == 1) {
    saved_crtime = EXFAT_I(new_inode)->i_crtime;
    inherit_crtime = true;
}

err = __exfat_rename(old_dir, EXFAT_I(old_inode), new_dir, new_dentry);
if (err)
    goto unlock;

if (inherit_crtime)
    EXFAT_I(old_inode)->i_crtime = saved_crtime;
```

#### Feature Flag

None. exFAT is a fixed format. ptime support is always available when the exfat driver is loaded.

### 5.7 Filesystem Support Summary

| Filesystem | Category | Storage | Rename-Over | Feature Flag | Precision | Lines |
|---|---|---|---|---|---|---|
| Btrfs | Native | Named field in reserved space | Yes (ptime-zero sentinel) | COMPAT_RO | nanosecond | ~200 |
| ext4 | Native | New i_ptime + i_ptime_extra fields | Yes (ptime-zero sentinel) | New compat flag (TBD w/ Ts'o) | nanosecond | ~200 |
| f2fs | Native | New ptime fields (deferred) | Yes | TBD | nanosecond | ~100 |
| ntfs3 | Mapped | NTFS creation time ($STD_INFO) | Yes (save/restore crtime) | N/A | 100ns | ~100 |
| FAT32/vfat | Mapped | FAT creation time fields | Yes (save/restore crtime) | N/A | 2 seconds | ~80 |
| exFAT | Mapped | exFAT creation time fields | Yes (save/restore crtime) | N/A | 10ms | ~80 |
| XFS | Deferred | — | — | — | — | — |
| tmpfs | Deferred | — | — | — | — | — |

---

## 6. Build Strategy

### 6.1 Three-Kernel Architecture

| Kernel | Package | Managed By | Purpose |
|---|---|---|---|
| LTS | `linux-lts` | pacman (rolling) | Safety net — always bootable |
| Mainline | `linux` | pacman (rolling) | Current — stays up to date |
| **ptime** | **`linux-ptime`** | **Manual rebuild** | **Default boot — our patched kernel** |

### 6.2 PKGBUILD Setup

1. Clone: `pkgctl repo clone --protocol=https linux`
2. Modify PKGBUILD: `pkgbase=linux` → `pkgbase=linux-ptime`
3. Remove `linux` from `provides`
4. Place `ptime-v5.patch` in the PKGBUILD directory
5. Add `ptime-v5.patch` to the `source=()` array with `SKIP` checksums
6. `prepare()` auto-applies all `.patch` files from the source array

**Critical**: Patches MUST be in the PKGBUILD `source=()` array, not applied directly to `src/`. `makepkg` re-extracts the source tarball on every build, wiping any direct edits to files under `src/`. Only patches listed in `source=()` survive rebuilds.

### 6.3 Operational Requirements

**mkinitcpio preset** (`/etc/mkinitcpio.d/linux-ptime.preset`):
```
ALL_config="/etc/mkinitcpio.conf"
ALL_kver="/boot/vmlinuz-linux-ptime"
PRESETS=('default' 'fallback')
default_image="/boot/initramfs-linux-ptime.img"
fallback_options="-S autodetect"
```

**GRUB default**: Set `GRUB_DEFAULT=saved` in `/etc/default/grub`. After install: `sudo grub-set-default N` (where N is the linux-ptime entry index).

**Headers package**: `linux-ptime-headers` MUST be installed — required for NVIDIA DKMS module rebuilds and any other out-of-tree modules.

**Secure Boot**: When sbctl is configured (TODO-030), linux-ptime kernel and modules must be signed with the user's enrolled key.

### 6.4 Locally-Patched Tool Packages

| Package | Local Name | IgnorePkg Entry |
|---|---|---|
| coreutils | `coreutils-ptime` | `coreutils` |
| kio | `kio-ptime` | `kio` |
| rsync | `rsync-ptime` | `rsync` |
| btrfs-progs | `btrfs-progs-ptime` | `btrfs-progs` |

Build process same as kernel: download PKGBUILD from Arch GitLab, apply patch, `makepkg -s`, `sudo pacman -U`.

### 6.5 Rebase Cycle

When updating to new kernel or tool version:
1. Fresh PKGBUILD clone
2. Copy patch files
3. `makepkg -s` — patches apply cleanly or need resolution
4. Install, regenerate GRUB config

Tool patches (~20-40 lines each) are structurally stable — they add one timestamp to an existing timestamp loop. Expect clean application across most version bumps.

---

## 7. Implementation Plan

### 7.1 Patch Series (Kernel)

Consolidated from Associate review feedback. VFS patches combined into single patch.

**Phase 1 — All 5 filesystems (implemented, tested, format-patch generated):**

| # | Patch | Scope | Files | Lines |
|---|---|---|---|---|
| 1 | vfs: add provenance_time (ptime) infrastructure | ATTR_PTIME (bit 19/20), STATX_PTIME, AT_UTIME_PTIME, ia_ptime, setattr_prepare, utimes.c, stat.c, all vfs_utimes callers | 10 | +64/-19 |
| 2 | btrfs: add provenance time (ptime) support | On-disk struct, getattr, setattr, delayed-inode, tree-log, new_inode init, COMPAT_RO flag, rename-over (ptime-zero sentinel) | 7 | +58/-2 |
| 3 | ntfs3: map ptime to NTFS creation time with rename-over | getattr, setattr, frecord cr_time write, rename-over (save/restore i_crtime) | 3 | +35 |
| 4 | ext4: add dedicated ptime field alongside i_crtime | New i_ptime + i_ptime_extra on-disk fields, iget/update_inode, getattr, setattr, rename-over (ptime-zero sentinel) | 3 | +30 |
| 5 | fat: map ptime to FAT creation time with rename-over | getattr, setattr, rename-over (save/restore i_crtime) | 2 | +24/-2 |
| 6 | exfat: map ptime to exFAT creation time with rename-over | getattr, setattr, rename-over (save/restore i_crtime) | 2 | +27/-3 |

**Total kernel (Phase 1)**: ~238 insertions, 27 files, 6 patches. Format-patch generated at `~/ptime-submission/kernel/patches/`. All pass `git am` and `checkpatch.pl` (0 errors, 3 cosmetic warnings).

**Phase 2 (deferred):**

| # | Patch | Lines |
|---|---|---|
| 7 | Btrfs: send/receive ptime | BTRFS_SEND_A_PTIME in send stream + receive setattr. ~60 |
| 8 | f2fs: ptime support | ~100 |

**Note on patch structure**: Each filesystem patch includes BOTH getattr/setattr AND rename-over in a single commit. This keeps each filesystem's changes self-contained for review and bisection.

### 7.2 Userspace Tools

| # | Tool | Status | Lines |
|---|---|---|---|
| 9 | coreutils cp (files + directories) | **Deployed** | ~50 |
| 10 | KIO (Dolphin) file + directory copy | **Deployed** | ~70 |
| 11 | rsync --crtimes | **Deployed** | ~30 |
| 12 | tar SCHILY.ptime PAX header | **Deployed** | ~40 |
| 13 | coreutils stat display | Pending | ~20 |
| 14 | btrfs-progs dump-tree | Pending | ~20 |
| 15 | ptime-set (new tool) | Pending | ~200 |
| 16 | ptime-stat (new tool) | Pending | ~100 |

### 7.3 Documentation

| # | Deliverable |
|---|---|
| 17 | man-page updates: statx(2), utimensat(2) — required for any UAPI change |
| 18 | ptime-doctor-kernel health check script |

### 7.4 Development Order

**Phase 1 — Core (COMPLETE — all 5 FS working end-to-end with rename-over):**
Kernel patches 1-6 deployed. Tools 9-12 deployed (cp, KIO, rsync, tar). PKGBUILD integrates ptime-v5.patch.

**Phase 2 — Polish:**
Kernel patches 7-8 (btrfs send, f2fs). Tools 13-16 (stat display, btrfs-progs, ptime-set, ptime-stat). Docs 17-18 (man-pages, ptime-doctor).

**Phase 3 — Upstream:**
Submit kernel patch series to linux-fsdevel. Contact Sterba first. Submit tool patches to respective projects.

---

## 8. Testing Plan

### 8.1 Core Kernel Tests

| # | Test | Method | Expected |
|---|---|---|---|
| 1 | New file ptime=0 | statx with STATX_PTIME | STATX_PTIME NOT in result_mask (ptime unset) |
| 2 | Set ptime via utimensat | ptime-set + ptime-stat | Reports set value; STATX_PTIME in mask |
| 3 | ptime survives reboot | Set → clean reboot → check | Value persists |
| 4 | ptime survives crash | Set → forced power-off (QEMU) → check | Value persists (tree-log replay) |
| 5 | Atomic save (LibreOffice) | Set ptime, edit in LibreOffice, save, check | **ptime preserved** |
| 6 | Atomic save (Vim :wq) | Set ptime, Vim edit, :wq, check | ptime preserved |
| 7 | Atomic save (Kate) | Set ptime, Kate edit, Ctrl+S, check | ptime preserved |
| 8 | Source has own ptime on rename-over | Set ptime on both files, rename | Source ptime wins |
| 9 | nlink>1 guard | Hardlink source, rename-over target with ptime | ptime NOT copied |
| 10 | RENAME_EXCHANGE | renameat2(RENAME_EXCHANGE) on two ptime files | Both ptimes unchanged |
| 11 | Btrfs snapshot | Set ptime, snapshot, check snapshot | ptime preserved |
| 12 | Btrfs reflink | Set ptime, cp --reflink=always, check | ptime preserved |
| 13 | Permission: owner | Owner sets ptime | Success |
| 14 | Permission: non-owner | Non-owner sets ptime | EPERM |
| 15 | Permission: CAP_FOWNER | Process with capability sets ptime | Success |
| 16 | Feature flag: old kernel | Boot unpatched kernel, mount Btrfs with ptime | RW mount rejected; RO mount succeeds |
| 17 | UTIME_NOW for ptime | utimensat with tv_nsec=UTIME_NOW in times[2] | ptime set to current time |
| 18 | UTIME_OMIT for ptime | utimensat with tv_nsec=UTIME_OMIT in times[2] | ptime unchanged |

### 8.2 Cross-Filesystem Tests

| # | Test | Expected |
|---|---|---|
| 19 | NTFS→Btrfs copy (patched cp) | NTFS Date Created → Btrfs ptime |
| 20 | Btrfs→NTFS copy (patched cp) | Btrfs ptime → NTFS Date Created |
| 21 | NTFS→Btrfs→NTFS round-trip | Date Created preserved through full cycle |
| 22 | Nanosecond precision NTFS↔Btrfs | Verify ns precision (NTFS=100ns, Btrfs=1ns) |
| 23 | Btrfs→ext4 copy (Phase 2) | ptime preserved |
| 24 | Cross-FS mv (EXDEV fallback) | Btrfs→NTFS mv uses patched cp, ptime preserved |
| 25 | Btrfs→FAT32 copy | ptime truncated to 2-second precision, creation time set |
| 26 | FAT32→Btrfs copy | FAT32 creation time → Btrfs ptime (2-second precision) |
| 27 | Btrfs→exFAT copy | ptime truncated to 10ms precision, creation time set |
| 28 | exFAT→Btrfs copy | exFAT creation time → Btrfs ptime (10ms precision) |
| 29 | Copy to tmpfs | STATX_PTIME not in result_mask (no ptime support) |

### 8.3 Rename-Over Tests (All Filesystems)

| # | Test | Expected |
|---|---|---|
| 30 | Btrfs atomic save (native) | ptime preserved via ptime-zero sentinel |
| 31 | ext4 atomic save (native, Phase 2) | ptime preserved via ptime-zero sentinel |
| 32 | NTFS atomic save (mapped) | Creation time preserved via save/restore |
| 33 | FAT32 atomic save (mapped) | Creation time preserved via save/restore |
| 34 | exFAT atomic save (mapped) | Creation time preserved via save/restore |
| 35 | NTFS: verify Windows Explorer shows original date after save | Date Created unchanged |
| 36 | FAT32: verify creation date survives atomic save | 2-second precision maintained |

### 8.4 Stress and Concurrency Tests

| # | Test | Expected |
|---|---|---|
| 37 | Copy 100,000 files with ptime | No performance degradation vs without ptime |
| 38 | Concurrent ptime-set on same file | Both writes succeed, last write wins |
| 39 | Snapshot during ptime write | ptime in consistent state |
| 40 | Filesystem full during ptime set | ENOSPC returned, no partial write |
| 41 | Quota exceeded during ptime set | EDQUOT returned |

### 8.5 Btrfs Integrity Tests

| # | Test | Expected |
|---|---|---|
| 42 | btrfs check after ptime operations | No errors |
| 43 | btrfs scrub after ptime operations | No errors |
| 44 | Btrfs RAID1: set ptime, check both devices | ptime consistent |
| 45 | Btrfs send/receive with ptime | ptime transmitted and written |
| 46 | btrfs-progs dump-tree shows ptime | Decoded correctly |

### 8.6 Negative and Regression Tests

| # | Test | Expected |
|---|---|---|
| 47 | statx STATX_PTIME on XFS/tmpfs | STATX_PTIME not in mask |
| 48 | utimensat AT_UTIME_PTIME on old kernel | EINVAL |
| 49 | Unpatched cp -a with ptime files | ptime NOT preserved (confirms tool patch necessity) |
| 50 | Old statx binary on patched kernel | Struct size unchanged (256 bytes), no breakage |
| 51 | New statx binary on old kernel | STATX_PTIME silently ignored |
| 52 | btrfs check with old btrfs-progs | No false corruption alarms |
| 53 | ext4 ptime on 128-byte inode | ptime silently unavailable, no errors |
| 54 | FAT32 ptime precision round-trip | Nanoseconds truncated to 2-second, no error |

### 8.7 Testing Infrastructure

| Tool | Purpose |
|---|---|
| **xfstests** | Standard filesystem test suite — add ptime test cases |
| **QEMU** | VM-level crash testing (power-off simulation) |
| **fsx-linux** | Filesystem exerciser with crash simulation |
| **fsstress** | Randomized filesystem operations |
| **checkpatch.pl** | Kernel coding style verification |
| **sparse** | Static analysis for kernel code |

### 8.8 Pre-Production Checklist

Before deploying linux-ptime to Praxis:

| Check | Pass Criteria |
|---|---|
| Kernel boots | `uname -r` shows linux-ptime |
| Btrfs mounts cleanly | No errors in dmesg |
| ptime set/get round-trip | ptime-set + ptime-stat works |
| Atomic save preservation (Btrfs) | LibreOffice save preserves ptime |
| Atomic save preservation (NTFS) | LibreOffice save preserves creation time |
| NTFS round-trip | Date Created preserved through Btrfs |
| FAT32 round-trip | Creation time preserved (2-second precision) |
| exFAT round-trip | Creation time preserved (10ms precision) |
| xfstests pass | No new failures vs stock kernel |
| btrfs check clean | No errors after ptime operations |
| LTS kernel still boots | Fallback verified |
| NVIDIA driver works | GPU acceleration confirmed |
| Feature flag enforced | Old kernel cannot mount RW |

---

## 9. Upstream Strategy

### 9.1 Submission Plan

**Phase A — Initial (6-patch series: VFS + Btrfs + ntfs3 + ext4 + vfat + exfat):**
`[RFC PATCH 0/6] VFS + Btrfs + ntfs3 + ext4 + vfat + exfat: provenance_time (ptime)`

Cover letter narrative: "Implements a settable inode timestamp for provenance tracking, as proposed in [RFC link] and aligned with Ts'o's March 2025 btime/crtime distinction. Two implementation categories: native (separate ptime field on Btrfs and ext4, preserving btime immutability) and mapped (ptime maps to creation time on bridge filesystems where the host OS treats creation time as mutable). Rename-over preservation on all five filesystems. Tested on EndeavourOS."

**Phase C — f2fs follow-up**: Same pattern.

### 9.2 Maintainer Engagement

| Maintainer | Strategy |
|---|---|
| **Sterba (Btrfs)** | **Contact before submitting.** Email: "I have working patches for ptime in Btrfs that serve your send/receive v2 use case. Would you be willing to review?" Getting a "yes, send them" transforms the submission. |
| **Ts'o (ext4)** | CC on initial submission. Frame ptime as implementing his btime/crtime distinction — with dedicated fields rather than overloading crtime. ext4 patches follow in Phase B. |
| **Brauner (VFS)** | Emphasize minimal VFS footprint: no i_ptime in struct inode, small flag additions only. |
| **Komarov (ntfs3)** | CC on submission. ntfs3 creation time write serves general NTFS interop. |
| **Chinner (XFS)** | Do not engage initially. ptime doesn't touch btime. If he objects, respond: "ptime is a separate field — btime remains immutable." |

### 9.3 Key Arguments

1. **Rename-over preservation** — "99% of Linux applications save via write-temp + rename. Without kernel-level preservation, every application save destroys provenance. No userspace solution can intercept rename(). This was empirically confirmed by attempting the xattr approach."

2. **Resolves 7-year impasse** — ptime gives provenance data a home without compromising btime's forensic meaning. Neither side compromises.

3. **Cross-platform interop** — Windows (SetFileTime), macOS (setattrlist), SMB (create_time) all support settable creation timestamps. Linux is the outlier. Affects NAS servers, enterprise migration, data archiving.

4. **Harrosh's 2019 conceptual framework** — "Author creation time" (globally-carried, settable) vs. "Local creation time" (immutable, forensic). ptime formalizes the distinction the community recognized 7 years ago.

5. **Bridge filesystem parity** — On bridge filesystems (NTFS, FAT32, exFAT) used for cross-platform file sharing, the host OS treats creation time as mutable via standard APIs (Windows `SetFileTime()`, macOS `setattrlist()`). No forensic integrity exists to protect — these timestamps are already modifiable by every OS that uses these formats. Linux should at minimum match that behavior. On Linux-native filesystems, ptime is a separate field that preserves btime immutability.

---

## 10. Migration from xattr System

If files have `user.provenance_time` xattr from the earlier xattr system:

```bash
ptime-set --from-xattr <directory>    # Reads xattr, sets kernel ptime, optionally removes xattr
```

Built into ptime-set as a migration mode.

---

## 11. Known Limitations

| Limitation | Impact | Mitigation |
|---|---|---|
| XFS deferred | XFS users no ptime | Add after upstream acceptance |
| tmpfs not implemented | /tmp no ptime | Irrelevant (volatile) |
| FAT32 2-second precision | Nanosecond ptime truncated to 2-second granularity on FAT32 | Documented trade-off inherent to format. Sub-second precision lost, date/hour/minute preserved. |
| exFAT 10ms precision | Nanosecond ptime truncated to 10ms granularity on exFAT | Documented trade-off inherent to format. |
| Mapped FS: ptime = creation time | Setting ptime overwrites creation time on ntfs3, FAT32, exFAT | By design — host OS treats creation time as mutable. No forensic integrity to protect. See §4.5. |
| ext4 128-byte inodes | ptime silently unavailable on legacy filesystems with small inodes | Modern default is 256 bytes. EXT4_FITS_IN_INODE provides graceful degradation — same as i_crtime behavior. |
| Unpatched tools drop ptime | Silent loss with stock cp/rsync | Deploy patched packages; ptime-doctor warns |
| Rename-over heuristic | Could stamp wrong ptime for unrelated overwrites | nlink=1 + zero-check (native) / timestamp-compare (mapped) guards minimize |
| Backup-via-rename editors | Vim/Emacs strand ptime on .bak | Configure backupcopy=yes |
| ptime=0 is epoch | True 1970-01-01T00:00:00Z unrepresentable | No files predate 1970 |
| glibc wrapper limitation | Standard utimensat() can't pass ptime | Tools use raw syscall(); glibc update or utimensat2 for upstream |
| Custom kernel maintenance | Periodic rebase | Small patches, LTS fallback |
| Dolphin GUI ptime display | Fully implemented — Properties dialog "Provenance Time:" label, sortable column in details view, directory ptime via copyjob.cpp fix. Btrfs↔NTFS round-trips verified. | KIO/Dolphin patches need PKGBUILD consolidation for rebuild persistence. |

---

## 12. Open Questions

1. **Exact FS_HAS_PTIME bit**: Audit `include/linux/fs.h` for SB_* and FS_* flag availability
2. **Btrfs accessor macros**: Verify BTRFS_SETGET_FUNCS generation for named ptime field in modified struct
3. **ext4 feature flag**: Coordinate with Ts'o on exact compat flag for ptime-enabled ext4 filesystems — compat vs RO-compat, bit position, flag name
4. **cp --reflink behavior**: Verify reflink on Btrfs shares ptime (expected yes — COW shares full inode)
5. **BorgBackup**: Does Borg use statx? Would it pick up ptime automatically?
6. **Btrfs send v2 protocol extensibility**: Is adding BTRFS_SEND_A_PTIME backward-compatible?
7. **ext4 setattr on 128-byte inodes**: Currently returns silently (no-op). Should it return EOPNOTSUPP? Coordinate with Ts'o.
8. **Verify STATX 0xC0 offset in linux-next**: Ensure no pending patches claim the same __spare3 slot

---

## 13. References

| Source | Relevance |
|---|---|
| Sandoval's 2019 AT_UTIME_BTIME patches | Structural template. 6-patch series on lore.kernel.org. |
| Chinner's Feb 2019 objection | Forensic btime argument. ptime avoids by being separate field. |
| Ts'o's March 2025 btime/crtime proposal | ext4 ptime implements his concept with dedicated fields. Quotation: "crtime which *can* be changed by a system call interface." |
| Boaz Harrosh's 2019 "Author creation time" | Conceptual foundation: "A tag carried globally denoting the time of the original creator." |
| Sterba's Btrfs send v2 / otime | Btrfs maintainer ally. Wants settable timestamps for send/receive. |
| User's RFC (March 2026) | lore.kernel.org archive. Public record of proposal. |
| ACF xattr review (April 2026) | Empirical evidence of xattr fragility. Strengthens kernel case. |
| GNU coreutils source (copy.c) | Confirms tools hardcode atime+mtime. |
| ntfs3 source (frecord.c) | Confirms cr_time write path doesn't exist yet. |
| NTFS $FILE_NAME vs $STANDARD_INFORMATION | Dual-timestamp architecture. $FILE_NAME timestamps are not modified by SetFileTime/ptime — forensic tools can detect modification. Normal NTFS behavior. |
| FAT32 specification (ECMA-107 / Microsoft) | Creation time fields: ctime (2B), cdate (2B), ctime_cs (1B). 2-second + 10ms precision. |
| exFAT specification (ECMA-381 / Microsoft) | Creation timestamp fields with 10ms precision and UTC offset. |
