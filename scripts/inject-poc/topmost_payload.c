// 置顶注入载荷：被 dlopen 进 Dock.app 后，在 Dock 进程内调用 SkyLight 私有 API 修改窗口层级。
//
// 原理同 yabai 的 scripting-addition：Dock 是系统进程，拥有自己的 SLS 连接，不受
// macOS 15+ 的跨进程进程归属校验限制。
//
// 参数通过文件传递（/tmp/topmost_target.txt 内容为 "wid level"），执行结果写到
// /tmp/topmost_result.txt。用构造器而非导出函数，是因为 lldb 的 expr 在 Dock 进程内
// 直接 dlsym 内联调用会崩（表达式求值环境拿不到完整符号），dlopen 触发构造器最稳。
//
// 注意：dlopen 同一路径第二次不会重跑构造器，调用方需每次复制成唯一文件名。
#include <stdio.h>
#include <stdlib.h>
#include <dlfcn.h>

#define TARGET_FILE "/tmp/topmost_target.txt"
#define RESULT_FILE "/tmp/topmost_result.txt"

typedef int (*fn_connection)(void);
typedef int (*fn_set_level)(int cid, unsigned int wid, int level);

__attribute__((constructor))
static void optsnap_topmost_apply(void) {
    FILE *rf = fopen(RESULT_FILE, "w");
    if (!rf) return;

    FILE *tf = fopen(TARGET_FILE, "r");
    if (!tf) { fprintf(rf, "FAIL 目标文件缺失\n"); fclose(rf); return; }

    unsigned int wid = 0;
    int level = 3;
    if (fscanf(tf, "%u %d", &wid, &level) != 2) {
        fprintf(rf, "FAIL 参数解析失败\n"); fclose(tf); fclose(rf); return;
    }
    fclose(tf);

    void *sl = dlopen("/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight", RTLD_LAZY);
    if (!sl) { fprintf(rf, "FAIL dlopen SkyLight\n"); fclose(rf); return; }

    fn_connection conn = (fn_connection)dlsym(sl, "SLSMainConnectionID");
    fn_set_level set_level = (fn_set_level)dlsym(sl, "SLSSetWindowLevel");
    if (!conn || !set_level) { fprintf(rf, "FAIL dlsym\n"); fclose(rf); return; }

    int err = set_level(conn(), wid, level);
    fprintf(rf, "wid=%u level=%d err=%d\n", wid, level, err);
    fclose(rf);
}
