/*
 * memload - guest-side memory workload generator for hotplug experiments.
 *
 * Runs as an ordinary (unprivileged) process inside the guest.
 *
 *   memload anon <MiB>             allocate and touch anonymous memory, hold it
 *   memload slab <count> <dir>     create <count> empty files in <dir> (tmpfs);
 *                                  every file pins an inode and a dentry in
 *                                  kernel slab, i.e. unmovable kernel memory
 *   memload frag <MiB> <count> <dir>
 *                                  interleave: fill <MiB> of anonymous memory,
 *                                  create <count> files, then release the
 *                                  anonymous memory. The slab objects end up
 *                                  scattered over the pages that were free,
 *                                  including hot-plugged ones.
 *
 * "anon" and "frag" print "READY" when the load is in place and then sleep
 * until killed, so the memory stays allocated for the duration of a trial.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define MiB (1024UL * 1024UL)

static void *fill_anon(unsigned long mib)
{
	size_t len = mib * MiB;
	char *p = mmap(NULL, len, PROT_READ | PROT_WRITE,
		       MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if (p == MAP_FAILED) {
		perror("mmap");
		exit(1);
	}
	long pg = sysconf(_SC_PAGESIZE);
	for (size_t off = 0; off < len; off += pg)
		p[off] = (char)off | 1;
	return p;
}

static unsigned long make_files(unsigned long count, const char *dir)
{
	char path[512];
	unsigned long made = 0;
	for (unsigned long i = 0; i < count; i++) {
		snprintf(path, sizeof(path), "%s/f%08lu", dir, i);
		int fd = open(path, O_CREAT | O_WRONLY, 0600);
		if (fd < 0) {
			if (errno == ENOSPC || errno == ENOMEM)
				break;
			perror("open");
			exit(1);
		}
		close(fd);
		made++;
	}
	return made;
}

static void hold(void)
{
	printf("READY\n");
	fflush(stdout);
	for (;;)
		pause();
}

int main(int argc, char **argv)
{
	if (argc >= 3 && !strcmp(argv[1], "anon")) {
		fill_anon(strtoul(argv[2], NULL, 10));
		hold();
	} else if (argc >= 4 && !strcmp(argv[1], "slab")) {
		unsigned long n = make_files(strtoul(argv[2], NULL, 10), argv[3]);
		printf("FILES %lu\n", n);
		return 0;
	} else if (argc >= 5 && !strcmp(argv[1], "frag")) {
		unsigned long mib = strtoul(argv[2], NULL, 10);
		void *p = fill_anon(mib);
		unsigned long n = make_files(strtoul(argv[3], NULL, 10), argv[4]);
		munmap(p, mib * MiB);
		printf("FILES %lu\n", n);
		return 0;
	}
	fprintf(stderr, "usage: memload anon MiB | slab N DIR | frag MiB N DIR\n");
	return 2;
}
