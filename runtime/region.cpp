#include "region.h"
#include "install/verify.h"
#include "log.h"

const Release* g_release = &kReleases[0];
extern "C" bool g_ppcEuCode;

bool Release_Runnable(const Release& r)
{
#ifdef SRR_HAVE_EU
    (void)r;
    return true;
#else
    return !r.euCode;
#endif
}

bool Region_Select(const std::string& dataDir, std::string& error)
{
    const Release* r = Install_DataRelease(dataDir);
    if (!r)
    {
        error = "the game data in " + dataDir + " is not from a supported release (sys/boot.bin)";
        return false;
    }
    if (!Release_Runnable(*r))
    {
        error = std::string("this build of SecretRingsRecomp does not include the ") + r->name +
                " release's code; install the USA or Japanese release, or use a build made with the European main.dol";
        return false;
    }
    g_release = r;
    g_ppcEuCode = r->euCode;
    LOG_INFO("release: {} ({}{})", r->name, r->gameId, r->euCode ? ", European code" : "");
    return true;
}
