#!/bin/bash

# Directory dove si trova il controller
CONTROLLER_DIR="comnetsemu_dependencies/ryu-v4.34/ryu/ryu/app"
CONTROLLER_FILE="flow_allocator_controller.py"
BASIC_CONTROLLER_FILE="basic_controller.py"

# Check for the basic parameter
if [ "$1" = "basic" ]; then
    CONTROLLER_FILE=$BASIC_CONTROLLER_FILE
    echo "Starting basic controller: $BASIC_CONTROLLER_FILE"
else
    echo "Starting default controller: $CONTROLLER_FILE"
fi

# Avvia il controller Ryu dalla directory corretta
cd $CONTROLLER_DIR

ryu-manager --ofp-tcp-listen-port 6653 --observe-links $CONTROLLER_FILE
