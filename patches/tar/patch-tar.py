#!/usr/bin/env python3
"""Patch GNU tar to preserve ptime via SCHILY.ptime PAX header — v2 (file_setattr)"""
import sys

base = sys.argv[1] if len(sys.argv) > 1 else '.'

# 1. tar.h — Add ptime field to tar_stat_info
print("[1/4] Patching tar.h...")
path = f'{base}/src/tar.h'
content = open(path).read()

content = content.replace(
    '  struct timespec ctime;\n',
    '  struct timespec ctime;\n  struct timespec ptime;    /* provenance time */\n'
)
open(path, 'w').write(content)
print("  Added ptime to tar_stat_info: OK")

# 2. xheader.c — Add ptime coder, decoder, and keyword registration
print("[2/4] Patching xheader.c (coder/decoder)...")
path = f'{base}/src/xheader.c'
content = open(path).read()

# Add ptime_coder and ptime_decoder after ctime_decoder
ctime_decoder_end = '''static void
ctime_decoder (struct tar_stat_info *st,
	       char const *keyword,
	       char const *arg,
	       MAYBE_UNUSED size_t size)
{
  struct timespec ts;
  if (decode_time (&ts, arg, keyword))
    st->ctime = ts;
}'''

ptime_funcs = '''static void
ctime_decoder (struct tar_stat_info *st,
	       char const *keyword,
	       char const *arg,
	       MAYBE_UNUSED size_t size)
{
  struct timespec ts;
  if (decode_time (&ts, arg, keyword))
    st->ctime = ts;
}

static void
ptime_coder (struct tar_stat_info const *st, char const *keyword,
	     struct xheader *xhdr, MAYBE_UNUSED void const *data)
{
  if (st->ptime.tv_sec || st->ptime.tv_nsec)
    code_time (st->ptime, keyword, xhdr);
}

static void
ptime_decoder (struct tar_stat_info *st,
	       char const *keyword,
	       char const *arg,
	       MAYBE_UNUSED size_t size)
{
  struct timespec ts;
  if (decode_time (&ts, arg, keyword))
    st->ptime = ts;
}'''

if ctime_decoder_end in content:
    content = content.replace(ctime_decoder_end, ptime_funcs)
    print("  Added ptime_coder/decoder: OK")
else:
    print("  ERROR: Could not find ctime_decoder")
    sys.exit(1)

# Add keyword registration — after mtime entry
old_mtime_kw = '  { "mtime",    mtime_coder,    mtime_decoder,    0, false },'
new_mtime_kw = '  { "mtime",    mtime_coder,    mtime_decoder,    0, false },\n  { "SCHILY.ptime", ptime_coder, ptime_decoder,  0, false },'

if old_mtime_kw in content:
    content = content.replace(old_mtime_kw, new_mtime_kw)
    print("  Registered SCHILY.ptime keyword: OK")
else:
    print("  ERROR: Could not find mtime keyword entry")
    sys.exit(1)

open(path, 'w').write(content)

# 3. create.c — Read ptime from source file via statx when creating archive
print("[3/4] Patching create.c (read ptime on archive creation)...")
path = f'{base}/src/create.c'
content = open(path).read()

# Find where atime/mtime/ctime are read from stat and add ptime via statx
# Look for where st->atime or st->ctime is set from the stat buffer
atime_set = 'st->atime = get_stat_atime (&st->stat);'
if atime_set in content:
    ptime_read = '''st->atime = get_stat_atime (&st->stat);

  /* Read provenance time via raw statx syscall */
  st->ptime.tv_sec = 0;
  st->ptime.tv_nsec = 0;
#ifdef __linux__
  {
    char stxbuf[256];
    memset (stxbuf, 0, 256);
    if (fd > 0 &&
        syscall (SYS_statx, fd, "", AT_EMPTY_PATH,
                 0x00040000U /* STATX_PTIME */, stxbuf) == 0)
      {
        uint32_t mask;
        memcpy (&mask, stxbuf, 4);
        if (mask & 0x00040000U)
          {
            int64_t ps;
            int32_t pn;
            memcpy (&ps, stxbuf + 0xC0, 8);
            memcpy (&pn, stxbuf + 0xC8, 4);
            st->ptime.tv_sec = ps;
            st->ptime.tv_nsec = pn;
          }
      }
  }
#endif'''
    content = content.replace(atime_set, ptime_read)
    print("  Added ptime reading on create: OK")
else:
    print("  WARNING: Could not find atime assignment in create.c")
    # Try alternate pattern
    print("  Searching for alternate patterns...")
    import re
    m = re.search(r'st->atime\s*=.*stat.*atime', content)
    if m:
        print(f"  Found at: {m.group()}")

# Add includes
if '#include <sys/syscall.h>' not in content:
    content = content.replace('#include "common.h"',
        '#include "common.h"\n#ifdef __linux__\n#include <sys/syscall.h>\n#include <stdint.h>\n#endif')
    print("  Added includes: OK")

open(path, 'w').write(content)

# 4. extract.c — Write ptime to extracted file via file_setattr
print("[4/4] Patching extract.c (write ptime on extraction)...")
path = f'{base}/src/extract.c'
content = open(path).read()

# Add includes
if '#include <sys/syscall.h>' not in content:
    content = content.replace('#include "common.h"',
        '#include "common.h"\n#ifdef __linux__\n#include <sys/syscall.h>\n#include <stdint.h>\n#endif')
    print("  Added includes: OK")

# Find the timestamp restoration error handler and add ptime block after it
# Pattern: after utime_error(file_name), add ptime restore before the closing brace
utime_anchor = '      else if (typeflag != SYMTYPE || implemented (errno))\n\tutime_error (file_name);'
if utime_anchor in content:
    ptime_extract = utime_anchor + '''

      /* Restore provenance time if present in archive */
#ifdef __linux__
      if (st->ptime.tv_sec || st->ptime.tv_nsec)
        {
          /* Write ptime via file_setattr (syscall 469) */
          char fa[40];
          int64_t ps = st->ptime.tv_sec;
          uint32_t pn = (uint32_t)st->ptime.tv_nsec;
          memset (fa, 0, 40);
          memcpy (fa + 24, &ps, 8);
          memcpy (fa + 32, &pn, 4);
          syscall (469 /* SYS_file_setattr */, chdir_fd, file_name,
                   fa, (size_t)40, atflag);
        }
#endif'''
    content = content.replace(utime_anchor, ptime_extract)
    print("  Added ptime extract block: OK")
else:
    print("  WARNING: Could not find utime_error anchor in extract.c")
    print("  Searching for alternate patterns...")
    import re
    m = re.search(r'utime_error.*file_name', content)
    if m:
        print(f"  Found utime_error at: {m.group()[:80]}")

open(path, 'w').write(content)

print("\nDone. Build and test with: makepkg -ef --nocheck --noconfirm")
