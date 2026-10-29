/*
 * SERVER-44991 (WiredTiger WT-5319): the latency of operations that wait for reconciliation of
 * prefix-compressed row-store pages read from disk. Built against each arm's own library and header (run.py).
 *
 *   wt5319 HOME load                    create the table and bulk-load it, checkpoint, close
 *   wt5319 HOME ckpt                    rounds of: update every STRIDE-th key, then a timed checkpoint
 *   wt5319 HOME evict                   THREADS updating random keys for SECS in a small cache; per-update latency
 *
 * Settings from the environment: N keys (2000000), KEYW key width (32: zero-padded decimal, so neighbours share a
 * long prefix), VAL value bytes (100), STRIDE (64), ROUNDS (5), CACHE_MB (1024; evict: SMALL_MB, 64), THREADS (8),
 * SECS (30). Prints one line per round or per run, then the connection's statistics that show the mechanism.
 */
#include <inttypes.h>
#include <math.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wiredtiger.h>

#define CHECK(call)                                                                   \
    do {                                                                              \
        int __r = (call);                                                             \
        if (__r != 0) {                                                               \
            fprintf(stderr, "%s:%d: %s: %s\n", __FILE__, __LINE__, #call, wiredtiger_strerror(__r)); \
            exit(1);                                                                  \
        }                                                                             \
    } while (0)

static uint64_t N, STRIDE, ROUNDS, CACHE_MB, SMALL_MB, THREADS, SECS;
static int KEYW, VAL;
static const char *TABLE_CONFIG =
  "key_format=S,value_format=S,prefix_compression=true,leaf_page_max=32KB,memory_page_max=10MB";

static uint64_t
envu(const char *name, uint64_t dflt)
{
    const char *v = getenv(name);
    return (v != NULL && *v != '\0' ? strtoull(v, NULL, 10) : dflt);
}

static uint64_t
now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ((uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec);
}

static void
mkkey(char *buf, uint64_t i)
{
    snprintf(buf, (size_t)KEYW + 1, "%0*" PRIu64, KEYW, i);
}

static void
mkval(char *buf, uint64_t i, uint64_t round)
{
    memset(buf, 'a' + (int)(round % 26), (size_t)VAL);
    snprintf(buf, 21, "%" PRIu64, i);
    buf[strlen(buf)] = '.';
    buf[VAL] = '\0';
}

static int64_t
stat_get(WT_SESSION *s, int key)
{
    WT_CURSOR *c;
    const char *desc, *pv;
    int64_t v = -1;

    CHECK(s->open_cursor(s, "statistics:", NULL, NULL, &c));
    c->set_key(c, key);
    if (c->search(c) == 0)
        CHECK(c->get_value(c, &desc, &pv, &v));
    CHECK(c->close(c));
    return (v);
}

static void
print_stats(WT_SESSION *s)
{
    printf("stat rec_pages %" PRId64 " rec_pages_eviction %" PRId64 " application_evict_time_us %" PRId64
           " checkpoint_time_recent_ms %" PRId64 " cache_bytes_inuse %" PRId64 "\n",
      stat_get(s, WT_STAT_CONN_REC_PAGES), stat_get(s, WT_STAT_CONN_REC_PAGES_EVICTION),
      stat_get(s, WT_STAT_CONN_APPLICATION_EVICT_TIME), stat_get(s, WT_STAT_CONN_TXN_CHECKPOINT_TIME_RECENT),
      stat_get(s, WT_STAT_CONN_CACHE_BYTES_INUSE));
}

static WT_CONNECTION *
open_conn(const char *home, uint64_t cache_mb, int create)
{
    WT_CONNECTION *conn;
    char cfg[256];

    snprintf(cfg, sizeof(cfg), "%scache_size=%" PRIu64 "MB,statistics=(fast),log=(enabled=false)",
      create ? "create," : "", cache_mb);
    CHECK(wiredtiger_open(home, NULL, cfg, &conn));
    return (conn);
}

static void
do_load(const char *home)
{
    WT_CONNECTION *conn = open_conn(home, CACHE_MB, 1);
    WT_SESSION *s;
    WT_CURSOR *c;
    char *k = malloc((size_t)KEYW + 1), *v = malloc((size_t)VAL + 21);
    uint64_t i, t0 = now_ns();

    CHECK(conn->open_session(conn, NULL, NULL, &s));
    CHECK(s->create(s, "table:t", TABLE_CONFIG));
    CHECK(s->open_cursor(s, "table:t", NULL, "bulk", &c));
    for (i = 0; i < N; i++) {
        mkkey(k, i);
        mkval(v, i, 0);
        c->set_key(c, k);
        c->set_value(c, v);
        CHECK(c->insert(c));
    }
    CHECK(c->close(c));
    CHECK(s->checkpoint(s, NULL));
    printf("load keys %" PRIu64 " ms %.1f\n", N, (double)(now_ns() - t0) / 1e6);
    CHECK(conn->close(conn, NULL));
}

static void
do_ckpt(const char *home)
{
    WT_CONNECTION *conn = open_conn(home, CACHE_MB, 0);
    WT_SESSION *s;
    WT_CURSOR *c;
    char *k = malloc((size_t)KEYW + 1), *v = malloc((size_t)VAL + 21);
    uint64_t i, r, n, t0, t1, t2;

    CHECK(conn->open_session(conn, NULL, NULL, &s));
    CHECK(s->open_cursor(s, "table:t", NULL, NULL, &c));
    for (r = 0; r < ROUNDS; r++) {
        t0 = now_ns();
        for (n = 0, i = r % STRIDE; i < N; i += STRIDE, n++) {
            mkkey(k, i);
            mkval(v, i, r + 1);
            c->set_key(c, k);
            c->set_value(c, v);
            CHECK(c->update(c));
        }
        CHECK(c->reset(c));
        t1 = now_ns();
        CHECK(s->checkpoint(s, NULL));
        t2 = now_ns();
        printf("round %" PRIu64 " updates %" PRIu64 " update_ms %.1f checkpoint_ms %.1f\n", r, n,
          (double)(t1 - t0) / 1e6, (double)(t2 - t1) / 1e6);
        fflush(stdout);
    }
    print_stats(s);
    CHECK(conn->close(conn, NULL));
}

/* Latency histogram: 100 buckets per decade from 100 ns, 9 decades. */
#define HB 900
struct worker {
    WT_CONNECTION *conn;
    uint64_t seed, ops, max_ns, hist[HB];
};
static volatile int stop;

static void *
evict_worker(void *arg)
{
    struct worker *w = arg;
    WT_SESSION *s;
    WT_CURSOR *c;
    char *k = malloc((size_t)KEYW + 1), *v = malloc((size_t)VAL + 21);
    uint64_t x = w->seed, i, t0, d;
    int b;

    CHECK(w->conn->open_session(w->conn, NULL, NULL, &s));
    CHECK(s->open_cursor(s, "table:t", NULL, NULL, &c));
    while (!stop) {
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        i = x % N;
        mkkey(k, i);
        mkval(v, i, w->ops);
        t0 = now_ns();
        c->set_key(c, k);
        c->set_value(c, v);
        CHECK(c->update(c));
        CHECK(c->reset(c));
        d = now_ns() - t0;
        b = d < 100 ? 0 : (int)(log10((double)d / 100.0) * 100.0);
        w->hist[b < HB ? b : HB - 1]++;
        if (d > w->max_ns)
            w->max_ns = d;
        w->ops++;
    }
    CHECK(s->close(s, NULL));
    return (NULL);
}

static double
pct(const uint64_t *h, uint64_t total, double p)
{
    uint64_t want = (uint64_t)(p * (double)total), acc = 0;
    int b;
    for (b = 0; b < HB; b++)
        if ((acc += h[b]) > want)
            return (100.0 * pow(10.0, (b + 1) / 100.0) / 1000.0); /* upper edge, microseconds */
    return (0);
}

static void
do_evict(const char *home)
{
    WT_CONNECTION *conn = open_conn(home, SMALL_MB, 0);
    WT_SESSION *s;
    struct worker *w = calloc(THREADS, sizeof(*w));
    pthread_t *t = calloc(THREADS, sizeof(*t));
    uint64_t h[HB] = {0}, ops = 0, mx = 0, j, t0;
    int b;
    struct timespec ts = {(time_t)SECS, 0};

    CHECK(conn->open_session(conn, NULL, NULL, &s));
    t0 = now_ns();
    for (j = 0; j < THREADS; j++) {
        w[j].conn = conn;
        w[j].seed = 0x9E3779B97F4A7C15ULL * (j + 1);
        pthread_create(&t[j], NULL, evict_worker, &w[j]);
    }
    nanosleep(&ts, NULL);
    stop = 1;
    for (j = 0; j < THREADS; j++) {
        pthread_join(t[j], NULL);
        ops += w[j].ops;
        if (w[j].max_ns > mx)
            mx = w[j].max_ns;
        for (b = 0; b < HB; b++)
            h[b] += w[j].hist[b];
    }
    printf("evict threads %" PRIu64 " secs %.1f updates %" PRIu64 " per_s %.0f p50_us %.1f p99_us %.1f "
           "p999_us %.1f max_us %.1f\n",
      THREADS, (double)(now_ns() - t0) / 1e9, ops, (double)ops / ((double)(now_ns() - t0) / 1e9),
      pct(h, ops, 0.50), pct(h, ops, 0.99), pct(h, ops, 0.999), (double)mx / 1000.0);
    print_stats(s);
    CHECK(conn->close(conn, NULL));
}

int
main(int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "usage: wt5319 HOME load|ckpt|evict\n");
        return (2);
    }
    N = envu("N", 2000000);
    KEYW = (int)envu("KEYW", 32);
    VAL = (int)envu("VAL", 100);
    STRIDE = envu("STRIDE", 64);
    ROUNDS = envu("ROUNDS", 5);
    CACHE_MB = envu("CACHE_MB", 1024);
    SMALL_MB = envu("SMALL_MB", 64);
    THREADS = envu("THREADS", 8);
    SECS = envu("SECS", 30);
    if (strcmp(argv[2], "load") == 0)
        do_load(argv[1]);
    else if (strcmp(argv[2], "ckpt") == 0)
        do_ckpt(argv[1]);
    else if (strcmp(argv[2], "evict") == 0)
        do_evict(argv[1]);
    else
        return (2);
    return (0);
}
