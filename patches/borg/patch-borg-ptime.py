#!/usr/bin/env python3
"""
Patch BorgBackup 1.4.4 for ptime (provenance_time) support.
CP-1: borgbackup-ptime

Adds:
- ptime capture via statx(STATX_PTIME) during backup
- ptime restore via file_setattr(syscall 469) during extract
- Linux birthtime capture via statx (fixes Borg #9251)
- --noptime flag for create and extract
- ptime PropDict registration in Item schema
"""
import os
import sys

BORG_SRC = os.path.expanduser('~/pkgsrc/borg/src/borgbackup-1.4.4/src/borg')

def read_file(relpath):
    path = os.path.join(BORG_SRC, relpath)
    with open(path, 'r') as f:
        return f.read()

def write_file(relpath, content):
    path = os.path.join(BORG_SRC, relpath)
    with open(path, 'w') as f:
        f.write(content)
    print(f'  Patched {relpath}')

def ensure_replace(content, old, new, filename, label):
    if old not in content:
        print(f'  WARNING: Could not find target in {filename} for: {label}')
        print(f'  Searched for: {repr(old[:80])}...')
        return content
    return content.replace(old, new)


# ===================================================================
# 1. constants.py - Add 'ptime' to ITEM_KEYS
# ===================================================================
def patch_constants():
    content = read_file('constants.py')
    if "'ptime'" in content:
        print('  constants.py: already patched')
        return
    content = ensure_replace(content,
        "'birthtime', 'size'",
        "'birthtime', 'ptime', 'size'",
        'constants.py', 'ITEM_KEYS ptime')
    write_file('constants.py', content)


# ===================================================================
# 2. item.pyx - Add ptime PropDict property
# ===================================================================
def patch_item():
    content = read_file('item.pyx')
    if 'ptime = PropDict' in content:
        print('  item.pyx: already patched')
        return
    content = ensure_replace(content,
        "    birthtime = PropDict._make_property('birthtime', int, 'bigint', encode=int_to_bigint, decode=bigint_to_int)",
        "    birthtime = PropDict._make_property('birthtime', int, 'bigint', encode=int_to_bigint, decode=bigint_to_int)\n"
        "    ptime = PropDict._make_property('ptime', int, 'bigint', encode=int_to_bigint, decode=bigint_to_int)",
        'item.pyx', 'ptime property')
    write_file('item.pyx', content)


# ===================================================================
# 3. platform/linux.pyx - Add get_ptime, set_ptime, get_birthtime_linux
# ===================================================================
def patch_linux_pyx():
    content = read_file('platform/linux.pyx')
    if 'get_ptime' in content:
        print('  platform/linux.pyx: already patched')
        return

    ptime_code = r'''

# ===================================================================
# ptime (provenance_time) support -- CP-1 borgbackup-ptime
# ===================================================================

from libc.string cimport memset, memcpy
from libc.stdint cimport uint32_t

cdef extern from "unistd.h":
    long syscall(long number, ...) nogil

cdef extern from "fcntl.h":
    int AT_FDCWD
    int AT_SYMLINK_NOFOLLOW
    int AT_EMPTY_PATH

# Syscall numbers (x86_64)
DEF SYS_statx = 332
DEF SYS_file_setattr = 469

# statx masks and offsets
DEF STATX_PTIME = 0x00040000
DEF STATX_BTIME = 0x00000800
DEF STX_MASK_OFFSET = 0x00
DEF STX_BTIME_OFFSET = 0x50
DEF STX_PTIME_OFFSET = 0xC0
DEF STATX_BUF_SIZE = 256

# struct file_attr VER1 offsets (VER0 base = 24 bytes, ptime ext = 16 bytes)
DEF FA_PTIME_SEC_OFFSET = 24
DEF FA_PTIME_NSEC_OFFSET = 32
DEF FA_PTIME_PAD_OFFSET = 36
DEF FA_SIZE_VER1 = 40


def get_ptime(path, fd=None):
    """Read ptime via statx. Returns ns (int) or None."""
    cdef char buf[STATX_BUF_SIZE]
    cdef int ret, cfd
    cdef int64_t sec
    cdef uint32_t nsec, stx_mask
    cdef const char* c_path = ""

    memset(buf, 0, sizeof(buf))

    if fd is not None:
        cfd = <int>fd
        with nogil:
            ret = <int>syscall(SYS_statx, cfd, c_path,
                               AT_EMPTY_PATH, STATX_PTIME, buf)
    else:
        path_bytes = os.fsencode(path)
        c_path = path_bytes
        with nogil:
            ret = <int>syscall(SYS_statx, AT_FDCWD, c_path,
                               AT_SYMLINK_NOFOLLOW, STATX_PTIME, buf)

    if ret != 0:
        return None

    memcpy(&stx_mask, buf + STX_MASK_OFFSET, sizeof(stx_mask))
    if not (stx_mask & STATX_PTIME):
        return None

    memcpy(&sec, buf + STX_PTIME_OFFSET, sizeof(sec))
    memcpy(&nsec, buf + STX_PTIME_OFFSET + 8, sizeof(nsec))
    if sec == 0 and nsec == 0:
        return None
    return sec * 1000000000 + nsec


def get_birthtime_linux(path, fd=None):
    """Read birthtime on Linux via statx. Returns ns (int) or None.
    Fixes Borg issue #9251.
    """
    cdef char buf[STATX_BUF_SIZE]
    cdef int ret, cfd
    cdef int64_t sec
    cdef uint32_t nsec, stx_mask
    cdef const char* c_path = ""

    memset(buf, 0, sizeof(buf))

    if fd is not None:
        cfd = <int>fd
        with nogil:
            ret = <int>syscall(SYS_statx, cfd, c_path,
                               AT_EMPTY_PATH, STATX_BTIME, buf)
    else:
        path_bytes = os.fsencode(path)
        c_path = path_bytes
        with nogil:
            ret = <int>syscall(SYS_statx, AT_FDCWD, c_path,
                               AT_SYMLINK_NOFOLLOW, STATX_BTIME, buf)

    if ret != 0:
        return None

    memcpy(&stx_mask, buf + STX_MASK_OFFSET, sizeof(stx_mask))
    if not (stx_mask & STATX_BTIME):
        return None

    memcpy(&sec, buf + STX_BTIME_OFFSET, sizeof(sec))
    memcpy(&nsec, buf + STX_BTIME_OFFSET + 8, sizeof(nsec))
    return sec * 1000000000 + nsec


def set_ptime(path, ptime_ns, fd=None):
    """Set ptime via file_setattr syscall (469). Raises OSError on failure."""
    cdef char fa[FA_SIZE_VER1]
    cdef int ret, cfd
    cdef int64_t sec
    cdef uint32_t nsec
    cdef const char* c_path = ""

    sec = ptime_ns // 1000000000
    nsec = ptime_ns % 1000000000

    memset(fa, 0, sizeof(fa))
    memcpy(fa + FA_PTIME_SEC_OFFSET, &sec, sizeof(sec))
    memcpy(fa + FA_PTIME_NSEC_OFFSET, &nsec, sizeof(nsec))

    if fd is not None:
        cfd = <int>fd
        with nogil:
            ret = <int>syscall(SYS_file_setattr, cfd, c_path,
                               fa, <size_t>FA_SIZE_VER1, AT_EMPTY_PATH)
    else:
        path_bytes = os.fsencode(path)
        c_path = path_bytes
        with nogil:
            ret = <int>syscall(SYS_file_setattr, AT_FDCWD, c_path,
                               fa, <size_t>FA_SIZE_VER1, 0)

    if ret != 0:
        raise OSError(errno.errno, os.strerror(errno.errno), path)
'''
    content += ptime_code
    write_file('platform/linux.pyx', content)


# ===================================================================
# 4. platform/__init__.py - Export ptime functions, fix birthtime
# ===================================================================
def patch_platform_init():
    content = read_file('platform/__init__.py')
    if 'get_ptime' in content:
        print('  platform/__init__.py: already patched')
        return

    # Add ptime imports in the is_linux block
    content = ensure_replace(content,
        '    from .linux import SyncFile',
        '    from .linux import SyncFile\n'
        '    from .linux import get_ptime, set_ptime, get_birthtime_linux',
        'platform/__init__.py', 'linux ptime imports')

    # Replace get_birthtime_ns to add Linux statx fallback
    content = ensure_replace(content,
        '    else:\n'
        '        return None',
        '    elif is_linux:\n'
        '        # Linux fallback: use statx to read stx_btime (fixes #9251)\n'
        '        try:\n'
        '            return get_birthtime_linux(path, fd=fd)\n'
        '        except Exception:\n'
        '            return None\n'
        '    else:\n'
        '        return None',
        'platform/__init__.py', 'birthtime Linux fallback')

    # Add non-Linux stubs at end
    content += '''
# ptime stubs for non-Linux platforms
if not is_linux:
    def get_ptime(path, fd=None):
        return None

    def set_ptime(path, ptime_ns, fd=None):
        pass

    def get_birthtime_linux(path, fd=None):
        return None
'''
    write_file('platform/__init__.py', content)


# ===================================================================
# 5. archive.py - Capture ptime + restore ptime
# ===================================================================
def patch_archive():
    content = read_file('archive.py')
    if 'get_ptime' in content:
        print('  archive.py: already patched')
        return

    # Add import for get_ptime, set_ptime
    content = ensure_replace(content,
        'from .platform import uid2user, user2uid, gid2group, group2gid, get_birthtime_ns',
        'from .platform import uid2user, user2uid, gid2group, group2gid, get_birthtime_ns, get_ptime, set_ptime',
        'archive.py', 'ptime imports')

    # Add noptime to MetadataCollector.__init__
    content = ensure_replace(content,
        'def __init__(self, *, noatime, noctime, nobirthtime, numeric_ids, noflags, noacls, noxattrs):',
        'def __init__(self, *, noatime, noctime, nobirthtime, noptime=False, numeric_ids, noflags, noacls, noxattrs):',
        'archive.py', 'MetadataCollector noptime param')

    content = ensure_replace(content,
        '        self.nobirthtime = nobirthtime',
        '        self.nobirthtime = nobirthtime\n'
        '        self.noptime = noptime',
        'archive.py', 'MetadataCollector noptime assignment')

    # Add ptime capture after birthtime capture in stat_simple_attrs
    content = ensure_replace(content,
        "        if not self.nobirthtime:\n"
        "            birthtime_ns = get_birthtime_ns(st, path, fd=fd)\n"
        "            if birthtime_ns is not None:\n"
        "                attrs['birthtime'] = safe_ns(birthtime_ns)",
        "        if not self.nobirthtime:\n"
        "            birthtime_ns = get_birthtime_ns(st, path, fd=fd)\n"
        "            if birthtime_ns is not None:\n"
        "                attrs['birthtime'] = safe_ns(birthtime_ns)\n"
        "        if not self.noptime:\n"
        "            ptime_ns = get_ptime(path, fd=fd)\n"
        "            if ptime_ns is not None:\n"
        "                attrs['ptime'] = safe_ns(ptime_ns)",
        'archive.py', 'ptime capture in stat_simple_attrs')

    # Add noptime to Archive.__init__ (use unique context to avoid matching MetadataCollector)
    content = ensure_replace(content,
        '                 noflags=False, noacls=False, noxattrs=False,',
        '                 noflags=False, noacls=False, noxattrs=False, noptime=False,',
        'archive.py', 'Archive.__init__ noptime param')

    # Use the assert line as unique context for Archive.__init__ (not present in MetadataCollector)
    content = ensure_replace(content,
        "        self.noxattrs = noxattrs\n"
        "        assert (start is None) == (start_monotonic is None)",
        "        self.noxattrs = noxattrs\n"
        "        self.noptime = noptime\n"
        "        assert (start is None) == (start_monotonic is None)",
        'archive.py', 'Archive.__init__ noptime assignment')

    # Add ptime restore after birthtime restore block
    content = ensure_replace(content,
        "            if 'birthtime' in item:\n"
        "                birthtime = item.birthtime\n"
        "                try:\n"
        "                    # This should work on FreeBSD, NetBSD, and Darwin and be harmless on other platforms.\n"
        "                    # See utimes(2) on either of the BSDs for details.\n"
        "                    if fd:\n"
        "                        os.utime(fd, None, ns=(atime, birthtime))\n"
        "                    else:\n"
        "                        os.utime(path, None, ns=(atime, birthtime), follow_symlinks=False)\n"
        "                except OSError:\n"
        "                    # some systems don't support calling utime on a symlink\n"
        "                    pass",
        "            if 'birthtime' in item:\n"
        "                birthtime = item.birthtime\n"
        "                try:\n"
        "                    # This should work on FreeBSD, NetBSD, and Darwin and be harmless on other platforms.\n"
        "                    # See utimes(2) on either of the BSDs for details.\n"
        "                    if fd:\n"
        "                        os.utime(fd, None, ns=(atime, birthtime))\n"
        "                    else:\n"
        "                        os.utime(path, None, ns=(atime, birthtime), follow_symlinks=False)\n"
        "                except OSError:\n"
        "                    # some systems don't support calling utime on a symlink\n"
        "                    pass\n"
        "            if 'ptime' in item and not self.noptime:\n"
        "                try:\n"
        "                    set_ptime(path, item.ptime, fd=fd)\n"
        "                except OSError:\n"
        "                    pass  # Non-ptime kernel -- graceful skip",
        'archive.py', 'ptime restore in restore_attrs')

    write_file('archive.py', content)


# ===================================================================
# 6. archiver.py - --noptime flag + plumbing
# ===================================================================
def patch_archiver():
    content = read_file('archiver.py')
    if 'noptime' in content:
        print('  archiver.py: already patched')
        return

    # Add --noptime to create fs_group (after --nobirthtime)
    content = ensure_replace(content,
        "        fs_group.add_argument('--nobirthtime', dest='nobirthtime', action='store_true',\n"
        "                              help='do not store birthtime (creation date) into archive')",
        "        fs_group.add_argument('--nobirthtime', dest='nobirthtime', action='store_true',\n"
        "                              help='do not store birthtime (creation date) into archive')\n"
        "        fs_group.add_argument('--noptime', dest='noptime', action='store_true',\n"
        "                              help='do not store provenance time (ptime) into archive')",
        'archiver.py', '--noptime create flag')

    # Add noptime to MetadataCollector call
    content = ensure_replace(content,
        '                    numeric_ids=args.numeric_ids, nobirthtime=args.nobirthtime)',
        "                    numeric_ids=args.numeric_ids, nobirthtime=args.nobirthtime,\n"
        "                    noptime=getattr(args, 'noptime', False))",
        'archiver.py', 'MetadataCollector noptime')

    # Add noptime to with_archive Archive creation (for extract)
    content = ensure_replace(content,
        "                          noxattrs=getattr(args, 'noxattrs', False),\n"
        "                          cache=kwargs.get('cache'),",
        "                          noxattrs=getattr(args, 'noxattrs', False),\n"
        "                          noptime=getattr(args, 'noptime', False),\n"
        "                          cache=kwargs.get('cache'),",
        'archiver.py', 'with_archive noptime')

    # Add --noptime to extract subparser (after last --noxattrs in extract section)
    # The extract section's --noxattrs is the second occurrence in the file
    # Find it by looking for the extract subparser section
    idx = content.find("        subparser.add_argument('--noxattrs', dest='noxattrs', action='store_true',\n"
                       "                               help='do not read and store xattrs into archive')")
    if idx > 0:
        # Find the SECOND occurrence (extract section)
        idx2 = content.find("        subparser.add_argument('--noxattrs', dest='noxattrs', action='store_true',\n"
                           "                               help='do not read and store xattrs into archive')", idx + 1)
        if idx2 > 0:
            target = "        subparser.add_argument('--noxattrs', dest='noxattrs', action='store_true',\n" \
                     "                               help='do not read and store xattrs into archive')"
            replacement = target + "\n" \
                          "        subparser.add_argument('--noptime', dest='noptime', action='store_true',\n" \
                          "                               help='do not restore provenance time (ptime) from archive')"
            # Replace only the second occurrence
            content = content[:idx2] + content[idx2:].replace(target, replacement, 1)
            print('  Added --noptime to extract subparser')
        else:
            print('  WARNING: Could not find second --noxattrs for extract subparser')
    else:
        print('  WARNING: Could not find --noxattrs in archiver.py')

    write_file('archiver.py', content)


# ===================================================================
# Main
# ===================================================================
if __name__ == '__main__':
    print('Patching BorgBackup 1.4.4 for ptime support...')
    print(f'Source: {BORG_SRC}')

    if not os.path.isdir(BORG_SRC):
        print(f'ERROR: {BORG_SRC} does not exist')
        print('Run: cd ~/pkgsrc/borg && makepkg -o --nodeps --skippgpcheck')
        sys.exit(1)

    patch_constants()
    patch_item()
    patch_linux_pyx()
    patch_platform_init()
    patch_archive()
    patch_archiver()

    print('\nDone. Generate patch with:')
    print('  cd ~/pkgsrc/borg')
    print('  diff -ruN src/borgbackup-1.4.4.orig src/borgbackup-1.4.4 > borg-ptime.patch')
