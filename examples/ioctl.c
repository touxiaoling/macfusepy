#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <sys/ioctl.h>

#define M_IOWR _IOWR('M', 1, uint32_t)

int main(int argc, char *argv[]) {
    char *endptr;
    int fd;
    uint32_t data;
    unsigned long parsed;

    if (argc != 3) {
        fprintf(stderr, "Usage: %s value filename\n", argv[0]);
        return 1;
    }

    errno = 0;
    parsed = strtoul(argv[1], &endptr, 10);
    if (errno != 0 || *endptr != '\0' || parsed > UINT32_MAX) {
        fprintf(stderr, "invalid value: %s\n", argv[1]);
        return 1;
    }
    data = (uint32_t)parsed;

    /* 打开挂载点里的文件后，对这个 fd 发起 ioctl，请求会转到 ioctl.py。 */
    fd = open(argv[2], O_RDONLY);
    if (fd == -1) {
        fprintf(stderr, "open failed: %s\n", strerror(errno));
        return 1;
    }

    if (ioctl(fd, M_IOWR, &data) == -1)
        fprintf(stderr, "M_IOWR failed: %s\n", strerror(errno));
    else {
        printf("M_IOWR successful, data = %u\n", data);
    }

    close(fd);
    return 0;
}
