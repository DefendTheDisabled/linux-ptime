# Tool Patches for ptime Support

Each patch adds ptime reading (via raw statx syscall) and writing (via raw
utimensat syscall) to the tool's timestamp preservation path. All patches
use raw syscalls because glibc's utimensat() wrapper only supports 2
timestamps.

Syscall numbers (x86_64): statx=332, utimensat=280
ptime flag: AT_UTIME_PTIME=0x20000
statx mask: STATX_PTIME=0x00040000
stx_ptime offset: 0xC0 in struct statx

## coreutils (cp, mv)

File: src/copy.c
After the existing fdutimensat() timestamp preservation block, add:

### Code (inserted after atime/mtime preservation):

```c
/* Preserve provenance time (ptime) if source has it */
{
    char stxbuf[256];
    memset(stxbuf, 0, 256);
    if (syscall(332 /* SYS_statx */, AT_FDCWD, src_name,
                AT_SYMLINK_NOFOLLOW, 0x00040800U, stxbuf) == 0) {
        uint32_t mask;
        memcpy(&mask, stxbuf, 4);
        if (mask & 0x00040000U) {
            int64_t ptime_sec;
            int32_t ptime_nsec;
            memcpy(&ptime_sec, stxbuf + 0xC0, 8);
            memcpy(&ptime_nsec, stxbuf + 0xC8, 4);
            if (ptime_sec || ptime_nsec) {
                struct timespec ts[3];
                memset(ts, 0, sizeof(ts));
                ts[0].tv_nsec = ((1L << 30) - 2L); /* UTIME_OMIT */
                ts[1].tv_nsec = ((1L << 30) - 2L); /* UTIME_OMIT */
                ts[2].tv_sec = ptime_sec;
                ts[2].tv_nsec = ptime_nsec;
                syscall(280 /* SYS_utimensat */, dst_dirfd,
                        dst_relname, ts, 0x20000 /* AT_UTIME_PTIME */);
            }
        }
    }
}
```

Requires: `#include <sys/syscall.h>` and `#include <stdint.h>`

## KIO (Dolphin file manager)

File: src/kioworkers/file/file_unix.cpp
Same pattern as cp, wrapped in `#ifdef Q_OS_LINUX`. Uses `_src.data()` for
source path, `_dest.data()` for destination path. Uses `SYS_statx` and
`SYS_utimensat` macros.

## rsync

Three files modified. rsync already has `--crtimes` infrastructure for
macOS (getattrlist) and Cygwin (st_birthtime). We add a Linux backend.

### rsync.h
Change SUPPORT_CRTIMES condition:
```c
#if defined HAVE_GETATTRLIST || defined __CYGWIN__ || defined __linux__
#define SUPPORT_CRTIMES 1
#endif
```

### syscall.c
Add Linux case to get_create_time() — reads ptime via statx, falls back to
btime. Add do_set_ptime_linux() helper — writes ptime via utimensat.

### rsync.c
Add Linux case to set_file_attrs() crtime setting:
```c
#elif defined __linux__
             do_set_ptime_linux(fname, file_crtime) == 0
```

## GNU tar

Four files modified.

### tar.h
Add `struct timespec ptime;` to `struct tar_stat_info`.

### xheader.c
Add ptime_coder (reads ptime via statx using st->file_name),
ptime_decoder, and register SCHILY.ptime PAX keyword.

### create.c
Add `xheader_store("SCHILY.ptime", st, NULL)` after ctime store (inside
`archive_format == POSIX_FORMAT` block).

### extract.c
Add ptime restoration via raw utimensat after the fdutimensat timestamp
block.
