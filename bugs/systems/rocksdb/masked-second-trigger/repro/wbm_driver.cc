// Workload for rocksdb/masked-second-trigger (fix 18eeb7b90e45, parent 1560b2f5f014).
//
// Writes random keys to many column families at a paced rate that is higher than the
// (rate-limited) flush rate, with a small max_total_wal_size and a small db_write_buffer_size,
// automatic compactions off. Samples rocksdb.cur-size-all-mem-tables (aggregated over CFs),
// the number of unflushed immutable memtables and VmRSS every --sample_ms into a CSV, and prints
// one JSON summary line: Put latency (call duration), achieved write rate, process CPU, peak RSS,
// peak memtable bytes, stall micros.
//
// Linked against the arm's own release objects (LIB_SOURCES of that commit, -O2 -DNDEBUG).
#include <rocksdb/db.h>
#include <rocksdb/options.h>
#include <rocksdb/rate_limiter.h>
#include <rocksdb/statistics.h>
#include <rocksdb/write_buffer_manager.h>

#include <sys/resource.h>
#include <unistd.h>
#include <atomic>
#include <chrono>
#include <cinttypes>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <vector>

using namespace rocksdb;
using Clock = std::chrono::steady_clock;

static std::string arg(int argc, char** argv, const char* name, const char* def) {
  std::string key = std::string("--") + name + "=";
  for (int i = 1; i < argc; i++)
    if (strncmp(argv[i], key.c_str(), key.size()) == 0) return argv[i] + key.size();
  return def;
}
static uint64_t argu(int argc, char** argv, const char* name, uint64_t def) {
  std::string s = arg(argc, argv, name, "");
  return s.empty() ? def : strtoull(s.c_str(), nullptr, 10);
}

static long status_kb(const char* field) {
  std::ifstream f("/proc/self/status");
  std::string line;
  size_t n = strlen(field);
  while (std::getline(f, line))
    if (line.compare(0, n, field) == 0) return atol(line.c_str() + n);
  return -1;
}

// Log2-bucketed latency histogram in nanoseconds, 4 sub-buckets per power of two.
struct Hist {
  std::vector<uint64_t> b = std::vector<uint64_t>(64 * 4, 0);
  uint64_t n = 0, sum = 0, max = 0;
  static int idx(uint64_t v) {
    if (v < 4) return (int)v;
    int e = 63 - __builtin_clzll(v);
    int sub = (int)((v >> (e - 2)) & 3);
    return e * 4 + sub;
  }
  static double lo(int i) {
    if (i < 4) return i;
    int e = i / 4, sub = i % 4;
    return std::ldexp(1.0, e) * (1.0 + sub / 4.0);
  }
  void add(uint64_t v) { b[idx(v)]++; n++; sum += v; if (v > max) max = v; }
  void merge(const Hist& o) {
    for (size_t i = 0; i < b.size(); i++) b[i] += o.b[i];
    n += o.n; sum += o.sum; if (o.max > max) max = o.max;
  }
  double pct(double p) const {
    uint64_t want = (uint64_t)std::ceil(p * n), c = 0;
    for (size_t i = 0; i < b.size(); i++) { c += b[i]; if (c >= want && b[i]) return lo((int)i); }
    return (double)max;
  }
};

int main(int argc, char** argv) {
  const std::string path = arg(argc, argv, "db", "/tmp/wbm_driver_db");
  const std::string csv = arg(argc, argv, "csv", "");
  const int ncf = (int)argu(argc, argv, "cfs", 20);
  const double seconds = atof(arg(argc, argv, "seconds", "60").c_str());
  const uint64_t write_rate = argu(argc, argv, "write_rate", 32ull << 20);  // bytes/s, all threads
  const int threads = (int)argu(argc, argv, "threads", 1);
  const size_t value_size = argu(argc, argv, "value_size", 1000);
  const uint64_t sample_ms = argu(argc, argv, "sample_ms", 100);

  Options o;
  o.create_if_missing = true;
  o.create_missing_column_families = true;
  o.db_write_buffer_size = argu(argc, argv, "db_write_buffer_size", 64ull << 20);
  o.write_buffer_size = argu(argc, argv, "write_buffer_size", 64ull << 20);
  o.max_write_buffer_number = (int)argu(argc, argv, "max_write_buffer_number", 4);
  o.max_total_wal_size = argu(argc, argv, "max_total_wal_size", 32ull << 20);
  o.disable_auto_compactions = true;
  o.compression = kNoCompression;
  o.max_background_flushes = (int)argu(argc, argv, "max_background_flushes", 1);
  o.max_background_compactions = 1;
  uint64_t flush_rate = argu(argc, argv, "flush_rate", 8ull << 20);
  if (flush_rate) o.rate_limiter.reset(NewGenericRateLimiter((int64_t)flush_rate));
  o.statistics = CreateDBStatistics();
  o.stats_dump_period_sec = 0;

  std::vector<ColumnFamilyDescriptor> cfds;
  cfds.emplace_back(kDefaultColumnFamilyName, ColumnFamilyOptions(o));
  for (int i = 1; i < ncf; i++)
    cfds.emplace_back("cf" + std::to_string(i), ColumnFamilyOptions(o));
  std::vector<ColumnFamilyHandle*> h;
  DB* db = nullptr;
  Status s = DB::Open(DBOptions(o), path, cfds, &h, &db);
  if (!s.ok()) { fprintf(stderr, "open: %s\n", s.ToString().c_str()); return 1; }

  std::atomic<bool> stop{false};
  std::atomic<uint64_t> bytes_done{0}, ops_done{0}, errors{0};
  std::vector<Hist> hists(threads);
  struct rusage ru0; getrusage(RUSAGE_SELF, &ru0);
  const auto t0 = Clock::now();
  const auto deadline = t0 + std::chrono::duration_cast<Clock::duration>(
                                 std::chrono::duration<double>(seconds));

  // Sampler
  uint64_t peak_mem = 0, peak_imm = 0, peak_act = 0; long peak_rss_kb = 0;
  std::thread sampler([&] {
    FILE* f = csv.empty() ? nullptr : fopen(csv.c_str(), "w");
    if (f) fprintf(f, "t_s,cur_size_all_mem_tables,cur_size_active_mem_tables,num_immutable,rss_kb,mb_written\n");
    while (!stop.load()) {
      uint64_t mem = 0, imm = 0, act = 0;
      db->GetAggregatedIntProperty(DB::Properties::kCurSizeAllMemTables, &mem);
      db->GetAggregatedIntProperty(DB::Properties::kCurSizeActiveMemTable, &act);
      db->GetAggregatedIntProperty(DB::Properties::kNumImmutableMemTable, &imm);
      long rss = status_kb("VmRSS:");
      if (mem > peak_mem) peak_mem = mem;
      if (act > peak_act) peak_act = act;
      if (imm > peak_imm) peak_imm = imm;
      if (rss > peak_rss_kb) peak_rss_kb = rss;
      double t = std::chrono::duration<double>(Clock::now() - t0).count();
      if (f) fprintf(f, "%.2f,%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%ld,%.1f\n", t, mem, act, imm, rss,
                     bytes_done.load() / 1048576.0);
      std::this_thread::sleep_for(std::chrono::milliseconds(sample_ms));
    }
    if (f) fclose(f);
  });

  std::vector<std::thread> ws;
  for (int t = 0; t < threads; t++) {
    ws.emplace_back([&, t] {
      std::mt19937_64 rng(12345 + t);
      std::string value(value_size, 'x');
      for (auto& c : value) c = (char)(rng() & 0xff);
      char key[16];
      const double per_thread_rate = write_rate ? (double)write_rate / threads : 0;
      uint64_t mine = 0;
      WriteOptions wo;
      Hist& hist = hists[t];
      while (Clock::now() < deadline) {
        if (per_thread_rate > 0) {  // pace: op i is due at t0 + i*bytes/rate
          auto due = t0 + std::chrono::duration_cast<Clock::duration>(
                              std::chrono::duration<double>(mine / per_thread_rate));
          if (due > Clock::now()) std::this_thread::sleep_until(due);
          if (Clock::now() >= deadline) break;
        }
        uint64_t r = rng();
        int cf = (int)(r % ncf);
        uint64_t k = rng();
        memcpy(key, &k, 8); memcpy(key + 8, &r, 8);
        // vary a few value bytes so values differ
        memcpy(&value[0], &k, 8);
        auto a = Clock::now();
        Status ps = db->Put(wo, h[cf], Slice(key, 16), value);
        auto b = Clock::now();
        if (!ps.ok()) { errors++; if (errors.load() < 5) fprintf(stderr, "put: %s\n", ps.ToString().c_str()); }
        hist.add((uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(b - a).count());
        mine += 16 + value_size;
        bytes_done += 16 + value_size;
        ops_done++;
      }
    });
  }
  for (auto& w : ws) w.join();
  const double wall = std::chrono::duration<double>(Clock::now() - t0).count();
  stop = true;
  sampler.join();
  struct rusage ru1; getrusage(RUSAGE_SELF, &ru1);
  auto tv = [](const timeval& x) { return x.tv_sec + x.tv_usec / 1e6; };
  double cpu = tv(ru1.ru_utime) - tv(ru0.ru_utime) + tv(ru1.ru_stime) - tv(ru0.ru_stime);
  long hwm_kb = status_kb("VmHWM:");

  Hist all;
  for (auto& x : hists) all.merge(x);
  uint64_t stall_us = o.statistics->getTickerCount(STALL_MICROS);
  uint64_t mem_end = 0;
  db->GetAggregatedIntProperty(DB::Properties::kCurSizeAllMemTables, &mem_end);

  printf("{\"ops\":%" PRIu64 ",\"mb_written\":%.1f,\"wall_s\":%.3f,\"write_mb_s\":%.2f,"
         "\"lat_mean_us\":%.2f,\"lat_p50_us\":%.2f,\"lat_p99_us\":%.2f,\"lat_p999_us\":%.2f,"
         "\"lat_max_ms\":%.2f,\"cpu_s\":%.3f,\"cpu_us_per_op\":%.3f,\"peak_rss_mb\":%.1f,"
         "\"peak_rss_sampled_mb\":%.1f,\"peak_memtables_mb\":%.1f,\"end_memtables_mb\":%.1f,"
         "\"peak_active_memtables_mb\":%.1f,"
         "\"peak_num_immutable\":%" PRIu64 ",\"stall_s\":%.3f,\"errors\":%" PRIu64 ","
         "\"db_write_buffer_mb\":%.1f}\n",
         ops_done.load(), bytes_done.load() / 1048576.0, wall, bytes_done.load() / 1048576.0 / wall,
         all.n ? all.sum / 1e3 / all.n : 0.0, all.pct(0.5) / 1e3, all.pct(0.99) / 1e3,
         all.pct(0.999) / 1e3, all.max / 1e6, cpu, ops_done.load() ? cpu * 1e6 / ops_done.load() : 0.0,
         hwm_kb / 1024.0, peak_rss_kb / 1024.0, peak_mem / 1048576.0, mem_end / 1048576.0,
         peak_act / 1048576.0, peak_imm, stall_us / 1e6, errors.load(), o.db_write_buffer_size / 1048576.0);
  fflush(stdout);
  // Fast exit: the measurement is over; closing would wait for the flush backlog.
  _exit(0);
}
