cmake_minimum_required(VERSION 3.9 FATAL_ERROR)
if (POLICY CMP0069)
    cmake_policy(SET CMP0069 NEW)
endif()

project(SignalServer LANGUAGES CXX)

# ISO standard compliance (C++14)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Optimization & Performance Tuning
option(ENABLE_NATIVE_OPT "Enable CPU native architecture optimization (-march=native)" ON)
option(ENABLE_LTO "Enable Link-Time Optimization (LTO/IPO)" ON)

if (MSVC)
    # Warning level 4 and aggressive optimization
    add_compile_options(/W4 /O2 /Oi /Ot /Gy)
else()
    # Compiler warnings
    add_compile_options(-Wall -Wextra -Wpedantic)
    # Advanced optimization flags for GCC/Clang
    add_compile_options(
        -O3
        -funroll-loops
        -finline-functions
        -fomit-frame-pointer
        -ftree-vectorize
    )

    if (ENABLE_NATIVE_OPT AND NOT CMAKE_CROSSCOMPILING)
        include(CheckCXXCompilerFlag)
        check_cxx_compiler_flag("-march=native" COMPILER_SUPPORTS_MARCH_NATIVE)
        if (COMPILER_SUPPORTS_MARCH_NATIVE)
            add_compile_options(-march=native)
        endif()
    endif()
endif()

if (ENABLE_LTO)
    include(CheckIPOSupported)
    check_ipo_supported(RESULT ipo_supported OUTPUT ipo_error)
    if (ipo_supported)
        set(CMAKE_INTERPROCEDURAL_OPTIMIZATION TRUE)
        message(STATUS "IPO/LTO enabled for all targets.")
    else()
        message(STATUS "IPO/LTO not supported: ${ipo_error}")
    endif()
endif()

# Get GIT commit branch & hash
execute_process(
    COMMAND git rev-parse --abbrev-ref HEAD
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    OUTPUT_VARIABLE GIT_BRANCH
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
execute_process(
    COMMAND git rev-parse --short HEAD
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    OUTPUT_VARIABLE GIT_COMMIT_HASH
    OUTPUT_STRIP_TRAILING_WHITESPACE
)

# Prepare internal libraries search
include_directories(models)

# Spdlog
find_package(spdlog REQUIRED)
include_directories(${spdlog_INCLUDE_DIRS})
if (EXISTS "/home/dedsec/.local/include")
    include_directories("/home/dedsec/.local/include")
endif()
add_compile_definitions(SPDLOG_HEADER_ONLY)

if (TARGET spdlog::spdlog_header_only)
    set(SPDLOG_LIB spdlog::spdlog_header_only)
else()
    set(SPDLOG_LIB spdlog::spdlog)
endif()

# internal libraries
add_library(image STATIC image.cc)
add_library(image-ppm STATIC image-ppm.cc)
add_library(inputs STATIC inputs.cc)
add_library(outputs STATIC outputs.cc)
add_library(tiles STATIC tiles.cc)
add_library(geo STATIC geo.cc)

add_library(cost STATIC models/cost.cc)
add_library(ecc33 STATIC models/ecc33.cc)
add_library(egli STATIC models/egli.cc)
add_library(ericsson STATIC models/ericsson.cc)
add_library(fspl STATIC models/fspl.cc)
add_library(hata STATIC models/hata.cc)
add_library(itwom3.0 STATIC models/itwom3.0.cc)
add_library(two_ray STATIC models/two_ray.cc)
add_library(los STATIC models/los.cc models/egli.cc models/two_ray.cc)
add_library(pel STATIC models/pel.cc)
add_library(soil STATIC models/soil.cc)
add_library(sui STATIC models/sui.cc)

# external libraries
find_library(bz2 bz2)
find_library(pthread pthread)
find_library(z z)

set(PLATFORM_LIBS "")
if (NOT WIN32)
    find_library(dl dl)
    if (dl)
        list(APPEND PLATFORM_LIBS ${dl})
    endif()
else()
    list(APPEND PLATFORM_LIBS ws2_32)
endif()

add_executable(signalserver main.cc)
add_executable(signalserverHD main.cc)
add_executable(signalserverLIDAR main.cc)

target_compile_definitions(
    signalserver PRIVATE
    "-DGIT_COMMIT_HASH=\"${GIT_COMMIT_HASH}\""
    "-DGIT_BRANCH=\"${GIT_BRANCH}\""
)

target_compile_definitions(
    signalserverHD PRIVATE
    "-DGIT_COMMIT_HASH=\"${GIT_COMMIT_HASH}\""
    "-DGIT_BRANCH=\"${GIT_BRANCH}\""
)

target_compile_definitions(
    signalserverLIDAR PRIVATE
    "-DGIT_COMMIT_HASH=\"${GIT_COMMIT_HASH}\""
    "-DGIT_BRANCH=\"${GIT_BRANCH}\""
)

target_link_libraries(signalserver 
			PUBLIC image
			PUBLIC image-ppm
			PUBLIC inputs
			PUBLIC outputs
			PUBLIC tiles
			PUBLIC cost
			PUBLIC ecc33
			PUBLIC egli
			PUBLIC ericsson
			PUBLIC fspl
			PUBLIC hata
			PUBLIC itwom3.0
			PUBLIC two_ray
			PUBLIC los
			PUBLIC pel
			PUBLIC soil
			PUBLIC sui
			PUBLIC bz2
			PUBLIC pthread
			PUBLIC z
			PUBLIC ${PLATFORM_LIBS}
            PUBLIC ${SPDLOG_LIB}
            PUBLIC geo
		  )

target_link_libraries(signalserverHD 
			PUBLIC image
			PUBLIC image-ppm
			PUBLIC inputs
			PUBLIC outputs
			PUBLIC tiles
			PUBLIC cost
			PUBLIC ecc33
			PUBLIC egli
			PUBLIC ericsson
			PUBLIC fspl
			PUBLIC hata
			PUBLIC itwom3.0
			PUBLIC two_ray
			PUBLIC los
			PUBLIC pel
			PUBLIC soil
			PUBLIC sui
			PUBLIC bz2
			PUBLIC pthread
			PUBLIC z
			PUBLIC ${PLATFORM_LIBS}
            PUBLIC ${SPDLOG_LIB}
            PUBLIC geo
		  )

target_link_libraries(signalserverLIDAR 
			PUBLIC image
			PUBLIC image-ppm
			PUBLIC inputs
			PUBLIC outputs
			PUBLIC tiles
			PUBLIC cost
			PUBLIC ecc33
			PUBLIC egli
			PUBLIC ericsson
			PUBLIC fspl
			PUBLIC hata
			PUBLIC itwom3.0
			PUBLIC two_ray
			PUBLIC los
			PUBLIC pel
			PUBLIC soil
			PUBLIC sui
			PUBLIC bz2
			PUBLIC pthread
			PUBLIC z
			PUBLIC ${PLATFORM_LIBS}
            PUBLIC ${SPDLOG_LIB}
            PUBLIC geo
		  )

# INSTALL target (make install)
install(TARGETS signalserver)
install(TARGETS signalserverHD)
install(TARGETS signalserverLIDAR)

