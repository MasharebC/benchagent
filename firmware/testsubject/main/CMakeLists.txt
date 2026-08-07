idf_component_register(SRCS "main.c" "bme280.c"
                       INCLUDE_DIRS ".")
# Planted-bug flags: idf.py -DBUG=WDT_STARVE reconfigure && idf.py build
if(DEFINED BUG)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE
        "BUG_${BUG}" "BUG_FLAGS_STR=\"BUG_${BUG}\"")
endif()
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
