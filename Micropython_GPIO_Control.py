#!/usr/bin/env python3

import argparse
import serial
import time
import sys

def main():
    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Set an ESP32-C3 GPIO pin via MicroPython REPL.")
    parser.add_argument("pin", type=int, help="The GPIO pin number to control (e.g., 8)")
    parser.add_argument("state", choices=["LOW", "HIGH"], type=str.upper, help="The state to set: LOW or HIGH")
    # Note: Defaulting to /dev/ttyACM0 as it's the standard Linux naming, but you can override it
    parser.add_argument("--port", type=str, default="/dev/ttyACM0", help="Serial port (default: /dev/ttyACM0)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")

    args = parser.parse_args()

    # Map HIGH/LOW to 1/0 for MicroPython
    value = 1 if args.state == "HIGH" else 0
    
    # We combine the import and execution into a single line to avoid REPL auto-indentation quirks
    cmd = f"from machine import Pin; Pin({args.pin}, Pin.OUT).value({value})\r\n"

    try:
        # Open the serial port
        ser = serial.Serial(args.port, args.baud, timeout=1)
        
        # Send Ctrl+C (\x03) to interrupt any currently running main.py loop
        ser.write(b'\x03')
        time.sleep(0.1)
        
        # Send an empty line to clear the prompt
        ser.write(b'\r\n')
        time.sleep(0.1)

        # Send the MicroPython command
        ser.write(cmd.encode('utf-8'))
        time.sleep(0.1) # Brief pause to allow execution

        # Read back the REPL output to clear the serial buffer
        ser.read_all()

        print(f"Success: GPIO {args.pin} set to {args.state} via {args.port}")
        ser.close()

    except serial.SerialException as e:
        print(f"Serial connection error: {e}", file=sys.stderr)
        print("Tip: Ensure you have read/write permissions for the port (e.g., dialout group on Linux).", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
