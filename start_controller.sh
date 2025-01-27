#!/bin/bash

# Directory dove si trova il controller
CONTROLLER_DIR="comnetsemu_dependencies/ryu-v4.34/ryu/ryu/app"
CONTROLLER_FILE="flow_allocator_controller.py"

# Avvia il controller Ryu dalla directory corretta
cd $CONTROLLER_DIR

ryu-manager --ofp-tcp-listen-port 6653 --observe-links $CONTROLLER_FILE
