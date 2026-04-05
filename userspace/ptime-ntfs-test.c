#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/syscall.h>
#include <stdint.h>
#include <errno.h>
#include <time.h>

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

static void read_times(const char *path, const char *label) {
    struct my_statx stx = {};
    if (syscall(__NR_statx, AT_FDCWD, path, 0,
                MY_STATX_PTIME | MY_STATX_BTIME, &stx) != 0) {
        printf("  %s: statx failed: %s\n", label, strerror(errno));
        return;
    }
    time_t bt = stx.stx_btime.tv_sec;
    struct tm *btm = gmtime(&bt);
    printf("  %s:\n", label);
    printf("    btime: %lld (%04d-%02d-%02d)\n", (long long)stx.stx_btime.tv_sec,
           btm->tm_year+1900, btm->tm_mon+1, btm->tm_mday);
    if (stx.stx_mask & MY_STATX_PTIME) {
        time_t pt = stx.stx_ptime.tv_sec;
        struct tm *ptm = gmtime(&pt);
        printf("    ptime: %lld (%04d-%02d-%02d) [STATX_PTIME set]\n",
               (long long)stx.stx_ptime.tv_sec,
               ptm->tm_year+1900, ptm->tm_mon+1, ptm->tm_mday);
    } else {
        printf("    ptime: (not set)\n");
    }
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
    const char *btrfs_file = "/home/sean/ptime-ntfs-test.txt";
    const char *ntfs_file = "/mnt/main-storage/ptime-ntfs-test.txt";
    int fd;

    printf("=== PTIME NTFS ROUND-TRIP TEST ===\n\n");

    /* Test 1: Set ptime on Btrfs, read it back */
    printf("TEST 1: Set ptime on Btrfs file\n");
    fd = open(btrfs_file, O_CREAT | O_WRONLY | O_TRUNC, 0644);
    if (fd < 0) { perror("create btrfs file"); return 1; }
    write(fd, "btrfs ptime test\n", 17);
    close(fd);
    if (set_ptime(btrfs_file, 1560608400) != 0) {
        perror("set ptime on btrfs");
        return 1;
    }
    read_times(btrfs_file, "Btrfs file");

    /* Test 2: Set ptime on NTFS file (should set NTFS creation time) */
    printf("\nTEST 2: Set ptime on NTFS file\n");
    fd = open(ntfs_file, O_CREAT | O_WRONLY | O_TRUNC, 0644);
    if (fd < 0) {
        printf("  Cannot create NTFS file at %s: %s\n", ntfs_file, strerror(errno));
        printf("  (Is /mnt/main-storage mounted? Check mount options)\n");
        goto cleanup;
    }
    write(fd, "ntfs ptime test\n", 16);
    close(fd);

    printf("  Created NTFS file. Reading NTFS creation time as ptime:\n");
    read_times(ntfs_file, "NTFS file (before ptime set)");

    if (set_ptime(ntfs_file, 1560608400) != 0) {
        printf("  set_ptime on NTFS failed: %s (errno=%d)\n", strerror(errno), errno);
        printf("  This may mean ntfs3 setattr doesn't support ATTR_PTIME yet\n");
        goto cleanup;
    }
    printf("  Set ptime = 2019-06-15 on NTFS file\n");
    read_times(ntfs_file, "NTFS file (after ptime set)");

    /* Test 3: Read NTFS btime — should now equal the ptime we set */
    printf("\nTEST 3: Verify NTFS Date Created changed\n");
    read_times(ntfs_file, "NTFS file Date Created");

    printf("\n");
    struct my_statx stx = {};
    syscall(__NR_statx, AT_FDCWD, ntfs_file, 0, MY_STATX_PTIME | MY_STATX_BTIME, &stx);
    if (stx.stx_btime.tv_sec == 1560608400) {
        printf("*********************************************\n");
        printf("***  NTFS Date Created = 2019-06-15!      ***\n");
        printf("***  ptime -> NTFS creation time WORKS     ***\n");
        printf("***  Windows Explorer will show correct date***\n");
        printf("*********************************************\n");
    } else if ((stx.stx_mask & MY_STATX_PTIME) && stx.stx_ptime.tv_sec == 1560608400) {
        printf("PARTIAL: ptime set correctly but btime unchanged\n");
        printf("  btime still: %lld (NTFS creation time not updated on disk yet)\n",
               (long long)stx.stx_btime.tv_sec);
        printf("  Try: sync && echo 3 | sudo tee /proc/sys/vm/drop_caches\n");
    } else {
        printf("FAIL: Neither btime nor ptime shows 2019-06-15\n");
    }

cleanup:
    unlink(btrfs_file);
    if (access(ntfs_file, F_OK) == 0) unlink(ntfs_file);
    return 0;
}
