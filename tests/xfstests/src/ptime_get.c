// SPDX-License-Identifier: GPL-2.0
/*
 * ptime_get - Read provenance time (ptime) from a file via statx
 *
 * Usage: ptime_get <file>
 *   Prints "<sec> <nsec>" to stdout.
 *   If ptime is not set or not supported, prints "0 0".
 *   Exit code 0 on success, 1 if statx fails, 2 if ptime not in mask.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/syscall.h>
#include <stdint.h>

#ifndef STATX_PTIME
#define STATX_PTIME 0x00040000U
#endif

#ifndef STATX_BTIME
#define STATX_BTIME 0x00000800U
#endif

#ifndef __NR_statx
#define __NR_statx 332
#endif

struct ptime_statx_ts { int64_t tv_sec; uint32_t tv_nsec; int32_t __reserved; };
struct ptime_statx {
	uint32_t stx_mask; uint32_t stx_blksize;
	uint64_t stx_attributes;
	uint32_t stx_nlink; uint32_t stx_uid; uint32_t stx_gid;
	uint16_t stx_mode; uint16_t __spare0[1];
	uint64_t stx_ino; uint64_t stx_size; uint64_t stx_blocks;
	uint64_t stx_attributes_mask;
	struct ptime_statx_ts stx_atime, stx_btime, stx_ctime, stx_mtime;
	uint32_t stx_rdev_major, stx_rdev_minor, stx_dev_major, stx_dev_minor;
	uint64_t stx_mnt_id;
	uint32_t stx_dio_mem_align, stx_dio_offset_align;
	uint64_t stx_subvol;
	uint32_t stx_atomic_write_unit_min, stx_atomic_write_unit_max;
	uint32_t stx_atomic_write_segments_max, stx_dio_read_offset_align;
	uint32_t stx_atomic_write_unit_max_opt;
	uint32_t __spare2[1];
	struct ptime_statx_ts stx_ptime;
	uint64_t __spare3[6];
};

int main(int argc, char *argv[])
{
	struct ptime_statx stx;
	int ret;

	if (argc < 2) {
		fprintf(stderr, "Usage: %s <file>\n", argv[0]);
		return 1;
	}

	memset(&stx, 0, sizeof(stx));
	ret = syscall(__NR_statx, AT_FDCWD, argv[1], 0,
		      STATX_PTIME | STATX_BTIME, &stx);
	if (ret != 0) {
		fprintf(stderr, "statx(%s): %s\n", argv[1], strerror(errno));
		return 1;
	}

	if (!(stx.stx_mask & STATX_PTIME)) {
		printf("0 0\n");
		return 2;
	}

	printf("%lld %u\n", (long long)stx.stx_ptime.tv_sec,
	       stx.stx_ptime.tv_nsec);
	return 0;
}
