// SPDX-License-Identifier: GPL-2.0
/*
 * ptime_set - Set provenance time (ptime) on a file via file_setattr
 *
 * Usage: ptime_set <file> <epoch_sec> [nsec]
 *   Sets ptime to the given epoch seconds (and optional nanoseconds).
 *   Only ptime is modified; atime/mtime/xflags are not touched.
 *
 * Uses file_setattr syscall (469) with struct file_attr VER1 (40 bytes).
 * ptime_sec at offset 24, ptime_nsec at offset 32, ptime_pad at offset 36.
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

#ifndef SYS_file_setattr
#define SYS_file_setattr 469
#endif

int main(int argc, char *argv[])
{
	const char *path;
	int64_t sec = 0;
	uint32_t nsec = 0;
	char fa[40];
	int ret;

	if (argc < 3) {
		fprintf(stderr, "Usage: %s <file> <epoch_sec> [nsec]\n", argv[0]);
		return 1;
	}

	path = argv[1];
	sec = atol(argv[2]);
	if (argc >= 4)
		nsec = (uint32_t)atol(argv[3]);

	/* Build file_attr VER1 struct: zero VER0 fields, set ptime */
	memset(fa, 0, 40);
	memcpy(fa + 24, &sec, 8);   /* fa_ptime_sec */
	memcpy(fa + 32, &nsec, 4);  /* fa_ptime_nsec */

	ret = syscall(SYS_file_setattr, AT_FDCWD, path, fa, (size_t)40, 0);
	if (ret != 0) {
		fprintf(stderr, "file_setattr(%s, ptime=%ld.%09u): %s\n",
			path, (long)sec, nsec, strerror(errno));
		return 1;
	}
	return 0;
}
