// SPDX-License-Identifier: GPL-2.0
/*
 * ptime_set - Set provenance time (ptime) on a file via utimensat
 *
 * Usage: ptime_set <file> <epoch_sec> [nsec]
 *   Sets ptime to the given epoch seconds (and optional nanoseconds).
 *   atime and mtime are left unchanged (UTIME_OMIT).
 *
 * Usage: ptime_set <file>
 *   Clears ptime by setting it to 0.0 (if supported).
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/syscall.h>

#ifndef AT_UTIME_PTIME
#define AT_UTIME_PTIME 0x20000
#endif

#ifndef UTIME_OMIT
#define UTIME_OMIT ((1L << 30) - 2L)
#endif

int main(int argc, char *argv[])
{
	struct timespec times[3];
	const char *path;
	long sec = 0;
	long nsec = 0;
	int ret;

	if (argc < 3) {
		fprintf(stderr, "Usage: %s <file> <epoch_sec> [nsec]\n", argv[0]);
		return 1;
	}

	path = argv[1];
	sec = atol(argv[2]);
	if (argc >= 4)
		nsec = atol(argv[3]);

	/* UTIME_OMIT for atime and mtime */
	times[0].tv_sec = 0;
	times[0].tv_nsec = UTIME_OMIT;
	times[1].tv_sec = 0;
	times[1].tv_nsec = UTIME_OMIT;
	/* ptime */
	times[2].tv_sec = sec;
	times[2].tv_nsec = nsec;

	ret = syscall(SYS_utimensat, AT_FDCWD, path, times, AT_UTIME_PTIME);
	if (ret != 0) {
		fprintf(stderr, "utimensat(%s, ptime=%ld.%09ld): %s\n",
			path, sec, nsec, strerror(errno));
		return 1;
	}
	return 0;
}
