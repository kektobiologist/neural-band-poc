"""Capture one probe run over USB; optionally reset the ESP32 first."""
import argparse
import time
from pathlib import Path

import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='/dev/cu.usbmodem2101')
    parser.add_argument('--seconds', type=float, default=65)
    parser.add_argument('--reset', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('--seconds must be positive')
    with args.output.open('x') as log, serial.Serial(args.port, 115200, timeout=.25) as port:
        if args.reset:
            from esptool.reset import HardReset
            # PySerial opens with DTR asserted; release GPIO0 before resetting
            # so a paused bootloader resumes the application instead of download mode.
            port.dtr = False
            HardReset(port, uses_usb=True)()
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            data = port.read(4096).decode(errors='replace')
            if data:
                print(data, end='', flush=True)
                log.write(data)
                log.flush()


if __name__ == '__main__':
    main()
