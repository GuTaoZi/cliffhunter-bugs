// bottom_loop: workload for the bottommost-files compaction loops of queue ranks 8 and 9
// (rocksdb/marking-ignores-progress, fix f7b791b21; rocksdb/marking-ignores-progress-3, fix eca47fb69).
//
// Setup (as in the fixes' unit tests, larger): level compaction; --keys keys of --value_size bytes written twice
// (so the bottommost file holds overwritten versions), flushed and moved to L1, the bottommost non-empty level; one
// more key written and flushed to bump the sequence number; a snapshot taken and released, which moves the oldest
// snapshot past the file and makes it eligible for bottommost-files marking. Then --seconds of idleness, measured:
// the database does nothing unless a compaction loop runs. With --ingest_behind (rank 9) the last level is reserved
// so sequence numbers can never be zeroed; with --preserve_seconds (rank 8) the preserve window keeps them.
//
// Measured over the idle window: compactions completed by reason (an EventListener), bytes written by compaction,
// process CPU (rusage), peak RSS (VmHWM reset at the window's start), MANIFEST size before and after. One JSON line.
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <dirent.h>
#include <sys/resource.h>
#include <sys/stat.h>

#include "rocksdb/db.h"
#include "rocksdb/listener.h"
#include "rocksdb/options.h"
#include "rocksdb/statistics.h"

using namespace ROCKSDB_NAMESPACE;

static std::map<std::string, std::string> g_args;
static long long ArgI(const char* k, long long d) {
  auto it = g_args.find(k);
  return it == g_args.end() ? d : atoll(it->second.c_str());
}
static std::string Arg(const char* k, const char* d) {
  auto it = g_args.find(k);
  return it == g_args.end() ? std::string(d) : it->second;
}

struct Counter : public EventListener {
  std::mutex mu;
  std::map<int, long long> by_reason;
  std::atomic<long long> total{0}, bytes{0};
  void OnCompactionCompleted(DB*, const CompactionJobInfo& ci) override {
    std::lock_guard<std::mutex> l(mu);
    by_reason[static_cast<int>(ci.compaction_reason)]++;
    total++;
    bytes += ci.stats.total_output_bytes;
  }
};

static double CpuS() {
  struct rusage ru;
  getrusage(RUSAGE_SELF, &ru);
  return ru.ru_utime.tv_sec + ru.ru_utime.tv_usec / 1e6 + ru.ru_stime.tv_sec + ru.ru_stime.tv_usec / 1e6;
}
static void ResetHwm() {
  std::ofstream f("/proc/self/clear_refs");
  f << "5";
}
static double HwmMb() {
  std::ifstream f("/proc/self/status");
  std::string line;
  while (std::getline(f, line))
    if (line.rfind("VmHWM:", 0) == 0) return atof(line.c_str() + 6) / 1024.0;
  return 0;
}
static long long ManifestBytes(const std::string& dir) {
  long long n = 0;
  DIR* d = opendir(dir.c_str());
  if (!d) return 0;
  while (dirent* e = readdir(d)) {
    std::string f = e->d_name;
    if (f.rfind("MANIFEST-", 0) == 0) {
      struct stat st;
      if (stat((dir + "/" + f).c_str(), &st) == 0) n += st.st_size;
    }
  }
  closedir(d);
  return n;
}

int main(int argc, char** argv) {
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    if (a.rfind("--", 0) == 0) {
      auto eq = a.find('=');
      g_args[a.substr(2, eq == std::string::npos ? std::string::npos : eq - 2)] =
          eq == std::string::npos ? "1" : a.substr(eq + 1);
    }
  }
  std::string path = Arg("db", "/tmp/bottom_loop_db");
  long long keys = ArgI("keys", 100000), vsize = ArgI("value_size", 1000), secs = ArgI("seconds", 30);

  Options o;
  o.create_if_missing = true;
  o.compaction_style = kCompactionStyleLevel;
  o.allow_ingest_behind = ArgI("ingest_behind", 0) != 0;
#ifdef BOTTOM_LOOP_PRESERVE
  o.preserve_internal_time_seconds = ArgI("preserve_seconds", 0);
#endif
  o.statistics = CreateDBStatistics();
  auto counter = std::make_shared<Counter>();
  o.listeners.push_back(counter);
#ifdef BOTTOM_LOOP_UNIQUE  // 2026 RocksDB opens into a std::unique_ptr<DB>
  std::unique_ptr<DB> dbp;
  Status s = DB::Open(o, path, &dbp);
  DB* db = dbp.get();
#else
  DB* db = nullptr;
  Status s = DB::Open(o, path, &db);
#endif
  if (!s.ok()) { fprintf(stderr, "open: %s\n", s.ToString().c_str()); return 1; }

  std::string v(vsize, 'x');
  WriteOptions wo;
  char k[32];
  // --spread_s: spread the writes over this many seconds (rank 8: the preserve window needs a seqno-to-time
  // mapping, which RocksDB records periodically while the database is open; the fix's test uses a mock clock).
  long long spread = ArgI("spread_s", 0), chunk = keys / 10 > 0 ? keys / 10 : 1;
  for (int round = 0; round < 2; round++)
    for (long long i = 0; i < keys; i++) {
      snprintf(k, sizeof k, "key%012lld", i);
      v[0] = 'a' + round;
      db->Put(wo, k, v);
      if (spread > 0 && (i + 1) % chunk == 0)
        std::this_thread::sleep_for(std::chrono::milliseconds(spread * 1000 / 20));
    }
  db->Flush(FlushOptions());
  CompactRangeOptions cro;
  cro.change_level = true;
  cro.target_level = static_cast<int>(ArgI("target_level", 1));  // rank 8's test uses the last level (6)
  db->CompactRange(cro, nullptr, nullptr);
  db->Put(wo, "zzz-bump-seqnum", "");
  db->Flush(FlushOptions());
  const Snapshot* snap = db->GetSnapshot();
  db->ReleaseSnapshot(snap);

  long long c0 = counter->total, b0 = counter->bytes, m0 = ManifestBytes(path);
  double cpu0 = CpuS();
  ResetHwm();
  auto t0 = std::chrono::steady_clock::now();
  std::this_thread::sleep_for(std::chrono::seconds(secs));
  double wall = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  double cpu = CpuS() - cpu0, hwm = HwmMb();
  long long c1 = counter->total, b1 = counter->bytes, m1 = ManifestBytes(path);
  std::string reasons;
  {
    std::lock_guard<std::mutex> l(counter->mu);
    for (auto& kv : counter->by_reason) reasons += (reasons.empty() ? "" : ",") + std::to_string(kv.first) + ":" +
                                                    std::to_string(kv.second);
  }
  uint64_t cw = o.statistics->getTickerCount(COMPACT_WRITE_BYTES);
  printf("{\"wall_s\": %.3f, \"cpu_s\": %.3f, \"peak_rss_mb\": %.1f, \"compactions_in_window\": %lld, "
         "\"compactions_total\": %lld, \"compaction_output_mb_in_window\": %.1f, \"compact_write_mb_total\": %.1f, "
         "\"manifest_bytes_before\": %lld, \"manifest_bytes_after\": %lld, \"reasons_total\": \"%s\"}\n",
         wall, cpu, hwm, c1 - c0, c1, (b1 - b0) / 1048576.0, cw / 1048576.0, m0, m1, reasons.c_str());
#ifndef BOTTOM_LOOP_UNIQUE
  delete db;
#endif
  return 0;
}
