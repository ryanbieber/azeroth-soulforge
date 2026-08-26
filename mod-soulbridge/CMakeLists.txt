cmake_minimum_required(VERSION 3.16)

if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
  project(soulbridge_scaffold LANGUAGES CXX)
  enable_testing()
endif()

add_library(soulbridge_queue STATIC
  src/SoulBridgeQueue.cpp
)
target_include_directories(soulbridge_queue PUBLIC src)
target_compile_features(soulbridge_queue PUBLIC cxx_std_17)
target_compile_options(soulbridge_queue PRIVATE -Wall -Wextra -Wpedantic)

if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
  add_executable(soulbridge_queue_test tests/SoulBridgeQueueTest.cpp)
  target_link_libraries(soulbridge_queue_test PRIVATE soulbridge_queue)
  add_test(NAME soulbridge_queue_test COMMAND soulbridge_queue_test)
endif()
