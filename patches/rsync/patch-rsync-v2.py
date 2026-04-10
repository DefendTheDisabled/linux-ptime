#!/usr/bin/env python3
"""Patch rsync for Linux ptime — v3. Uses file_setattr (syscall 469) for write."""
import sys

base = sys.argv[1] if len(sys.argv) > 1 else '.'

# 1. rsync.h — Enable SUPPORT_CRTIMES on Linux
print("[1/3] Patching rsync.h...")
path = f'{base}/rsync.h'
content = open(path).read()

old = '#if defined HAVE_GETATTRLIST || defined __CYGWIN__\n#define SUPPORT_CRTIMES 1\n#endif'
new = '#if defined HAVE_GETATTRLIST || defined __CYGWIN__ || (defined __linux__ && defined SYS_statx)\n#define SUPPORT_CRTIMES 1\n#endif'

if old in content:
    content = content.replace(old, new)
    open(path, 'w').write(content)
    print("  OK")
else:
    print("  ERROR"); sys.exit(1)

# 2. syscall.c — Add Linux get_create_time and do_set_ptime_linux
print("[2/3] Patching syscall.c...")
path = f'{base}/syscall.c'
content = open(path).read()

# Add includes if needed
if '#include <sys/syscall.h>' not in content:
    content = content.replace('#include "rsync.h"',
        '#include "rsync.h"\n#ifdef __linux__\n#include <sys/syscall.h>\n#endif')

# Add Linux case to get_create_time
old_get = '''#elif defined __CYGWIN__
\t(void)path;
\treturn stp->st_birthtime;
#else
#error Unknown crtimes implementation
#endif
}'''

new_get = '''#elif defined __CYGWIN__
\t(void)path;
\treturn stp->st_birthtime;
#elif defined __linux__
\t/* Read ptime (or btime fallback) via raw statx syscall */
\t(void)stp;
\tchar stxbuf[256];
\tmemset(stxbuf, 0, 256);
\tif (syscall(SYS_statx, AT_FDCWD, path, AT_SYMLINK_NOFOLLOW,
\t\t    0x00040800U /* STATX_BTIME|STATX_PTIME */, stxbuf) == 0) {
\t\tuint32 mask;
\t\tmemcpy(&mask, stxbuf, 4);
\t\t/* Prefer ptime if available */
\t\tif (mask & 0x00040000U) { /* STATX_PTIME */
\t\t\tint64 ptime_sec;
\t\t\tmemcpy(&ptime_sec, stxbuf + 0xC0, 8);
\t\t\tif (ptime_sec)
\t\t\t\treturn (time_t)ptime_sec;
\t\t}
\t\t/* Fall back to btime */
\t\tif (mask & 0x00000800U) { /* STATX_BTIME */
\t\t\tint64 btime_sec;
\t\t\tmemcpy(&btime_sec, stxbuf + 0x50, 8);
\t\t\treturn (time_t)btime_sec;
\t\t}
\t}
\treturn 0;
#else
#error Unknown crtimes implementation
#endif
}'''

if old_get in content:
    content = content.replace(old_get, new_get)
    print("  get_create_time: OK")
else:
    print("  ERROR: get_create_time not found"); sys.exit(1)

# Add do_set_ptime_linux helper function after the SUPPORT_CRTIMES get_create_time block
# Find a good insertion point — after the Cygwin do_SetFileTime block or after get_create_time
insert_marker = '#endif /* HAVE_SETATTRLIST */'
if insert_marker not in content:
    # Try alternate marker
    insert_marker = '#endif\n\n#ifdef SUPPORT_CRTIMES\ntime_t get_create_time'
    
# Add the Linux helper before the end of the file but after existing crtime functions
# Simple approach: add right before the last #endif or at end of SUPPORT_CRTIMES section
linux_helper = '''
#if defined SUPPORT_CRTIMES && defined __linux__
int do_set_ptime_linux(const char *path, time_t crtime)
{
\tchar fa[40];
\tint64_t ps = (int64_t)crtime;

\tif (dry_run) return 0;
\tRETURN_ERROR_IF_RO_OR_LO;

\tmemset(fa, 0, 40);
\tmemcpy(fa + 24, &ps, 8);
\t/* file_setattr syscall 469, struct size 40 (VER1 with ptime) */
\treturn syscall(469 /* SYS_file_setattr */, AT_FDCWD, path,
\t\t       fa, (size_t)40, AT_SYMLINK_NOFOLLOW);
}
#endif
'''

# Find end of get_create_time function and add after it
idx = content.find('Unknown crtimes implementation')
if idx >= 0:
    # Find the closing #endif and } after it
    idx2 = content.find('\n}\n', idx)
    if idx2 >= 0:
        content = content[:idx2+3] + linux_helper + content[idx2+3:]
        print("  do_set_ptime_linux helper: OK")
    else:
        print("  WARNING: Could not find insertion point for helper")

open(path, 'w').write(content)

# 3. rsync.c — Add Linux case to set_file_attrs
print("[3/3] Patching rsync.c...")
path = f'{base}/rsync.c'
content = open(path).read()

# Add includes
if '#include <sys/syscall.h>' not in content:
    content = content.replace('#include "rsync.h"',
        '#include "rsync.h"\n#ifdef __linux__\n#include <sys/syscall.h>\n#endif')

old_set = '''#elif defined __CYGWIN__
\t\t\t     do_SetFileTime(fname, file_crtime) == 0
#else
#error Unknown crtimes implementation
#endif
\t\t)
\t\t\t\tupdated |= UPDATED_CRTIME;'''

new_set = '''#elif defined __CYGWIN__
\t\t\t     do_SetFileTime(fname, file_crtime) == 0
#elif defined __linux__
\t\t\t     do_set_ptime_linux(fname, file_crtime) == 0
#else
#error Unknown crtimes implementation
#endif
\t\t)
\t\t\t\tupdated |= UPDATED_CRTIME;'''

if old_set in content:
    content = content.replace(old_set, new_set)
    print("  set_file_attrs: OK")
else:
    print("  ERROR: set block not found")
    # Debug
    idx = content.find('do_SetFileTime')
    if idx >= 0:
        print(f"  Found do_SetFileTime at {idx}")
        print(f"  Context: {repr(content[idx-20:idx+200])}")
    sys.exit(1)

open(path, 'w').write(content)
print("\nDone.")
