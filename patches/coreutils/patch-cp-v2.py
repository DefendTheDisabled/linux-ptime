#!/usr/bin/env python3
"""Patch coreutils cp to preserve ptime - v3 (file_setattr API)"""
import sys

path = sys.argv[1] if len(sys.argv) > 1 else 'src/copy.c'
content = open(path).read()

# 1. Add includes
include_anchor = '#include <sys/xattr.h>'
if include_anchor in content and '#include <sys/syscall.h>' not in content:
    content = content.replace(include_anchor,
        include_anchor + '\n#include <sys/syscall.h>')
    print("Added sys/syscall.h include")

# 2. Add ptime block after the timestamp preservation code
old_block = '''      if (fdutimensat (dest_desc, dst_dirfd, dst_relname, timespec, 0) != 0)
        {
          error (0, errno, _("preserving times for %s"), quoteaf (dst_name));
          if (x->require_preserve)
            {
              return_val = false;
              goto close_src_and_dst_desc;
            }
        }
    }'''

new_block = '''      if (fdutimensat (dest_desc, dst_dirfd, dst_relname, timespec, 0) != 0)
        {
          error (0, errno, _("preserving times for %s"), quoteaf (dst_name));
          if (x->require_preserve)
            {
              return_val = false;
              goto close_src_and_dst_desc;
            }
        }

      /* Preserve provenance time (ptime) if the source has it.
         Read via statx, write via file_setattr (syscall 469). */
      {
        struct statx stx;
        if (statx (AT_FDCWD, src_name, AT_SYMLINK_NOFOLLOW,
                   0x00040000U /* STATX_PTIME */, &stx) == 0
            && (stx.stx_mask & 0x00040000U))
          {
            struct statx_timestamp *stp = (struct statx_timestamp *)
              ((char *) &stx + 0xC0);
            if (stp->tv_sec || stp->tv_nsec)
              {
                /* Write ptime via file_setattr (syscall 469) */
                char fa[40];
                memset (fa, 0, 40);
                memcpy (fa + 24, &stp->tv_sec, 8);
                memcpy (fa + 32, &stp->tv_nsec, 4);
                syscall (469 /* SYS_file_setattr */, dst_dirfd, dst_relname,
                         fa, (size_t)40, 0);
              }
          }
      }
    }'''

if old_block in content:
    content = content.replace(old_block, new_block, 1)
    print("Patched timestamp preservation block: OK")
else:
    print("ERROR: Could not find timestamp block")
    idx = content.find('fdutimensat (dest_desc')
    if idx >= 0:
        print(f"Found fdutimensat at position {idx}")
        print("Context:")
        print(repr(content[idx-50:idx+300]))
    sys.exit(1)

open(path, 'w').write(content)
print("Done.")
