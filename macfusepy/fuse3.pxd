from libc.stddef cimport size_t
from libc.stdint cimport int32_t, uint16_t, uint32_t, uint64_t
from posix.types cimport dev_t, gid_t, mode_t, off_t, pid_t, uid_t

cdef extern from "fcntl.h":
    cdef struct flock:
        short l_type
        short l_whence
        off_t l_start
        off_t l_len
        pid_t l_pid


cdef extern from "time.h":
    ctypedef long time_t

    cdef struct timespec:
        time_t tv_sec
        long tv_nsec


cdef extern from "fuse.h":
    cdef struct c_stat "fuse_darwin_attr":
        uint64_t ino
        mode_t mode
        uint32_t nlink
        uid_t uid
        gid_t gid
        dev_t rdev
        timespec atimespec
        timespec mtimespec
        timespec ctimespec
        timespec btimespec
        timespec bkuptimespec
        off_t size
        long long blocks
        int32_t blksize
        unsigned int flags


cdef extern from "sys/mount.h":
    cdef struct c_statvfs "statfs":
        uint32_t f_bsize
        uint64_t f_blocks
        uint64_t f_bfree
        uint64_t f_bavail
        uint64_t f_files
        uint64_t f_ffree
        uint32_t f_flags


cdef extern from "fuse.h":
    cdef struct fuse:
        pass

    cdef struct fuse_conn_info:
        uint32_t proto_major
        uint32_t proto_minor
        uint32_t max_write
        uint32_t max_read
        uint32_t max_readahead
        uint32_t capable
        uint32_t want
        uint32_t max_background
        uint32_t congestion_threshold
        uint32_t time_gran
        uint32_t max_backing_stack_depth
        uint64_t capable_ext
        uint64_t want_ext
        uint64_t capable_darwin
        uint64_t want_darwin
        uint16_t request_timeout

    cdef struct fuse_config:
        int set_gid
        unsigned int gid
        int set_uid
        unsigned int uid
        int set_mode
        unsigned int umask
        double entry_timeout
        double negative_timeout
        double attr_timeout
        int intr
        int intr_signal
        int remember
        int hard_remove
        int use_ino
        int readdir_ino
        int direct_io
        int kernel_cache
        int auto_cache
        int no_rofd_flush
        int ac_attr_timeout_set
        double ac_attr_timeout
        int nullpath_ok
        int show_help

    cdef struct fuse_file_info:
        int32_t flags
        uint32_t writepage
        uint32_t direct_io
        uint32_t keep_cache
        uint32_t flush
        uint32_t nonseekable
        uint32_t flock_release
        uint32_t cache_readdir
        uint32_t noflush
        uint32_t parallel_direct_writes
        uint64_t fh
        uint64_t lock_owner
        uint32_t poll_events
        int32_t backing_id
        uint64_t compat_flags

    cdef struct fuse_context:
        fuse *fuse
        uid_t uid
        gid_t gid
        pid_t pid
        void *private_data

    cdef enum fuse_readdir_flags:
        FUSE_READDIR_DEFAULTS
        FUSE_READDIR_PLUS

    cdef enum fuse_fill_dir_flags:
        FUSE_FILL_DIR_DEFAULTS
        FUSE_FILL_DIR_PLUS

    ctypedef int (*fuse_fill_dir_t "fuse_darwin_fill_dir_t")(
        void *buf,
        const char *name,
        const c_stat *stbuf,
        off_t off,
        fuse_fill_dir_flags flags,
    )

    cdef struct fuse_operations:
        int (*getattr)(const char *, c_stat *, fuse_file_info *)
        int (*readlink)(const char *, char *, size_t)
        int (*mknod)(const char *, mode_t, dev_t)
        int (*mkdir)(const char *, mode_t)
        int (*unlink)(const char *)
        int (*rmdir)(const char *)
        int (*symlink)(const char *, const char *)
        int (*rename)(const char *, const char *, unsigned int)
        int (*link)(const char *, const char *)
        int (*chmod)(const char *, mode_t, fuse_file_info *)
        int (*chown)(const char *, uid_t, gid_t, fuse_file_info *)
        int (*truncate)(const char *, off_t, fuse_file_info *)
        int (*open)(const char *, fuse_file_info *)
        int (*read)(const char *, char *, size_t, off_t, fuse_file_info *)
        int (*write)(const char *, const char *, size_t, off_t, fuse_file_info *)
        int (*statfs)(const char *, c_statvfs *)
        int (*flush)(const char *, fuse_file_info *)
        int (*release)(const char *, fuse_file_info *)
        int (*fsync)(const char *, int, fuse_file_info *)
        int (*lock)(const char *, fuse_file_info *, int, flock *)
        int (*setxattr)(const char *, const char *, const char *, size_t, int, uint32_t)
        int (*getxattr)(const char *, const char *, char *, size_t, uint32_t)
        int (*listxattr)(const char *, char *, size_t)
        int (*removexattr)(const char *, const char *)
        int (*opendir)(const char *, fuse_file_info *)
        int (*readdir)(
            const char *,
            void *,
            fuse_fill_dir_t,
            off_t,
            fuse_file_info *,
            fuse_readdir_flags,
        )
        int (*releasedir)(const char *, fuse_file_info *)
        int (*fsyncdir)(const char *, int, fuse_file_info *)
        void *(*init)(fuse_conn_info *, fuse_config *)
        void (*destroy)(void *)
        int (*access)(const char *, int)
        int (*create)(const char *, mode_t, fuse_file_info *)
        int (*utimens)(const char *, const timespec *, fuse_file_info *)
        int (*bmap)(const char *, size_t, uint64_t *)
        int (*ioctl)(const char *, unsigned int, void *, fuse_file_info *, unsigned int, void *)

    int fuse_main(
        int argc,
        char **argv,
        const fuse_operations *op,
        void *user_data,
    ) nogil
    fuse_context *fuse_get_context()
    void fuse_exit(fuse *f)
    int fuse_get_version "fuse_version"()


cdef extern from "fuse_lowlevel.h":
    ctypedef uint64_t fuse_ino_t
    ctypedef void *fuse_req_t

    cdef struct fuse_ctx:
        uid_t uid
        gid_t gid
        pid_t pid
        mode_t umask

    cdef struct fuse_session:
        pass

    cdef struct fuse_loop_config:
        int clone_fd
        unsigned int max_idle_threads

    cdef struct fuse_args:
        int argc
        char **argv
        int allocated

    cdef struct fuse_entry_param "fuse_darwin_entry_param":
        fuse_ino_t ino
        uint64_t generation
        c_stat attr
        double attr_timeout
        double entry_timeout

    cdef struct fuse_lowlevel_ops:
        void (*init)(void *, fuse_conn_info *)
        void (*destroy)(void *)
        void (*lookup)(fuse_req_t, fuse_ino_t, const char *)
        void (*forget)(fuse_req_t, fuse_ino_t, uint64_t)
        void (*getattr)(fuse_req_t, fuse_ino_t, fuse_file_info *)
        void (*setattr)(fuse_req_t, fuse_ino_t, c_stat *, int, fuse_file_info *)
        void (*readlink)(fuse_req_t, fuse_ino_t)
        void (*mknod)(fuse_req_t, fuse_ino_t, const char *, mode_t, dev_t)
        void (*mkdir)(fuse_req_t, fuse_ino_t, const char *, mode_t)
        void (*unlink)(fuse_req_t, fuse_ino_t, const char *)
        void (*rmdir)(fuse_req_t, fuse_ino_t, const char *)
        void (*symlink)(fuse_req_t, const char *, fuse_ino_t, const char *)
        void (*rename)(fuse_req_t, fuse_ino_t, const char *, fuse_ino_t, const char *, unsigned int)
        void (*link)(fuse_req_t, fuse_ino_t, fuse_ino_t, const char *)
        void (*open)(fuse_req_t, fuse_ino_t, fuse_file_info *)
        void (*read)(fuse_req_t, fuse_ino_t, size_t, off_t, fuse_file_info *)
        void (*write)(fuse_req_t, fuse_ino_t, const char *, size_t, off_t, fuse_file_info *)
        void (*flush)(fuse_req_t, fuse_ino_t, fuse_file_info *)
        void (*release)(fuse_req_t, fuse_ino_t, fuse_file_info *)
        void (*fsync)(fuse_req_t, fuse_ino_t, int, fuse_file_info *)
        void (*opendir)(fuse_req_t, fuse_ino_t, fuse_file_info *)
        void (*readdir)(fuse_req_t, fuse_ino_t, size_t, off_t, fuse_file_info *)
        void (*releasedir)(fuse_req_t, fuse_ino_t, fuse_file_info *)
        void (*fsyncdir)(fuse_req_t, fuse_ino_t, int, fuse_file_info *)
        void (*statfs)(fuse_req_t, fuse_ino_t)
        void (*setxattr)(fuse_req_t, fuse_ino_t, const char *, const char *, size_t, int, uint32_t)
        void (*getxattr)(fuse_req_t, fuse_ino_t, const char *, size_t, uint32_t)
        void (*listxattr)(fuse_req_t, fuse_ino_t, size_t)
        void (*removexattr)(fuse_req_t, fuse_ino_t, const char *)
        void (*access)(fuse_req_t, fuse_ino_t, int)
        void (*create)(fuse_req_t, fuse_ino_t, const char *, mode_t, fuse_file_info *)
        void (*getlk)(fuse_req_t, fuse_ino_t, fuse_file_info *, flock *)
        void (*setlk)(fuse_req_t, fuse_ino_t, fuse_file_info *, flock *, int)
        void (*bmap)(fuse_req_t, fuse_ino_t, size_t, uint64_t)
        void (*ioctl)(fuse_req_t, fuse_ino_t, unsigned int, void *, fuse_file_info *, unsigned int, const void *, size_t, size_t)
        void *poll
        void *write_buf
        void *retrieve_reply
        void *forget_multi
        void (*flock)(fuse_req_t, fuse_ino_t, fuse_file_info *, int)
        void *fallocate
        void *readdirplus
        void *copy_file_range
        void *lseek
        void *tmpfile
        void (*setvolname)(fuse_req_t, const char *)
        void *monitor
        void *statx

    fuse_session *fuse_session_new(
        fuse_args *args,
        const fuse_lowlevel_ops *op,
        size_t op_size,
        void *userdata,
    )
    int fuse_session_mount(fuse_session *se, const char *mountpoint)
    void fuse_session_unmount(fuse_session *se)
    void fuse_session_destroy(fuse_session *se)
    int fuse_session_fd(fuse_session *se)
    int fuse_session_exited(fuse_session *se)
    void fuse_session_exit(fuse_session *se)
    int fuse_session_loop_mt(fuse_session *se, fuse_loop_config *config) nogil
    void *fuse_req_userdata(fuse_req_t req)
    const fuse_ctx *fuse_req_ctx(fuse_req_t req)

    int fuse_reply_err(fuse_req_t req, int err)
    int fuse_reply_entry(fuse_req_t req, const fuse_entry_param *e)
    int fuse_reply_create(fuse_req_t req, const fuse_entry_param *e, const fuse_file_info *fi)
    int fuse_reply_attr(fuse_req_t req, const c_stat *attr, double attr_timeout)
    int fuse_reply_readlink(fuse_req_t req, const char *link)
    int fuse_reply_open(fuse_req_t req, const fuse_file_info *fi)
    int fuse_reply_lock(fuse_req_t req, const flock *lock)
    int fuse_reply_write(fuse_req_t req, size_t count)
    int fuse_reply_buf(fuse_req_t req, const char *buf, size_t size)
    int fuse_reply_statfs(fuse_req_t req, const c_statvfs *stbuf)
    int fuse_reply_xattr(fuse_req_t req, size_t count)
    int fuse_reply_bmap(fuse_req_t req, uint64_t idx)
    int fuse_reply_ioctl(fuse_req_t req, int result, const void *buf, size_t size)
    void fuse_reply_none(fuse_req_t req)
    size_t fuse_add_direntry(
        fuse_req_t req,
        char *buf,
        size_t bufsize,
        const char *name,
        const c_stat *stbuf,
        off_t off,
    )
