// epanet-pressures: load an EPANET .inp file, run an extended-period
// hydraulic simulation and print the pressure at every node for every
// hydraulic time step, using the thread-safe EN_ (project handle) API.
//
// Usage: epanet-pressures <input.inp> [report.rpt]

#include <cstdio>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "epanet2_2.h"

namespace {

#ifdef _WIN32
const char *kNullDevice = "NUL";
#else
const char *kNullDevice = "/dev/null";
#endif

// Throws on errors (codes > 100); codes 1-6 are warnings and are reported.
void check(int code, const char *call)
{
    if (code == 0) return;
    char msg[EN_MAXMSG + 1] = "";
    EN_geterror(code, msg, EN_MAXMSG);
    if (code > 100)
        throw std::runtime_error(std::string(call) + " failed: " + msg);
    std::cerr << "warning: " << call << ": " << msg << "\n";
}

// Owns an EN_Project so it is always closed and deleted.
class Project {
public:
    Project() { check(EN_createproject(&ph_), "EN_createproject"); }
    ~Project()
    {
        EN_close(ph_);
        EN_deleteproject(ph_);
    }
    Project(const Project &) = delete;
    Project &operator=(const Project &) = delete;
    EN_Project get() const { return ph_; }

private:
    EN_Project ph_ = nullptr;
};

const char *nodeTypeName(int type)
{
    switch (type) {
    case EN_JUNCTION:  return "Junction";
    case EN_RESERVOIR: return "Reservoir";
    case EN_TANK:      return "Tank";
    default:           return "?";
    }
}

const char *pressureUnitName(int units)
{
    switch (units) {
    case EN_PSI:    return "psi";
    case EN_KPA:    return "kPa";
    case EN_METERS: return "m";
    case EN_BAR:    return "bar";
    case EN_FEET:   return "ft";
    default:        return "?";
    }
}

std::string clock(long seconds)
{
    char buf[32];
    std::snprintf(buf, sizeof buf, "%ld:%02ld:%02ld", seconds / 3600,
                  (seconds % 3600) / 60, seconds % 60);
    return buf;
}

struct Node {
    std::string id;
    int type;
};

int run(const char *inpFile, const char *rptFile)
{
    Project project;
    EN_Project ph = project.get();

    int version = 0;
    EN_getversion(&version);
    std::cout << "EPANET toolkit " << version / 10000 << "."
              << (version % 10000) / 100 << "." << version % 100 << "\n";

    // Read the network (no binary output file is needed).
    check(EN_open(ph, inpFile, rptFile, ""), "EN_open");

    int nodeCount = 0, linkCount = 0, tankCount = 0;
    check(EN_getcount(ph, EN_NODECOUNT, &nodeCount), "EN_getcount");
    check(EN_getcount(ph, EN_LINKCOUNT, &linkCount), "EN_getcount");
    check(EN_getcount(ph, EN_TANKCOUNT, &tankCount), "EN_getcount");

    double pressUnits = 0;
    check(EN_getoption(ph, EN_PRESS_UNITS, &pressUnits), "EN_getoption");
    const char *unit = pressureUnitName(static_cast<int>(pressUnits));

    long duration = 0;
    check(EN_gettimeparam(ph, EN_DURATION, &duration), "EN_gettimeparam");

    std::cout << "Network:  " << inpFile << "\n"
              << "Nodes:    " << nodeCount << " (" << nodeCount - tankCount
              << " junctions, " << tankCount << " tanks/reservoirs)\n"
              << "Links:    " << linkCount << "\n"
              << "Duration: " << clock(duration) << "\n";

    // Node IDs and types are 1-based in the toolkit.
    std::vector<Node> nodes(nodeCount);
    for (int i = 1; i <= nodeCount; ++i) {
        char id[EN_MAXID + 1] = "";
        check(EN_getnodeid(ph, i, id), "EN_getnodeid");
        check(EN_getnodetype(ph, i, &nodes[i - 1].type), "EN_getnodetype");
        nodes[i - 1].id = id;
    }

    // Step through the extended-period hydraulic simulation.
    check(EN_openH(ph), "EN_openH");
    check(EN_initH(ph, EN_NOSAVE), "EN_initH");

    long t = 0, tstep = 0;
    int periods = 0;
    do {
        check(EN_runH(ph, &t), "EN_runH");
        ++periods;
        std::cout << "\nTime " << clock(t) << "\n"
                  << std::left << std::setw(12) << "Node" << std::setw(11)
                  << "Type" << std::right << std::setw(12)
                  << (std::string("Pressure ") + unit) << "\n";
        for (int i = 1; i <= nodeCount; ++i) {
            double p = 0;
            check(EN_getnodevalue(ph, i, EN_PRESSURE, &p), "EN_getnodevalue");
            std::cout << std::left << std::setw(12) << nodes[i - 1].id
                      << std::setw(11) << nodeTypeName(nodes[i - 1].type)
                      << std::right << std::setw(12) << std::fixed
                      << std::setprecision(2) << p << "\n";
        }
        check(EN_nextH(ph, &tstep), "EN_nextH");
    } while (tstep > 0);

    check(EN_closeH(ph), "EN_closeH");
    std::cout << "\nSimulation complete: " << periods << " hydraulic time steps.\n";
    return EXIT_SUCCESS;
}

} // namespace

int main(int argc, char *argv[])
{
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <input.inp> [report.rpt]\n";
        return EXIT_FAILURE;
    }
    try {
        return run(argv[1], argc > 2 ? argv[2] : kNullDevice);
    } catch (const std::exception &e) {
        std::cerr << "error: " << e.what() << "\n";
        return EXIT_FAILURE;
    }
}
