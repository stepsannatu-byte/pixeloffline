/* steam_api64.dll falsa para el modo offline de PG3D.
 *
 * Sustituye a la de Valve solo en la copia offline del juego. No habla con
 * Steam ni con nadie: responde a las llamadas de Steamworks.NET con valores
 * locales y entrega un ticket falso que solo acepta el servidor local.
 *
 * Este archivo implementa las funciones con comportamiento propio. El resto
 * de exportaciones (más de mil) las genera gen_stub.py en stub_gen.c y
 * devuelven 0, o un puntero a memoria a cero si devuelven IntPtr.
 *
 * Configuración: steam_stub.ini junto a la DLL (ver steam_stub.ini.example).
 * Registro: steam_stub.log junto a la DLL, con la primera llamada a cada función.
 */
#include <windows.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "stub.h"

#define APP_ID 2524890u
#define CB_GET_AUTH_SESSION_TICKET_RESPONSE 163
#define CB_ENCRYPTED_APP_TICKET_RESPONSE 154
#define CB_GET_TICKET_FOR_WEB_API_RESPONSE 168
#define CB_USER_STATS_RECEIVED 1101
#define CB_STEAM_API_CALL_COMPLETED 703
#define TICKET_MAX 2560

/* Memoria a cero que sirve a la vez de "interfaz" no nula y de cadena vacía. */
__attribute__((aligned(16))) uint8_t g_zero[65536];

/* ------------------------------------------------------------ configuración */

static char g_dir[MAX_PATH];
static char g_name[128] = "Jugador";
static char g_language[64] = "english";
static char g_country[8] = "ES";
static uint64_t g_steamid = 76561197960265729ull; /* cuenta individual, id 1 */

static void read_config(void) {
    char ini[MAX_PATH + 32], buf[128];
    snprintf(ini, sizeof ini, "%s\\steam_stub.ini", g_dir);
    GetPrivateProfileStringA("player", "name", g_name, g_name, sizeof g_name, ini);
    GetPrivateProfileStringA("player", "language", g_language, g_language, sizeof g_language, ini);
    GetPrivateProfileStringA("player", "country", g_country, g_country, sizeof g_country, ini);
    if (GetPrivateProfileStringA("player", "steamid", "", buf, sizeof buf, ini) && buf[0])
        g_steamid = strtoull(buf, NULL, 10);
}

/* ------------------------------------------------------------------ registro */

static SRWLOCK g_lock = SRWLOCK_INIT;
static FILE *g_log;

void stub_log(const char *fmt, ...) {
    if (!g_log) return;
    va_list ap;
    va_start(ap, fmt);
    AcquireSRWLockExclusive(&g_lock);
    vfprintf(g_log, fmt, ap);
    fputc('\n', g_log);
    fflush(g_log);
    ReleaseSRWLockExclusive(&g_lock);
    va_end(ap);
}

void stub_seen(volatile LONG *flag, const char *name) {
    if (*flag || InterlockedExchange(flag, 1)) return;
    stub_log("call %s", name);
}

#define SEEN() do { static volatile LONG f; stub_seen(&f, __func__); } while (0)

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        char path[MAX_PATH], *slash;
        GetModuleFileNameA(inst, path, sizeof path);
        if ((slash = strrchr(path, '\\'))) *slash = 0;
        strncpy(g_dir, path, sizeof g_dir - 1);
        read_config();
        snprintf(path, sizeof path, "%s\\steam_stub.log", g_dir);
        g_log = fopen(path, "w");
        stub_log("steam_stub cargado. name=%s steamid=%llu language=%s",
                 g_name, (unsigned long long)g_steamid, g_language);
    }
    return TRUE;
}

/* ---------------------------------------------------- cola de callbacks */

typedef struct Callback {
    struct Callback *next;
    int id;
    int size;
    uint8_t data[];
} Callback;

typedef struct CallResult {
    struct CallResult *next;
    uint64_t handle;
    int id;
    int size;
    uint8_t data[];
} CallResult;

typedef struct {
    int32_t m_hSteamUser;
    int32_t m_iCallback;
    uint8_t *m_pubParam;
    int32_t m_cubParam;
} CallbackMsg_t;

static Callback *g_head, *g_tail, *g_current;
static CallResult *g_results;
static uint64_t g_next_call = 1;
static uint32_t g_next_ticket = 1;

static void push_callback(int id, const void *data, int size) {
    Callback *cb = calloc(1, sizeof *cb + size);
    cb->id = id;
    cb->size = size;
    memcpy(cb->data, data, size);
    AcquireSRWLockExclusive(&g_lock);
    if (g_tail) g_tail->next = cb; else g_head = cb;
    g_tail = cb;
    ReleaseSRWLockExclusive(&g_lock);
}

/* Registra el resultado de una llamada asíncrona y avisa con SteamAPICallCompleted_t. */
static uint64_t push_call_result(int id, const void *data, int size) {
    CallResult *r = calloc(1, sizeof *r + size);
    r->id = id;
    r->size = size;
    memcpy(r->data, data, size);
    AcquireSRWLockExclusive(&g_lock);
    r->handle = g_next_call++;
    r->next = g_results;
    g_results = r;
    ReleaseSRWLockExclusive(&g_lock);
    struct { uint64_t m_hAsyncCall; int32_t m_iCallback; uint32_t m_cubParam; } done =
        { r->handle, id, (uint32_t)size };
    push_callback(CB_STEAM_API_CALL_COMPLETED, &done, sizeof done);
    return r->handle;
}

STUB_EXPORT void SteamAPI_ManualDispatch_Init(void) { SEEN(); }
STUB_EXPORT void SteamAPI_ManualDispatch_RunFrame(int32_t pipe) { (void)pipe; SEEN(); }

STUB_EXPORT uint8_t SteamAPI_ManualDispatch_GetNextCallback(int32_t pipe, CallbackMsg_t *msg) {
    (void)pipe;
    SEEN();
    AcquireSRWLockExclusive(&g_lock);
    Callback *cb = g_current ? NULL : g_head;
    if (cb) {
        g_head = cb->next;
        if (!g_head) g_tail = NULL;
        g_current = cb;
    }
    ReleaseSRWLockExclusive(&g_lock);
    if (!cb) return 0;
    msg->m_hSteamUser = 1;
    msg->m_iCallback = cb->id;
    msg->m_pubParam = cb->data;
    msg->m_cubParam = cb->size;
    stub_log("callback %d (%d bytes)", cb->id, cb->size);
    return 1;
}

STUB_EXPORT void SteamAPI_ManualDispatch_FreeLastCallback(int32_t pipe) {
    (void)pipe;
    AcquireSRWLockExclusive(&g_lock);
    Callback *cb = g_current;
    g_current = NULL;
    ReleaseSRWLockExclusive(&g_lock);
    free(cb);
}

STUB_EXPORT uint8_t SteamAPI_ManualDispatch_GetAPICallResult(int32_t pipe, uint64_t call, void *out,
                                                             int size, int expected, uint8_t *failed) {
    (void)pipe;
    SEEN();
    AcquireSRWLockExclusive(&g_lock);
    CallResult **p = &g_results, *r = NULL;
    for (; *p; p = &(*p)->next)
        if ((*p)->handle == call) { r = *p; *p = r->next; break; }
    ReleaseSRWLockExclusive(&g_lock);
    if (!r) return 0;
    memcpy(out, r->data, size < r->size ? size : r->size);
    if (failed) *failed = r->id != expected;
    free(r);
    return 1;
}

/* ------------------------------------------------------------- arranque */

STUB_EXPORT uint8_t SteamAPI_Init(void) { SEEN(); return 1; }
STUB_EXPORT uint8_t SteamAPI_InitSafe(void) { SEEN(); return 1; }
STUB_EXPORT uint8_t SteamAPI_InitAnonymousUser(void) { SEEN(); return 1; }
STUB_EXPORT uint8_t SteamAPI_IsSteamRunning(void) { SEEN(); return 1; }
STUB_EXPORT uint8_t SteamAPI_RestartAppIfNecessary(uint32_t app) { (void)app; SEEN(); return 0; }
STUB_EXPORT int32_t SteamAPI_GetHSteamPipe(void) { return 1; }
STUB_EXPORT int32_t SteamAPI_GetHSteamUser(void) { return 1; }
STUB_EXPORT void *SteamInternal_CreateInterface(const char *ver) {
    stub_log("CreateInterface %s", ver ? ver : "(null)");
    return g_zero;
}
STUB_EXPORT int32_t SteamAPI_ISteamClient_CreateSteamPipe(void *self) { (void)self; return 1; }
STUB_EXPORT int32_t SteamAPI_ISteamClient_ConnectToGlobalUser(void *self, int32_t pipe) {
    (void)self; (void)pipe; return 1;
}

/* ---------------------------------------------------------------- usuario */

/* Ticket falso: "PG3DOFFLINE:<steamid>:<nombre>". El servidor local lo reconoce. */
static int make_ticket(uint8_t *out, int max) {
    char t[256];
    int n = snprintf(t, sizeof t, "PG3DOFFLINE:%llu:%s", (unsigned long long)g_steamid, g_name);
    if (n > max) n = max;
    memcpy(out, t, n);
    return n;
}

STUB_EXPORT uint8_t SteamAPI_ISteamUser_BLoggedOn(void *self) { (void)self; return 1; }
STUB_EXPORT uint64_t SteamAPI_ISteamUser_GetSteamID(void *self) { (void)self; SEEN(); return g_steamid; }
STUB_EXPORT int32_t SteamAPI_ISteamUser_GetHSteamUser(void *self) { (void)self; return 1; }
STUB_EXPORT int32_t SteamAPI_ISteamUser_GetPlayerSteamLevel(void *self) { (void)self; return 1; }

STUB_EXPORT uint32_t SteamAPI_ISteamUser_GetAuthTicketForWebApi(void *self, const char *identity) {
    (void)self;
    struct {
        uint32_t m_hAuthTicket;
        int32_t m_eResult;
        int32_t m_cubTicket;
        uint8_t m_rgubTicket[TICKET_MAX];
    } r = {0};
    r.m_hAuthTicket = g_next_ticket++;
    r.m_eResult = 1; /* k_EResultOK */
    r.m_cubTicket = make_ticket(r.m_rgubTicket, TICKET_MAX);
    stub_log("GetAuthTicketForWebApi identity=%s -> ticket %u", identity ? identity : "(null)",
             r.m_hAuthTicket);
    push_callback(CB_GET_TICKET_FOR_WEB_API_RESPONSE, &r, sizeof r);
    return r.m_hAuthTicket;
}

STUB_EXPORT uint32_t SteamAPI_ISteamUser_GetAuthSessionTicket(void *self, uint8_t *ticket, int max,
                                                              uint32_t *len, void *identity) {
    (void)self; (void)identity;
    struct { uint32_t m_hAuthTicket; int32_t m_eResult; } r = { g_next_ticket++, 1 };
    *len = (uint32_t)make_ticket(ticket, max);
    stub_log("GetAuthSessionTicket -> ticket %u", r.m_hAuthTicket);
    push_callback(CB_GET_AUTH_SESSION_TICKET_RESPONSE, &r, sizeof r);
    return r.m_hAuthTicket;
}

STUB_EXPORT uint64_t SteamAPI_ISteamUser_RequestEncryptedAppTicket(void *self, void *data, int size) {
    (void)self; (void)data; (void)size;
    SEEN();
    int32_t result = 1;
    return push_call_result(CB_ENCRYPTED_APP_TICKET_RESPONSE, &result, sizeof result);
}

STUB_EXPORT uint8_t SteamAPI_ISteamUser_GetEncryptedAppTicket(void *self, uint8_t *ticket, int max,
                                                              uint32_t *len) {
    (void)self;
    SEEN();
    *len = (uint32_t)make_ticket(ticket, max);
    return 1;
}

/* ------------------------------------------------------- amigos, apps, utils */

STUB_EXPORT const char *SteamAPI_ISteamFriends_GetPersonaName(void *self) { (void)self; SEEN(); return g_name; }
STUB_EXPORT int32_t SteamAPI_ISteamFriends_GetPersonaState(void *self) { (void)self; return 1; /* online */ }

STUB_EXPORT uint8_t SteamAPI_ISteamApps_BIsSubscribed(void *self) { (void)self; return 1; }
STUB_EXPORT uint8_t SteamAPI_ISteamApps_BIsSubscribedApp(void *self, uint32_t app) { (void)self; return app == APP_ID; }
STUB_EXPORT uint8_t SteamAPI_ISteamApps_BIsAppInstalled(void *self, uint32_t app) { (void)self; return app == APP_ID; }
STUB_EXPORT uint64_t SteamAPI_ISteamApps_GetAppOwner(void *self) { (void)self; return g_steamid; }
STUB_EXPORT const char *SteamAPI_ISteamApps_GetCurrentGameLanguage(void *self) { (void)self; return g_language; }
STUB_EXPORT const char *SteamAPI_ISteamApps_GetAvailableGameLanguages(void *self) { (void)self; return g_language; }

STUB_EXPORT uint32_t SteamAPI_ISteamUtils_GetAppID(void *self) { (void)self; return APP_ID; }
STUB_EXPORT const char *SteamAPI_ISteamUtils_GetIPCountry(void *self) { (void)self; return g_country; }
STUB_EXPORT const char *SteamAPI_ISteamUtils_GetSteamUILanguage(void *self) { (void)self; return g_language; }
STUB_EXPORT uint32_t SteamAPI_ISteamUtils_GetServerRealTime(void *self) { (void)self; return (uint32_t)time(NULL); }
STUB_EXPORT int32_t SteamAPI_ISteamUtils_GetConnectedUniverse(void *self) { (void)self; return 1; /* público */ }
STUB_EXPORT uint8_t SteamAPI_ISteamUtils_GetCurrentBatteryPower(void *self) { (void)self; return 255; }

/* ------------------------------------------------------------ estadísticas */

STUB_EXPORT uint8_t SteamAPI_ISteamUserStats_RequestCurrentStats(void *self) {
    (void)self;
    SEEN();
    /* UserStatsReceived_t: CSteamID va empaquetado a 1, de ahí el desplazamiento 12. */
    uint8_t r[24] = {0};
    uint64_t game = APP_ID;
    int32_t ok = 1;
    memcpy(r, &game, 8);
    memcpy(r + 8, &ok, 4);
    memcpy(r + 12, &g_steamid, 8);
    push_callback(CB_USER_STATS_RECEIVED, r, sizeof r);
    return 1;
}

STUB_EXPORT uint8_t SteamAPI_ISteamUserStats_StoreStats(void *self) { (void)self; return 1; }
