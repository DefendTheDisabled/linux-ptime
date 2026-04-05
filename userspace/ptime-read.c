#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/syscall.h>
#include <stdint.h>
#include <time.h>

#define MY_STATX_PTIME 0x00040000U
#define MY_STATX_BTIME 0x00000800U

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

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: ptime-read <file> [file2 ...]\n");
        return 1;
    }
    for (int i = 1; i < argc; i++) {
        struct my_statx stx = {};
        int ret = syscall(__NR_statx, AT_FDCWD, argv[i], 0,
                          MY_STATX_PTIME | MY_STATX_BTIME, &stx);
        if (ret != 0) {
            perror(argv[i]);
            continue;
        }
        printf("%s:\n", argv[i]);
        printf("  btime: %lld.%09u", (long long)stx.stx_btime.tv_sec, stx.stx_btime.tv_nsec);
        if (stx.stx_btime.tv_sec) {
            time_t t = stx.stx_btime.tv_sec;
            struct tm *tm = gmtime(&t);
            printf("  (%04d-%02d-%02dT%02d:%02d:%02dZ)",
                   tm->tm_year+1900, tm->tm_mon+1, tm->tm_mday,
                   tm->tm_hour, tm->tm_min, tm->tm_sec);
        }
        printf("\n");
        if (stx.stx_mask & MY_STATX_PTIME) {
            printf("  ptime: %lld.%09u", (long long)stx.stx_ptime.tv_sec, stx.stx_ptime.tv_nsec);
            time_t t = stx.stx_ptime.tv_sec;
            struct tm *tm = gmtime(&t);
            printf("  (%04d-%02d-%02dT%02d:%02d:%02dZ)",
                   tm->tm_year+1900, tm->tm_mon+1, tm->tm_mday,
                   tm->tm_hour, tm->tm_min, tm->tm_sec);
            printf("\n");
        } else {
            printf("  ptime: (not set)\n");
        }
    }
    return 0;
}
