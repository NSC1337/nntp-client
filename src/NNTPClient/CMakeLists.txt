cmake_minimum_required(VERSION 3.15...4.4)
project(nntp_client LANGUAGES C CXX)

find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
find_package(OpenSSL REQUIRED COMPONENTS SSL Crypto)

set(PACKAGE_NAME NNTPClient)

function(add_cython_module target module_name source destination)
    set(generated "${CMAKE_CURRENT_BINARY_DIR}/${module_name}.cpp")

    add_custom_command(
        OUTPUT "${generated}"
        COMMAND "${Python_EXECUTABLE}" -m cython --cplus -3
            -I "${CMAKE_CURRENT_SOURCE_DIR}" -I "${CMAKE_CURRENT_SOURCE_DIR}/parser"
            --output-file "${generated}" "${source}"
        DEPENDS "${source}" ${ARGN}
        COMMENT "Cythonizing ${source}"
        VERBATIM
    )

    Python_add_library(${target} MODULE WITH_SOABI "${generated}")
    set_target_properties(${target} PROPERTIES OUTPUT_NAME "${module_name}")
    install(TARGETS ${target} LIBRARY DESTINATION "${destination}" RUNTIME DESTINATION "${destination}")
endfunction()

add_subdirectory(parser/rapidyenc EXCLUDE_FROM_ALL)

add_cython_module(parser_python parser "${CMAKE_CURRENT_SOURCE_DIR}/parser/parser.pyx" "${PACKAGE_NAME}/parser"
    "${CMAKE_CURRENT_SOURCE_DIR}/parser/rapidyenc.pxd"
    "${CMAKE_CURRENT_SOURCE_DIR}/parser/rapidyenc/rapidyenc.h"
)
target_include_directories(parser_python PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/parser")
target_link_libraries(parser_python PRIVATE rapidyenc_static)

add_cython_module(connection_python connection "${CMAKE_CURRENT_SOURCE_DIR}/connection.py" "${PACKAGE_NAME}"
    "${CMAKE_CURRENT_SOURCE_DIR}/openssl.pxd"
)
target_link_libraries(connection_python PRIVATE OpenSSL::SSL OpenSSL::Crypto)

install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/__init__.py" DESTINATION "${PACKAGE_NAME}")
install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/parser/__init__.py" "${CMAKE_CURRENT_SOURCE_DIR}/parser/parser.pyi"
    DESTINATION "${PACKAGE_NAME}/parser")
