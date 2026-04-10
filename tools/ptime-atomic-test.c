#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/syscall.h>
#include <stdint.h>
#include <errno.h>

#define AT_UTIME_PTIME 0x20000
#define MY_STATX_PTIME 0x00040000U
#define MY_STATX_BTIME 0x00000800U
#define MY_UTIME_OMIT ((1L << 30) - 2L)

struct my_statx_ts { int64_t tv_sec; uint32_t tv_nsec; int32_t __reserved; };
struct my_statx {
    uint32_t stx_mask; uint32_t stx_blksize;
    uint64_t stx_attributes;
    uint32_t stx_nlink; uint32_t stx_uid; uint32_t stx_gid;
    uint16_t stx_mode; uint16_t __spare0[1];
    uint64_t stx_ino; uint64_t stx_size; uint64_t stx_blocks;
    uint64_t stx_attributes_mask;
    struct my_statx_ts stx_atime, stx_btime, stx_ctime, stx_mtime;
    uint32_t stx_rdev_major, stx_rdev_minor, stx_dev_major, stx_dev_minor;
    uint64_t stx_mnt_id;
    uint32_t stx_dio_mem_align, stx_dio_offset_align;
    uint64_t stx_subvol;
    uint32_t stx_atomic_write_unit_min, stx_atomic_write_unit_max;
    uint32_t stx_atomic_write_segments_max, stx_dio_read_offset_align;
    uint32_t stx_atomic_write_unit_max_opt;
    uint32_t __spare2[1];
    struct my_statx_ts stx_ptime;
    uint64_t __spare3[6];
};

#ifndef __NR_statx
#define __NR_statx 332
#endif

static int64_t read_ptime(const char *path) {
    struct my_statx stx = {};
    if (syscall(__NR_statx, AT_FDCWD, path, 0, MY_STATX_PTIME, &stx) != 0)
        return -1;
    if (!(stx.stx_mask & MY_STATX_PTIME))
        return 0;
    return stx.stx_ptime.tv_sec;
}

static int set_ptime(const char *path, int64_t sec) {
    struct timespec times[3];
    times[0].tv_nsec = MY_UTIME_OMIT;
    times[1].tv_nsec = MY_UTIME_OMIT;
    times[2].tv_sec = sec;
    times[2].tv_nsec = 0;
    return syscall(SYS_utimensat, AT_FDCWD, path, times, AT_UTIME_PTIME);
}

int main(void) {
    const char *original = "/home/sean/ptime-atomic-original.txt";
    const char *tmpfile  = "/home/sean/ptime-atomic-original.txt.tmp";
    int fd;

    printf("=== PTIME ATOMIC SAVE TEST ===\n\n");

    /* Step 1: Create original file and set ptime */
    fd = open(original, O_CREAT | O_WRONLY | O_TRUNC, 0644);
    write(fd, "original content\n", 17);
    close(fd);

    if (set_ptime(original, 1560608400) != 0) {
        perror("set_ptime");
        return 1;
    }
    printf("1. Created '%s' with ptime = 2019-06-15\n", original);
    printf("   ptime before atomic save: %lld\n\n", (long long)read_ptime(original));

    /* Step 2: Simulate atomic save (what LibreOffice/Vim/Kate do) */
    printf("2. Simulating atomic save:\n");
    printf("   - Writing new content to .tmp file\n");
    fd = open(tmpfile, O_CREAT | O_WRONLY | O_TRUNC, 0644);
    write(fd, "modified content after edit\n", 27);
    close(fd);

    printf("   - .tmp file ptime: %lld (should be 0 = unset)\n", (long long)read_ptime(tmpfile));

    printf("   - rename(.tmp -> original)  [this is the atomic save]\n");
    if (rename(tmpfile, original) != 0) {
        perror("rename");
        return 1;
    }

    /* Step 3: Check if ptime survived */
    int64_t ptime_after = read_ptime(original);
    printf("\n3. After atomic save:\n");
    printf("   ptime: %lld\n", (long long)ptime_after);

    if (ptime_after == 1560608400) {
        printf("\n");
        printf("*********************************************\n");
        printf("***  ATOMIC SAVE: PTIME PRESERVED!        ***\n");
        printf("***  LibreOffice/Vim/Kate saves will work  ***\n");
        printf("***  This is what xattr could NEVER do     ***\n");
        printf("*********************************************\n");
    } else if (ptime_after == 0) {
        printf("\n*** FAIL: ptime was lost during atomic save ***\n");
        printf("*** The rename-over preservation did not work ***\n");
    } else {
        printf("\n*** UNEXPECTED: ptime = %lld (not 0 and not expected) ***\n",
               (long long)ptime_after);
    }

    unlink(original);
    return 0;
}
