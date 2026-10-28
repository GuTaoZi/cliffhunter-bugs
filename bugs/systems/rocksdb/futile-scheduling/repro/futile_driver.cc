// futile_driver: workload for rocksdb/futile-scheduling (fix 416943bf2, parent b7e1c5213).
//
// All column families have disable_auto_compactions=true. Optional "cold" column families each hold
// one bottommost L0 file with deletions (so they become marked for bottommost compaction once the
// oldest snapshot passes them). During the measured phase:
//   - one writer thread (paced, --write_rate pairs/s) writes short-lived records to the default CF:
//     Put(k_i, value) then Delete(k_i), keys increasing (a queue / lock-table pattern), so every
//     flushed L0 file is a new bottommost file with deletions;
//   - --snap_threads threads (each paced at --snap_rate/s) loop GetSnapshot / ReleaseSnapshot.
// Measured: per-op latency of Put, Delete, GetSnapshot, ReleaseSnapshot; process CPU (rusage) and
// per-thread-group CPU (schedstat); peak RSS of the interval (VmHWM reset at start) and of the
// process; LOW-priority jobs scheduled (Env::Schedule wrapper = compaction jobs, all futile here
// since auto compactions are off); flushes; tickers. Prints one JSON object on stdout.
#include <atomic>
#include <chrono>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
#include <dirent.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>

#include "rocksdb/db.h"
#include "rocksdb/env.h"
#include "rocksdb/listener.h"
#include "rocksdb/options.h"
#include "rocksdb/statistics.h"

using namespace rocksdb;

static std::map<std::string, std::string> g_args;
static std::string Arg(const char* k, const char* d) {
  auto it = g_args.find(k);
  return it == g_args.end() ? std::string(d) : it->second;
}
static long long ArgI(const char* k, long long d) {
  auto it = g_args.find(k);
  return it == g_args.end() ? d : atoll(it->second.c_str());
}

static inline uint64_t NowNs() {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return uint64_t(ts.tv_sec) * 1000000000ull + ts.tv_nsec;
}

// Log-linear histogram in ns: 32 sub-buckets per power of two.
struct Hist {
  static const int kSub = 32;
  std::vector<uint64_t> b;
  uint64_t n = 0, sum = 0, mx = 0;
  Hist() : b(64 * kSub, 0) {}
  static int Idx(uint64_t v) {
    if (v < kSub) return int(v);
    int msb = 63 - __builtin_clzll(v);
    int shift = msb - 5;  // log2(kSub)=5
    int sub = int((v >> shift) & (kSub - 1));
    return (msb - 4) * kSub + sub;
  }
  static uint64_t Lo(int i) {
    if (i < kSub) return uint64_t(i);
    int msb = i / kSub + 4;
    int sub = i % kSub;
    return (uint64_t(kSub) | sub) << (msb - 5);
  }
  void Add(uint64_t v) {
    b[Idx(v)]++;
    n++;
    sum += v;
    if (v > mx) mx = v;
  }
  void Merge(const Hist& o) {
    for (size_t i = 0; i < b.size(); i++) b[i] += o.b[i];
    n += o.n;
    sum += o.sum;
    if (o.mx > mx) mx = o.mx;
  }
  double Pct(double p) const {
    if (n == 0) return 0;
    uint64_t want = uint64_t(p / 100.0 * n);
    if (want >= n) want = n - 1;
    uint64_t c = 0;
    for (size_t i = 0; i < b.size(); i++) {
      c += b[i];
      if (c > want) return double(Lo(int(i)));
    }
    return double(mx);
  }
  std::string Json() const {
    char buf[512];
    snprintf(buf, sizeof(buf),
             "{\"n\":%" PRIu64 ",\"mean_us\":%.3f,\"p50_us\":%.3f,\"p99_us\":%.3f,"
             "\"p999_us\":%.3f,\"max_us\":%.3f}",
             n, n ? sum / 1000.0 / n : 0.0, Pct(50) / 1000.0, Pct(99) / 1000.0,
             Pct(99.9) / 1000.0, mx / 1000.0);
    return buf;
  }
};

// Counts LOW-priority (compaction) and HIGH-priority (flush) jobs handed to the thread pools.
class CountingEnv : public EnvWrapper {
 public:
  explicit CountingEnv(Env* t) : EnvWrapper(t) {}
  std::atomic<uint64_t> low{0}, high{0}, other{0};
  void Schedule(void (*f)(void* arg), void* a, Priority pri, void* tag,
                void (*u)(void* arg)) override {
    if (pri == Env::Priority::LOW)
      low++;
    else if (pri == Env::Priority::HIGH)
      high++;
    else
      other++;
    EnvWrapper::Schedule(f, a, pri, tag, u);
  }
};

class FlushCounter : public EventListener {
 public:
  std::atomic<uint64_t> flushes{0};
  void OnFlushCompleted(DB*, const FlushJobInfo&) override { flushes++; }
};

// CPU ns per thread-name group, from /proc/self/task/*/schedstat.
static std::map<std::string, uint64_t> ThreadCpu() {
  std::map<std::string, uint64_t> out;
  DIR* d = opendir("/proc/self/task");
  if (!d) return out;
  struct dirent* e;
  while ((e = readdir(d)) != nullptr) {
    if (e->d_name[0] == '.') continue;
    std::string base = std::string("/proc/self/task/") + e->d_name;
    std::ifstream c(base + "/comm"), s(base + "/schedstat");
    std::string comm;
    uint64_t ns = 0;
    if (!std::getline(c, comm) || !(s >> ns)) continue;
    std::string g = comm;
    if (g.compare(0, 11, "rocksdb:low") == 0)
      g = "rocksdb:low";
    else if (g.compare(0, 12, "rocksdb:high") == 0)
      g = "rocksdb:high";
    else if (g.compare(0, 4, "snap") == 0)
      g = "snap";
    out[g] += ns;
  }
  closedir(d);
  return out;
}

static long StatusKb(const char* key) {
  std::ifstream f("/proc/self/status");
  std::string line;
  size_t kl = strlen(key);
  while (std::getline(f, line))
    if (line.compare(0, kl, key) == 0) return atol(line.c_str() + kl + 1);
  return -1;
}

static double CpuS(const struct rusage& r) {
  return r.ru_utime.tv_sec + r.ru_utime.tv_usec / 1e6 + r.ru_stime.tv_sec +
         r.ru_stime.tv_usec / 1e6;
}

// Paced loop: calls op() rate times per second, in 1 ms ticks, until stop.
template <class F>
static void Paced(long long rate, std::atomic<bool>* stop, F op) {
  const uint64_t tick = 1000000;  // 1 ms
  uint64_t t0 = NowNs();
  uint64_t done = 0;
  while (!stop->load(std::memory_order_relaxed)) {
    if (rate <= 0) {
      op();
      continue;
    }
    uint64_t now = NowNs();
    uint64_t due = (now - t0) * uint64_t(rate) / 1000000000ull;
    while (done < due && !stop->load(std::memory_order_relaxed)) {
      op();
      done++;
    }
    uint64_t next = t0 + ((now - t0) / tick + 1) * tick;
    uint64_t n2 = NowNs();
    if (n2 < next) {
      struct timespec ts;
      ts.tv_sec = (next - n2) / 1000000000ull;
      ts.tv_nsec = (next - n2) % 1000000000ull;
      nanosleep(&ts, nullptr);
    }
  }
}

int main(int argc, char** argv) {
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    if (a.compare(0, 2, "--") != 0) continue;
    size_t eq = a.find('=');
    if (eq == std::string::npos)
      g_args[a.substr(2)] = "1";
    else
      g_args[a.substr(2, eq - 2)] = a.substr(eq + 1);
  }
  const std::string path = Arg("db", "");
  if (path.empty()) {
    fprintf(stderr, "--db required\n");
    return 2;
  }
  const long long seconds = ArgI("seconds", 20);
  const long long cold_cfs = ArgI("cold_cfs", 0);
  const long long cold_keys = ArgI("cold_keys", 2000);
  const long long write_rate = ArgI("write_rate", 20000);  // put+delete pairs per second
  const long long value_size = ArgI("value_size", 1024);
  const long long snap_rate = ArgI("snap_rate", 20000);  // per thread, 0 = unpaced
  const long long snap_threads = ArgI("snap_threads", 1);
  const long long wbs = ArgI("write_buffer_size", 1 << 20);
  const bool stats_all = ArgI("stats_all", 0) != 0;

  CountingEnv* env = new CountingEnv(Env::Default());
  auto listener = std::make_shared<FlushCounter>();
  Options opt;
  opt.env = env;
  opt.create_if_missing = true;
  opt.create_missing_column_families = true;
  opt.disable_auto_compactions = true;
  opt.write_buffer_size = size_t(wbs);
  opt.max_write_buffer_number = 4;
  opt.compression = kNoCompression;
  opt.statistics = CreateDBStatistics();
  opt.statistics->set_stats_level(stats_all ? StatsLevel::kAll
                                            : StatsLevel::kExceptTimeForMutex);
  opt.listeners.push_back(listener);

  std::vector<ColumnFamilyDescriptor> cfds;
  cfds.push_back(ColumnFamilyDescriptor(kDefaultColumnFamilyName, opt));
  for (long long c = 0; c < cold_cfs; c++) {
    char nm[32];
    snprintf(nm, sizeof(nm), "cold%04lld", c);
    cfds.push_back(ColumnFamilyDescriptor(nm, opt));
  }
  std::vector<ColumnFamilyHandle*> hs;
  DB* db = nullptr;
  Status s = DB::Open(DBOptions(opt), path, cfds, &hs, &db);
  if (!s.ok()) {
    fprintf(stderr, "open: %s\n", s.ToString().c_str());
    return 1;
  }
  WriteOptions wo;
  std::string cval(64, 'c');
  // Setup: each cold CF gets one L0 file with cold_keys puts and cold_keys/2 deletes.
  for (long long c = 0; c < cold_cfs; c++) {
    ColumnFamilyHandle* h = hs[size_t(c + 1)];
    char k[32];
    for (long long i = 0; i < cold_keys; i++) {
      snprintf(k, sizeof(k), "k%010lld", i);
      db->Put(wo, h, k, cval);
    }
    for (long long i = 0; i < cold_keys; i += 2) {
      snprintf(k, sizeof(k), "k%010lld", i);
      db->Delete(wo, h, k);
    }
    FlushOptions fo;
    fo.wait = true;
    s = db->Flush(fo, h);
    if (!s.ok()) {
      fprintf(stderr, "flush: %s\n", s.ToString().c_str());
      return 1;
    }
  }
  std::this_thread::sleep_for(std::chrono::milliseconds(1000));

  // Measured phase.
  std::shared_ptr<Logger> log = db->GetOptions().info_log;
  Log(InfoLogLevel::WARN_LEVEL, log, "CH_MEASURE_START");
  { std::ofstream cr("/proc/self/clear_refs"); cr << "5"; }  // reset VmHWM
  struct rusage r0, r1;
  getrusage(RUSAGE_SELF, &r0);
  auto tc0 = ThreadCpu();
  uint64_t low0 = env->low, high0 = env->high, fl0 = listener->flushes;
  uint64_t mw0 = opt.statistics->getTickerCount(DB_MUTEX_WAIT_MICROS);
  uint64_t w0 = NowNs();

  std::atomic<bool> stop{false};
  Hist hput, hdel;
  const size_t nsnap = size_t(snap_threads);
  std::vector<Hist> hget(nsnap), hrel(nsnap);
  std::thread writer([&] {
    pthread_setname_np(pthread_self(), "writer");
    std::string val(size_t(value_size), 'v');
    char k[32];
    uint64_t i = 0;
    ColumnFamilyHandle* h = hs[0];
    Paced(write_rate, &stop, [&] {
      snprintf(k, sizeof(k), "h%016" PRIu64, i++);
      uint64_t a = NowNs();
      db->Put(wo, h, k, val);
      uint64_t b = NowNs();
      db->Delete(wo, h, k);
      uint64_t c = NowNs();
      hput.Add(b - a);
      hdel.Add(c - b);
    });
  });
  std::vector<std::thread> snaps;
  for (long long t = 0; t < snap_threads; t++) {
    snaps.emplace_back([&, t] {
      char nm[16];
      snprintf(nm, sizeof(nm), "snap%lld", t);
      pthread_setname_np(pthread_self(), nm);
      Hist& hg = hget[size_t(t)];
      Hist& hr = hrel[size_t(t)];
      Paced(snap_rate, &stop, [&] {
        uint64_t a = NowNs();
        const Snapshot* sn = db->GetSnapshot();
        uint64_t b = NowNs();
        db->ReleaseSnapshot(sn);
        uint64_t c = NowNs();
        hg.Add(b - a);
        hr.Add(c - b);
      });
    });
  }
  std::this_thread::sleep_for(std::chrono::seconds(seconds));
  stop = true;
  writer.join();
  for (auto& t : snaps) t.join();
  uint64_t w1 = NowNs();
  getrusage(RUSAGE_SELF, &r1);
  auto tc1 = ThreadCpu();
  uint64_t low1 = env->low, high1 = env->high, fl1 = listener->flushes;
  uint64_t mw1 = opt.statistics->getTickerCount(DB_MUTEX_WAIT_MICROS);
  long hwm_kb = StatusKb("VmHWM:");
  Log(InfoLogLevel::WARN_LEVEL, log, "CH_MEASURE_END");

  Hist hg, hr;
  for (auto& h : hget) hg.Merge(h);
  for (auto& h : hrel) hr.Merge(h);
  std::string l0, pend, l0cold;
  db->GetProperty(hs[0], "rocksdb.num-files-at-level0", &l0);
  db->GetProperty(hs[0], "rocksdb.compaction-pending", &pend);
  if (cold_cfs > 0) db->GetProperty(hs[1], "rocksdb.num-files-at-level0", &l0cold);
  double wall = (w1 - w0) / 1e9;
  std::ostringstream o;
  o << "{\"wall_s\":" << wall << ",\"cpu_s\":" << (CpuS(r1) - CpuS(r0))
    << ",\"peak_rss_mb\":" << hwm_kb / 1024.0
    << ",\"process_maxrss_mb\":" << r1.ru_maxrss / 1024.0
    << ",\"vol_ctxsw\":" << (r1.ru_nvcsw - r0.ru_nvcsw)
    << ",\"invol_ctxsw\":" << (r1.ru_nivcsw - r0.ru_nivcsw) << ",\"thread_cpu_s\":{";
  bool first = true;
  for (auto& kv : tc1) {
    uint64_t before = tc0.count(kv.first) ? tc0[kv.first] : 0;
    o << (first ? "" : ",") << "\"" << kv.first << "\":" << (kv.second - before) / 1e9;
    first = false;
  }
  o << "},\"low_jobs\":" << (low1 - low0) << ",\"high_jobs\":" << (high1 - high0)
    << ",\"flushes\":" << (fl1 - fl0) << ",\"db_mutex_wait_us\":" << (mw1 - mw0)
    << ",\"put\":" << hput.Json() << ",\"delete\":" << hdel.Json()
    << ",\"get_snapshot\":" << hg.Json() << ",\"release_snapshot\":" << hr.Json()
    << ",\"pairs_per_s\":" << hput.n / wall << ",\"snaps_per_s\":" << hr.n / wall
    << ",\"l0_files_default\":\"" << l0 << "\",\"l0_files_cold0\":\"" << l0cold
    << "\",\"compaction_pending\":\"" << pend << "\"}";
  printf("%s\n", o.str().c_str());
  fflush(stdout);
  for (auto* h : hs) db->DestroyColumnFamilyHandle(h);
  delete db;
  delete env;
  return 0;
}
