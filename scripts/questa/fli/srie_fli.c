/* ==========================================================================
 * AId-UVO-RT  --  SRIE FLI shim (optional, reference implementation)
 * ==========================================================================
 *
 * WHAT THIS IS
 *   A QuestaSim "foreign" shared library (loaded with `vsim -foreign`) that
 *   exposes the live simulation over a TCP socket using the same line protocol
 *   as the Tcl transport:
 *
 *       client ->  <cid>\t<command>\n
 *       shim   ->  ... output lines ...
 *       shim   ->  @@SRIE_END <cid> rc=<0|1>@@
 *       shim   ->  @@SRIE_EVT {"kind":"change","path":"...","value":"..."}@@
 *
 *   Supported verbs: version | describe <path> | examine <path> |
 *                    force -freeze|-deposit <path> <value> | release <path> |
 *                    watch <path> | unwatch <path> | run <time> | stop
 *
 * WHY IT IS OPTIONAL
 *   The Tcl transports already provide everything the optimizer needs, with no
 *   compilation step.  FLI adds two things: per-transition value-change
 *   callbacks (no polling) and lower steering latency.
 *
 * STATUS
 *   Reference implementation.  It compiles against the Questa FLI headers on
 *   Windows (MSVC + winsock2) and Linux (gcc + POSIX sockets) and follows the
 *   documented mti API, but it has not been validated against every Questa
 *   release.  Treat it as a starting point, not as a supported binary.  If in
 *   doubt, use the Tcl transport.
 *
 * BUILD (Windows, from a Questa-aware shell -- see build_fli.bat):
 *   cl /LD srie_fli.c /I"%QUESTA_ROOT%\include" /link ws2_32.lib ^
 *      "%QUESTA_ROOT%\win64\mtipli.lib" /OUT:srie_fli.dll
 *
 * RUN:
 *   vsim -foreign "srie_fli_init srie_fli.dll 7654" -c work.tb_top_opt
 * ========================================================================== */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#include "mti.h"

#ifdef _WIN32
#  include <winsock2.h>
#  include <ws2tcpip.h>
#  pragma comment(lib, "ws2_32.lib")
typedef SOCKET srie_socket_t;
#  define SRIE_INVALID_SOCKET INVALID_SOCKET
#  define srie_close_socket closesocket
#else
#  include <sys/socket.h>
#  include <netinet/in.h>
#  include <unistd.h>
#  include <fcntl.h>
typedef int srie_socket_t;
#  define SRIE_INVALID_SOCKET (-1)
#  define srie_close_socket close
#endif

#ifndef _WIN32
#  define _snprintf snprintf
#  define _strdup   strdup
#endif

#define SRIE_MAX_CLIENTS 4
#define SRIE_LINE_MAX    8192

static srie_socket_t g_listen = SRIE_INVALID_SOCKET;
static srie_socket_t g_client[SRIE_MAX_CLIENTS];
static char          g_inbuf[SRIE_MAX_CLIENTS][SRIE_LINE_MAX];
static int           g_inlen[SRIE_MAX_CLIENTS];
static int           g_port = 0;
static mtiProcessIdT g_poll_proc = NULL;

/* ------------------------------------------------------------------ output */

static void srie_send(int idx, const char *text)
{
    if (idx < 0 || idx >= SRIE_MAX_CLIENTS) return;
    if (g_client[idx] == SRIE_INVALID_SOCKET) return;
    send(g_client[idx], text, (int)strlen(text), 0);
}

static void srie_send_all(const char *text)
{
    int i;
    for (i = 0; i < SRIE_MAX_CLIENTS; i++) srie_send(i, text);
}

static void srie_emit_event(const char *kind, const char *path, const char *value)
{
    char line[SRIE_LINE_MAX];
    _snprintf(line, sizeof(line),
              "@@SRIE_EVT {\"kind\":\"%s\",\"path\":\"%s\",\"value\":\"%s\",\"t\":\"[now]\"}@@\n",
              kind, path, value);
    line[sizeof(line) - 1] = '\0';
    srie_send_all(line);
}

/* --------------------------------------------------------- signal helpers */

static mtiSignalIdT srie_find_signal(const char *path)
{
    char *copy = _strdup(path);
    char *name = copy;
    char *region_name = NULL;
    mtiRegionIdT region;
    mtiSignalIdT sig;
    char *slash = strrchr(copy, '/');

    if (slash) {
        *slash = '\0';
        name = slash + 1;
        region_name = copy;
    }
    region = region_name ? mti_FindRegion(region_name) : mti_FindRegion("/");
    sig = (region == NULL) ? NULL : mti_GetSignalByName(region, name);
    free(copy);
    return sig;
}

static void srie_value_to_string(mtiSignalIdT sig, char *out, size_t n)
{
    mtiInt32T width = mti_TickWidth(sig);
    if (width <= 32) {
        _snprintf(out, n, "%ld", (long)mti_GetSignalValue(sig));
    } else {
        char *v = mti_VsignalToStr(sig, mti_GetSignalValueHigh(sig), mti_GetSignalValue(sig));
        _snprintf(out, n, "%s", v ? v : "0");
        if (v) mti_VsimFree(v);
    }
    out[n - 1] = '\0';
}

/* ------------------------------------------------------- value-change callbacks */

typedef struct srie_watch_s {
    mtiSignalIdT sig;
    char        *path;
    struct srie_watch_s *next;
} srie_watch_t;

static srie_watch_t *g_watches = NULL;

static void srie_change_cb(mtiSignalIdT sig, void *param)
{
    srie_watch_t *w = (srie_watch_t *)param;
    char value[128];
    srie_value_to_string(sig, value, sizeof(value));
    srie_emit_event("change", w->path, value);
}

static void srie_watch_add(const char *path)
{
    mtiSignalIdT sig = srie_find_signal(path);
    srie_watch_t *w;
    if (sig == NULL) return;
    for (w = g_watches; w; w = w->next) {
        if (strcmp(w->path, path) == 0) return;
    }
    w = (srie_watch_t *)malloc(sizeof(*w));
    w->sig = sig;
    w->path = _strdup(path);
    w->next = g_watches;
    g_watches = w;
    mti_AddSignalEvent(sig, srie_change_cb, w);
}

static void srie_watch_clear(void)
{
    srie_watch_t *w = g_watches;
    while (w) {
        srie_watch_t *next = w->next;
        mti_RemoveSignalEvent(w->sig, srie_change_cb, w);
        free(w->path);
        free(w);
        w = next;
    }
    g_watches = NULL;
}

/* -------------------------------------------------------------- commands */

static void srie_describe(int idx, const char *path)
{
    mtiRegionIdT region = mti_FindRegion(path);
    mtiSignalIdT sig;
    char line[SRIE_LINE_MAX];
    char value[128];
    if (region == NULL) {
        sig = srie_find_signal(path);
        if (sig == NULL) {
            srie_send(idx, "@@SRIE_ERR describe: no region or signal\n");
            return;
        }
        srie_value_to_string(sig, value, sizeof(value));
        _snprintf(line, sizeof(line), "# Region: %s\n#   %s   internal  net  width=%ld\n",
                  path, path, (long)mti_TickWidth(sig));
        srie_send(idx, line);
        return;
    }
    _snprintf(line, sizeof(line), "# Region: %s\n", path);
    srie_send(idx, line);
    for (sig = mti_FirstSignal(region); sig; sig = mti_NextSignal()) {
        srie_value_to_string(sig, value, sizeof(value));
        _snprintf(line, sizeof(line), "#   %s/%s   internal  net  width=%ld\n",
                  path, mti_GetSignalName(sig), (long)mti_TickWidth(sig));
        srie_send(idx, line);
    }
}

static void srie_examine(int idx, const char *path)
{
    char line[SRIE_LINE_MAX];
    char value[128];
    mtiSignalIdT sig = srie_find_signal(path);
    if (sig == NULL) {
        srie_send(idx, "@@SRIE_ERR examine: no object named ");
        srie_send(idx, path);
        srie_send(idx, "\n");
        return;
    }
    srie_value_to_string(sig, value, sizeof(value));
    _snprintf(line, sizeof(line), "# %s = %s\n", path, value);
    srie_send(idx, line);
}

static void srie_force(int idx, const char *path, const char *value, int freeze)
{
    mtiSignalIdT sig = srie_find_signal(path);
    mtiDriverIdT driver;
    if (sig == NULL) {
        srie_send(idx, "@@SRIE_ERR force: unknown signal\n");
        return;
    }
    driver = mti_CreateDriver(sig);
    mti_ScheduleDriver(driver, (long)strtoll(value, NULL, 0), 0,
                       freeze ? MTI_FORCE : MTI_DEPOSIT);
    mti_DoneDriver(driver);
    srie_send(idx, "# forced\n");
}

static void srie_release(int idx, const char *path)
{
    mtiSignalIdT sig = srie_find_signal(path);
    if (sig == NULL) {
        srie_send(idx, "@@SRIE_ERR release: unknown signal\n");
        return;
    }
    mti_ReleaseSignal(sig);
    srie_send(idx, "# released\n");
}

/* Split "<cid>\t<command>" and dispatch.  Returns 0 on success. */
static int srie_dispatch(int idx, char *line)
{
    char *cmd = line;
    char *tab = strchr(line, '\t');
    char cid[32] = "0";
    char done[64];
    char *argv[8];
    int argc = 0;
    char *tok;

    if (tab) {
        size_t n = (size_t)(tab - line);
        if (n >= sizeof(cid)) n = sizeof(cid) - 1;
        memcpy(cid, line, n);
        cid[n] = '\0';
        cmd = tab + 1;
    }
    while (*cmd == ' ') cmd++;

    for (tok = strtok(cmd, " \t"); tok && argc < 8; tok = strtok(NULL, " \t")) {
        argv[argc++] = tok;
    }
    if (argc == 0) return 0;

    if (strcmp(argv[0], "version") == 0) {
        char v[256];
        _snprintf(v, sizeof(v), "# srie-fli 1.0 (questa %s)\n", mti_Version());
        srie_send(idx, v);
    } else if (strcmp(argv[0], "describe") == 0 && argc >= 2) {
        srie_describe(idx, argv[argc - 1]);
    } else if (strcmp(argv[0], "examine") == 0 && argc >= 2) {
        srie_examine(idx, argv[argc - 1]);
    } else if (strcmp(argv[0], "force") == 0 && argc >= 3) {
        int freeze = (strcmp(argv[1], "-deposit") != 0);
        srie_force(idx, argv[argc - 2], argv[argc - 1], freeze);
    } else if (strcmp(argv[0], "release") == 0 && argc >= 2) {
        srie_release(idx, argv[argc - 1]);
    } else if (strcmp(argv[0], "watch") == 0 && argc >= 2) {
        srie_watch_add(argv[1]);
        srie_send(idx, "# watching\n");
    } else if (strcmp(argv[0], "unwatch") == 0) {
        srie_watch_clear();
        srie_send(idx, "# cleared\n");
    } else if (strcmp(argv[0], "stop") == 0) {
        mti_Stop();
        srie_send(idx, "# stopped\n");
    } else {
        srie_send(idx, "@@SRIE_ERR unsupported command\n");
        _snprintf(done, sizeof(done), "@@SRIE_END %s rc=1@@\n", cid);
        srie_send(idx, done);
        return 1;
    }
    _snprintf(done, sizeof(done), "@@SRIE_END %s rc=0@@\n", cid);
    srie_send(idx, done);
    return 0;
}

/* --------------------------------------------------------------- transport */

static int srie_set_nonblocking(srie_socket_t s)
{
#ifdef _WIN32
    u_long mode = 1;
    return ioctlsocket(s, FIONBIO, &mode);
#else
    int flags = fcntl(s, F_GETFL, 0);
    return fcntl(s, F_SETFL, flags | O_NONBLOCK);
#endif
}

static void srie_poll_clients(void)
{
    int i;
    for (i = 0; i < SRIE_MAX_CLIENTS; i++) {
        char chunk[1024];
        int n;
        if (g_client[i] == SRIE_INVALID_SOCKET) continue;
        n = recv(g_client[i], chunk, (int)sizeof(chunk), 0);
        if (n == 0) {
            srie_close_socket(g_client[i]);
            g_client[i] = SRIE_INVALID_SOCKET;
            g_inlen[i] = 0;
            continue;
        }
        if (n < 0) continue;
        if (g_inlen[i] + n >= SRIE_LINE_MAX) { g_inlen[i] = 0; continue; }
        memcpy(g_inbuf[i] + g_inlen[i], chunk, (size_t)n);
        g_inlen[i] += n;
        /* extract complete lines */
        for (;;) {
            char *nl = memchr(g_inbuf[i], '\n', (size_t)g_inlen[i]);
            int consumed;
            if (!nl) break;
            *nl = '\0';
            srie_dispatch(i, g_inbuf[i]);
            consumed = (int)(nl - g_inbuf[i]) + 1;
            memmove(g_inbuf[i], g_inbuf[i] + consumed, (size_t)(g_inlen[i] - consumed));
            g_inlen[i] -= consumed;
        }
    }
}

static void srie_accept_pending(void)
{
    for (;;) {
        srie_socket_t c;
        int i, slot = -1;
        if (g_listen == SRIE_INVALID_SOCKET) return;
        c = accept(g_listen, NULL, NULL);
        if (c == SRIE_INVALID_SOCKET) return;
        for (i = 0; i < SRIE_MAX_CLIENTS; i++) {
            if (g_client[i] == SRIE_INVALID_SOCKET) { slot = i; break; }
        }
        if (slot < 0) { srie_close_socket(c); continue; }
        srie_set_nonblocking(c);
        g_client[slot] = c;
        g_inlen[slot] = 0;
        srie_send(slot, "@@SRIE_READY srie-fli/1.0@@\n");
    }
}

/* A 1 ns process keeps the socket serviced while the simulation runs. */
static void srie_poll_proc(void)
{
    srie_accept_pending();
    srie_poll_clients();
    mti_ScheduleWakeup(1, srie_poll_proc);
}

/* ------------------------------------------------------------ FLI entry */

void srie_fli_init(void)
{
    char *port_arg = mti_GetArg(1);
    struct sockaddr_in addr;
    int i;

#ifdef _WIN32
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
#endif
    for (i = 0; i < SRIE_MAX_CLIENTS; i++) {
        g_client[i] = SRIE_INVALID_SOCKET;
        g_inlen[i] = 0;
    }
    g_port = port_arg ? atoi(port_arg) : 7654;

    g_listen = socket(AF_INET, SOCK_STREAM, 0);
    if (g_listen == SRIE_INVALID_SOCKET) {
        mti_PrintMessage("SRIE-FLI: cannot create socket\n");
        return;
    }
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = htons((unsigned short)g_port);
    if (bind(g_listen, (struct sockaddr *)&addr, sizeof(addr)) != 0 ||
        listen(g_listen, 4) != 0) {
        mti_PrintMessage("SRIE-FLI: cannot bind/listen\n");
        return;
    }
    srie_set_nonblocking(g_listen);
    mti_PrintFormat("SRIE-FLI: listening on 127.0.0.1:%d\n", g_port);
    g_poll_proc = mti_CreateProcess("srie_poll", srie_poll_proc);
    mti_ScheduleWakeup(1, srie_poll_proc);
}
