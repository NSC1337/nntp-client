cmake_minimum_required(VERSION 3.20)
project(download_benchmark LANGUAGES C)
find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
find_package(OpenSSL REQUIRED)

set(SOURCE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../src")
add_custom_command(
    OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/cython_openssl.c"
    COMMAND Python::Interpreter -m cython -3
            -I "${SOURCE_ROOT}" -I "${CMAKE_CURRENT_SOURCE_DIR}"
            "${CMAKE_CURRENT_SOURCE_DIR}/cython_openssl.py"
            -o "${CMAKE_CURRENT_BINARY_DIR}/cython_openssl.c"
    DEPENDS cython_openssl.py openssl_api.pxd "${SOURCE_ROOT}/NNTPClient/openssl.pxd"
    VERBATIM
)
Python_add_library(cython_openssl MODULE WITH_SOABI
    "${CMAKE_CURRENT_BINARY_DIR}/cython_openssl.c")
target_link_libraries(cython_openssl PRIVATE OpenSSL::SSL OpenSSL::Crypto)
set_target_properties(cython_openssl PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}")
