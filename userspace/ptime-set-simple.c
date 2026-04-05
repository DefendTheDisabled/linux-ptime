#define _GNU_SOURCE
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/syscall.h>
#include <time.h>
#define AT_UTIME_PTIME 0x20000
#define MY_UTIME_OMIT ((1L << 30) - 2L)
int main(int argc, char **argv) {
    struct timespec times[3];
    times[0].tv_nsec = MY_UTIME_OMIT; times[1].tv_nsec = MY_UTIME_OMIT;
    times[2].tv_sec = 1560608400; times[2].tv_nsec = 0;
    int ret = syscall(SYS_utimensat, AT_FDCWD, argv[1], times, AT_UTIME_PTIME);
    printf("utimensat returned %d\n", ret);
    return ret;
}
