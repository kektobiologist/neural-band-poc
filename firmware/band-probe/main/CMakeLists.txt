if(CONFIG_BAND_OWNER_AUTH AND NOT EXISTS "${CMAKE_CURRENT_LIST_DIR}/owner_identity.h")
    message(FATAL_ERROR "Provision the enrolled owner PEM with firmware/band-probe/provision_identity.py first")
endif()
idf_component_register(SRCS "band_probe.c" "band_protocol.c" "ac_control.c" "ac_logic.c" INCLUDE_DIRS ".")
