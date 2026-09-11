cmake_minimum_required(VERSION 3.9 FATAL_ERROR)
if (POLICY CMP0069)
    cmake_policy(SET CMP0069 NEW)
endif()

project(usgs2sdf LANGUAGES CXX)

# ISO standard compliance (C++14)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Optimization & Performance Tuning
option(ENABLE_NATIVE_OPT "Enable CPU native architecture optimization (-march=native)" ON)
option(ENABLE_LTO "Enable Link-Time Optimization (LTO/IPO)" ON)

if (MSVC)
    add_compile_options(/W4 /O2 /Oi /Ot /Gy)
else()
    add_compile_options(-Wall -Wextra -Wpedantic)
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
    endif()
endif()

# external libraries
find_library(bz2 bz2)

add_executable(srtm2sdf srtm2sdf.cc)
add_executable(srtm2sdf-hd srtm2sdf.cc)
add_executable(usgs2sdf usgs2sdf.cc)

target_link_libraries(srtm2sdf 
			PUBLIC bz2
		  )

target_link_libraries(srtm2sdf-hd 
			PUBLIC bz2
		  )

# INSTALL target (make install)
install(TARGETS usgs2sdf)
install(TARGETS srtm2sdf)
install(TARGETS srtm2sdf-hd)
