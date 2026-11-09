// OptSnap 置顶载荷 —— 被注入到 Dock.app 后常驻运行，代理执行窗口层级修改。
//
// 为什么要借 Dock 的进程：
//   macOS 15 起，SkyLight 的 SLSSetWindowLevel / SLSSetWindowAlpha 对「其它进程」的窗口
//   会返回 CGError 0（假装成功）但实际不生效，因为底层做了进程归属校验。Dock 是系统
//   进程，用它自己的 SLS 连接就能改。yabai 的 scripting-addition 是同一原理。
//
// 工作方式：
//   构造器启动一个后台线程，轮询命令文件。命令格式（单行）：
//       <序号> <window_id> <level>
//   执行后把回执写到 ack 文件：
//       <序号> <window_id> <level> <CGError>
//   同时定期刷新心跳文件，供宿主判断通道是否存活。
//
// 用「序号」而不是直接执行：宿主可以重试同一条命令，载荷只执行序号更大的命令，
// 避免重复下发导致的状态错乱。

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <pthread.h>
#include <dlfcn.h>

#define CMD_FILE       "/tmp/optsnap_pin_cmd"
#define ACK_FILE       "/tmp/optsnap_pin_ack"
#define HEARTBEAT_FILE "/tmp/optsnap_pin_heartbeat"

// 轮询间隔。30ms 足够让快捷键的响应看起来是即时的，
// 又不会让 Dock 的空闲 CPU 占用变得显眼。
#define POLL_INTERVAL_US 30000

// 心跳写盘间隔（微秒）。心跳只是为了证明通道存活，没必要每轮都重写文件 ——
// 每轮都 fopen+rename 会让 Dock 常驻 1.8% 左右的 CPU，改成 1 秒一次后
// 绝大多数轮次只做一次「读命令文件」的轻量检查。
#define HEARTBEAT_INTERVAL_US 1000000

typedef int (*fn_connection)(void);
typedef int (*fn_set_level)(int cid, unsigned int wid, int level);

// 原子写文件：先写临时文件再 rename，避免宿主读到半截内容。
static void write_atomic(const char *path, const char *content) {
    char tmp[256];
    snprintf(tmp, sizeof(tmp), "%s.tmp", path);
    FILE *f = fopen(tmp, "w");
    if (!f) return;
    fputs(content, f);
    fclose(f);
    rename(tmp, path);
}

static void *watch_thread(void *arg) {
    (void)arg;

    void *sl = dlopen("/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight", RTLD_LAZY);
    if (!sl) return NULL;

    fn_connection conn = (fn_connection)dlsym(sl, "SLSMainConnectionID");
    fn_set_level set_level = (fn_set_level)dlsym(sl, "SLSSetWindowLevel");
    if (!conn || !set_level) return NULL;

    int cid = conn();
    long last_seq = 0;
    long long last_heartbeat = 0;
    // 命令文件的「已处理版本」标记：用 inode + 修改时间判断内容是否变了。
    // 只做 stat() 比每轮 open+read+close 便宜得多 —— 空闲时基本零开销。
    ino_t last_ino = 0;
    time_t last_mtime = 0;

    for (;;) {
        // 心跳：证明通道存活，宿主据此判断是否需要重新注入。
        // 按秒节流，避免每轮轮询都产生文件 I/O。
        long long now_us = (long long)time(NULL) * 1000000;
        if (now_us - last_heartbeat >= HEARTBEAT_INTERVAL_US) {
            last_heartbeat = now_us;
            char hb[64];
            snprintf(hb, sizeof(hb), "%d\n", getpid());
            write_atomic(HEARTBEAT_FILE, hb);
        }

        // 先 stat 判断命令文件是否被换过，没变就跳过读取
        struct stat st;
        if (stat(CMD_FILE, &st) == 0 && (st.st_ino != last_ino || st.st_mtime != last_mtime)) {
            last_ino = st.st_ino;
            last_mtime = st.st_mtime;

            FILE *cf = fopen(CMD_FILE, "r");
            if (cf) {
                long seq = 0;
                unsigned int wid = 0;
                int level = 0;
                int parsed = fscanf(cf, "%ld %u %d", &seq, &wid, &level);
                fclose(cf);

                // 只执行序号更新的命令；解析失败（正在写）就跳过，下一轮再看
                if (parsed == 3 && seq > last_seq) {
                    last_seq = seq;
                    int err = set_level(cid, wid, level);

                    char ack[128];
                    snprintf(ack, sizeof(ack), "%ld %u %d %d\n", seq, wid, level, err);
                    write_atomic(ACK_FILE, ack);
                }
            }
        }

        usleep(POLL_INTERVAL_US);
    }

    return NULL;
}

__attribute__((constructor))
static void optsnap_pin_start(void) {
    pthread_t t;
    if (pthread_create(&t, NULL, watch_thread, NULL) == 0) {
        pthread_detach(t);
    }
}
