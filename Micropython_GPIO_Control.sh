#!/bin/bash

# Check for required arguments
if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <pin_number> <HIGH|LOW> [port]"
    echo "Example: $0 8 HIGH /dev/ttyACM0"
    exit 1
fi

PIN=$1
STATE=$(echo "$2" | tr '[:lower:]' '[:upper:]')
# Default to /dev/ttyACM0 if a third argument isn't provided
PORT=${3:-"/dev/ttyACM0"} 

# Convert HIGH/LOW to 1/0
if [ "$STATE" = "HIGH" ]; then
    VALUE=1
elif [ "$STATE" = "LOW" ]; then
    VALUE=0
else
    echo "Error: State must be HIGH or LOW" >&2
    exit 1
fi

# Check if the device port exists and is accessible
if [ ! -e "$PORT" ]; then
    echo "Error: Serial port $PORT not found." >&2
    exit 1
fi

# 1. Configure the serial port using stty
# Set baud rate to 115200, enable raw mode, and disable local echo
stty -F "$PORT" 115200 raw -echo -echoe -echok -echoctl -echoke

# 2. Send Ctrl+C (\x03) to break out of any running main.py script
printf '\x03' > "$PORT"
sleep 0.1

# 3. Send a carriage return/newline to clear the REPL prompt line
printf '\r\n' > "$PORT"
sleep 0.1

# 4. Construct and send the MicroPython statement
CMD="from machine import Pin; Pin($PIN, Pin.OUT).value($VALUE)\r\n"
printf "$CMD" > "$PORT"

echo "DONE"

