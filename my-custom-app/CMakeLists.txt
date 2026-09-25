# my-custom-app: C++ command-line tool built on the EPANET 2.3 toolkit.
#
# Build (from this folder):
#   cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
#   cmake --build build
#   ./build/bin/epanet-pressures ../example-networks/Net1.inp

cmake_minimum_required(VERSION 3.8)

project(MyCustomEpanetApp LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Put our binaries and the EPANET library side by side.
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)

# Build the repo's EPANET engine as part of this project. EXCLUDE_FROM_ALL
# means only the targets we link against (the epanet2 library) get built,
# not runepanet or the output-file library.
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/.. epanet EXCLUDE_FROM_ALL)

add_executable(epanet-pressures src/main.cpp)

# epanet2 exports its include/ folder publicly, so the headers come along.
target_link_libraries(epanet-pressures PRIVATE epanet2)
if(NOT WIN32)
  target_link_libraries(epanet-pressures PRIVATE m)
endif()
