#include "verify.h"
#include "releases.h"

#include <cstdio>
#include <cstring>
#include <iterator>
#include <vector>
#include <windows.h>
#include <bcrypt.h>

namespace fs = std::filesystem;

namespace
{
struct KnownFile
{
    const char* path;
    uint64_t size;
    const char* sha1;   // hex
    uint32_t releases;  // Release::mask bits
};

constexpr KnownFile kAllFiles[] = {
#include "releases_files.inc"
};

// The files of one release
struct FileList
{
    uint32_t mask;
    struct It
    {
        const KnownFile* p;
        uint32_t mask;
        void skip() { while (p != std::end(kAllFiles) && !(p->releases & mask)) ++p; }
        const KnownFile& operator*() const { return *p; }
        It& operator++() { ++p; skip(); return *this; }
        bool operator!=(const It& o) const { return p != o.p; }
    };
    It begin() const { It i{ kAllFiles, mask }; i.skip(); return i; }
    It end() const { return { std::end(kAllFiles), mask }; }
};

std::string Hex(const uint8_t* d, size_t n)
{
    static const char* digits = "0123456789abcdef";
    std::string s;
    for (size_t i = 0; i < n; i++) { s += digits[d[i] >> 4]; s += digits[d[i] & 15]; }
    return s;
}

// SHA-1 of a file; false if it cannot be read (or the check was canceled)
bool HashFile(const fs::path& p, std::string& hex, VerifyProgress* progress)
{
    FILE* f = _wfopen(p.c_str(), L"rb");
    if (!f) return false;
    BCRYPT_HASH_HANDLE h = nullptr;
    if (BCryptCreateHash(BCRYPT_SHA1_ALG_HANDLE, &h, nullptr, 0, nullptr, 0, 0) != 0) { fclose(f); return false; }
    std::vector<uint8_t> buf(1 << 20);
    bool ok = true;
    for (;;)
    {
        size_t n = fread(buf.data(), 1, buf.size(), f);
        if (n == 0) break;
        BCryptHashData(h, buf.data(), (ULONG)n, 0);
        if (progress)
        {
            progress->done += n;
            if (progress->cancel) { ok = false; break; }
        }
    }
    uint8_t out[20];
    BCryptFinishHash(h, out, 20, 0);
    BCryptDestroyHash(h);
    fclose(f);
    hex = Hex(out, 20);
    return ok;
}

const KnownFile* Find(const FileList& files, const char* path)
{
    for (auto& k : files)
        if (strcmp(k.path, path) == 0) return &k;
    return nullptr;
}
}   // namespace

const Release* Install_DataRelease(const fs::path& data)
{
    char id[6] = {};
    FILE* f = _wfopen((data / "sys" / "boot.bin").c_str(), L"rb");
    if (!f) return nullptr;
    size_t n = fread(id, 1, 6, f);
    fclose(f);
    return n == 6 ? Release_Find(std::string_view(id, 6)) : nullptr;
}

DataStatus Install_QuickCheck(const fs::path& data, std::string& problem)
{
    std::error_code ec;
    if (!fs::exists(data / "sys" / "main.dol", ec))
    {
        problem = "the game data is not installed";
        return DataStatus::Missing;
    }
    const Release* release = Install_DataRelease(data);
    if (!release)
    {
        problem = "sys/boot.bin is missing or not from a supported release";
        return DataStatus::Corrupt;
    }
    FileList files{ release->mask };
    int bad = 0;
    for (auto& k : files)
    {
        uint64_t size = fs::file_size(data / fs::path(std::u8string((const char8_t*)k.path)), ec);
        if (ec || size != k.size)
        {
            if (bad++ == 0) problem = std::string(k.path) + (ec ? " is missing" : " has the wrong size");
        }
    }
    if (bad > 1) problem += " (and " + std::to_string(bad - 1) + " more)";
    if (bad) return DataStatus::Corrupt;
    // the recompiled code only matches this exact main.dol
    std::string hex;
    const KnownFile* dol = Find(files, "sys/main.dol");
    if (!HashFile(data / "sys" / "main.dol", hex, nullptr) || !dol || hex != dol->sha1)
    {
        problem = std::string("sys/main.dol does not match the supported ") + release->name + " release";
        return DataStatus::Corrupt;
    }
    return DataStatus::Ok;
}

DataStatus Install_FullCheck(const fs::path& data, VerifyProgress& progress, std::string& problem)
{
    DataStatus quick = Install_QuickCheck(data, problem);
    if (quick != DataStatus::Ok) return quick;
    FileList files{ Install_DataRelease(data)->mask };
    uint64_t total = 0;
    for (auto& k : files) total += k.size;
    progress.total = total;
    progress.done = 0;
    int bad = 0;
    for (auto& k : files)
    {
        std::string hex;
        if (!HashFile(data / fs::path(std::u8string((const char8_t*)k.path)), hex, &progress))
        {
            if (progress.cancel) break;
            hex.clear();
        }
        if (hex != k.sha1 && bad++ == 0) problem = std::string(k.path) + " is damaged";
    }
    if (bad > 1) problem += " (and " + std::to_string(bad - 1) + " more)";
    return bad ? DataStatus::Corrupt : DataStatus::Ok;
}
