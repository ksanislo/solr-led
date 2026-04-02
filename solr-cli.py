import usb.core
import usb.util
import time
import argparse
import colorsys
import sys

VID = 0x044f
PIDS = [0x0422, 0x042a]  # 0422 = right, 042a = left
INTERFACE = 1
ENDPOINT_OUT = 0x02
ENDPOINT_IN = 0x82

FACTORY_COLORS = {
    0x00: bytes([0x1B, 0xCA, 0xFF]),  # Thumbstick: sky blue
}
FACTORY_DEFAULT = bytes([0x50, 0xFF, 0xFF])  # All other zones: bright cyan

LED_IDS = {
    0x00: "Thumbstick LED",
    0x01: "TM Logo Bottom",
    0x02: "TM Logo Right",
    0x03: "TM Logo Left",
    0x04: "Upper Circle",
    0x05: "Upper Right Circle",
    0x06: "Right Middle Circle",
    0x07: "Button 17",
    0x08: "Button 16",
    0x09: "Button 18",
    0x0A: "Button 19",
    0x0B: "Bottom Right Circle",
    0x0C: "Bottom Circle",
    0x0D: "Bottom Left Circle",
    0x0E: "Left Center Circle",
    0x0F: "Upper Left Circle",
    0x10: "Button 6",
    0x11: "Button 5",
    0x12: "Button 7",
    0x13: "Button 8",
}

# Button to LED mapping (including thumb = 0x00)
BUTTON_TO_LED = {
    0: 0x00,    # thumb
    5: 0x11,
    6: 0x10,
    7: 0x12,
    8: 0x13,
    16: 0x08,
    17: 0x07,
    18: 0x09,
    19: 0x0A,
}

# Groups of LEDs by name
GROUPS = {
    "tm_logo": [0x01, 0x02, 0x03],
    "upper_circles": [0x04, 0x05, 0x06, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F],
    "left_buttons": [BUTTON_TO_LED[b] for b in [5, 6, 7, 8]],
    "right_buttons": [BUTTON_TO_LED[b] for b in [17, 16, 19, 18]],
}

def send_led_packet(dev, led_colors, persistent=False):
    persist_flag = 0x80 if persistent else 0x00
    thumbstick_colors = {k: v for k, v in led_colors.items() if k == 0x00}
    other_colors = {k: v for k, v in led_colors.items() if k != 0x00}

    for led_id, color in thumbstick_colors.items():
        packet = bytes([0x01, 0x88, persist_flag | 0x01, 0xFF]) + bytes([led_id]) + color
        dev.write(ENDPOINT_OUT, packet, timeout=1000)
        time.sleep(0.01)

    keys = list(other_colors.keys())
    for i in range(0, len(keys), 2):
        batch = {k: other_colors[k] for k in keys[i:i+2]}
        packet = bytes([0x01, 0x08, persist_flag | len(batch), 0xFF])
        for led_id, color in batch.items():
            packet += bytes([led_id]) + color
        dev.write(ENDPOINT_OUT, packet, timeout=1000)
        time.sleep(0.01)

def read_led_colors(dev):
    """Read EEPROM-stored LED colors from the device."""
    colors = {}
    for report_type in [0x0002, 0x8002]:  # base zones, then grip zones
        start = 0
        while True:
            pkt = bytearray(64)
            pkt[0] = report_type & 0xFF
            pkt[1] = (report_type >> 8) & 0xFF
            pkt[2] = start
            dev.write(ENDPOINT_OUT, bytes(pkt), timeout=1000)
            time.sleep(0.02)
            try:
                resp = bytes(dev.read(ENDPOINT_IN, 64, timeout=1000))
            except usb.core.USBTimeoutError:
                break
            if (resp[0] | resp[1] << 8) != report_type:
                break
            n = resp[2] & 0x0F
            if n == 0:
                break
            last = start
            for i in range(n):
                off = 4 + i * 4
                zid, r, g, b = resp[off], resp[off+1], resp[off+2], resp[off+3]
                colors[zid] = (r, g, b)
                last = zid
            start = last + 1
            if n < 14 or start > 0x20:
                break
    return colors

def hex_to_rgb(hex_str):
    if len(hex_str) != 6:
        raise ValueError("Hex color must be 6 characters (e.g. 'FF0000')")
    return bytes.fromhex(hex_str)

def frange(start, stop, step):
    while start <= stop if step > 0 else start >= stop:
        yield start
        start += step

def breathing_effect(dev, leds, base_rgb):
    try:
        while True:
            # Fade up
            for v in frange(0.1, 1.0, 0.05):
                scaled = bytes([int(c * v) for c in base_rgb])
                led_colors = {led: scaled for led in leds}
                send_led_packet(dev, led_colors)
                time.sleep(0.05)
            # Fade down
            for v in frange(1.0, 0.1, -0.05):
                scaled = bytes([int(c * v) for c in base_rgb])
                led_colors = {led: scaled for led in leds}
                send_led_packet(dev, led_colors)
                time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nBreathing effect stopped by user.")

def rainbow_breathing_effect(dev, leds):
    try:
        hue = 0.0
        while True:
            for v in list(frange(0.1, 1.0, 0.05)) + list(frange(1.0, 0.1, -0.05)):
                r, g, b = colorsys.hsv_to_rgb(hue, 1.0, v)
                scaled = bytes([int(r * 255), int(g * 255), int(b * 255)])
                led_colors = {led: scaled for led in leds}
                send_led_packet(dev, led_colors)
                time.sleep(0.05)
                hue += 0.01
                if hue > 1.0:
                    hue = 0.0
    except KeyboardInterrupt:
        print("\nRainbow breathing stopped by user.")

def find_devices():
    devices = {}
    for pid in PIDS:
        dev = usb.core.find(idVendor=VID, idProduct=pid)
        if dev is not None:
            side = "right" if pid == 0x0422 else "left"
            devices[side] = dev
    return devices

def print_list():
    print("Available devices:")
    print("  left  - PID 042A")
    print("  right - PID 0422\n")
    print("Available groups:")
    for g in GROUPS:
        print(f"  {g} - LEDs: {', '.join(f'0x{led:02X}' for led in GROUPS[g])}")
    print("\nAvailable buttons:")
    for btn, led in sorted(BUTTON_TO_LED.items()):
        print(f"  Button {btn} -> LED 0x{led:02X}")
    print("\nUse --device with left or right, and specify either --group or --buttons with colors.")

def main():
    parser = argparse.ArgumentParser(description="Sol-R Flightstick LED controller CLI")
    parser.add_argument('--device', choices=['left', 'right'], help='Device to configure')
    group_mode = parser.add_mutually_exclusive_group()
    group_mode.add_argument('--group', choices=GROUPS.keys(), help='Group of LEDs to set')
    group_mode.add_argument('--buttons', type=str, help='Comma-separated list of button numbers to set (e.g. 5,6,7)')
    parser.add_argument('--list', action='store_true', help='List devices, groups, and buttons')
    parser.add_argument('--read', action='store_true', help='Read and display current EEPROM-stored LED colors')
    parser.add_argument('--reset', action='store_true', help='Reset all LEDs to factory default colors (persistent)')
    parser.add_argument('--breathing', action='store_true', help='Make LEDs breathe (pulse) with fixed color')
    parser.add_argument('--rainbow', action='store_true', help='Make LEDs breathe with rainbow colors')
    parser.add_argument('--persistent', action='store_true', help='Save color to EEPROM (default: volatile)')
    parser.add_argument('color', nargs='?', help='Color in RRGGBB hex (required unless --rainbow or --read)')

    args = parser.parse_args()

    if args.list:
        print_list()
        return

    if args.device is None:
        print("Error: --device is required (use --list to see devices).")
        return

    if not args.read and not args.reset and not args.group and not args.buttons:
        print("Error: Either --group, --buttons, --read, or --reset must be specified (use --list to see options).")
        return

    if args.breathing and args.rainbow:
        print("Error: --breathing and --rainbow cannot be used together.")
        return

    if not args.read and not args.reset and (args.breathing or (not args.rainbow)) and not args.color:
        print("Error: Color argument is required (use RRGGBB hex).")
        return

    devices = find_devices()
    if args.device not in devices:
        print(f"Device '{args.device}' not found.")
        return

    dev = devices[args.device]

    if dev.is_kernel_driver_active(INTERFACE):
        try:
            dev.detach_kernel_driver(INTERFACE)
        except usb.core.USBError as e:
            print(f"Could not detach kernel driver: {e}")
            return

    usb.util.claim_interface(dev, INTERFACE)

    # Determine LEDs to set (not needed for --read or --reset)
    leds_to_set = []
    if args.group:
        leds_to_set = GROUPS[args.group]
    elif args.buttons:
        try:
            buttons = [int(b.strip()) for b in args.buttons.split(',')]
        except ValueError:
            print("Invalid button numbers in --buttons argument.")
            return
        for b in buttons:
            if b not in BUTTON_TO_LED:
                print(f"Button {b} is not known.")
                return
            leds_to_set.append(BUTTON_TO_LED[b])

    try:
        # Drain any pending data on IN endpoint
        try:
            while True:
                dev.read(ENDPOINT_IN, 64, timeout=100)
        except usb.core.USBTimeoutError:
            pass

        if args.read:
            colors = read_led_colors(dev)
            for zid in sorted(colors.keys()):
                r, g, b = colors[zid]
                name = LED_IDS.get(zid, f"Zone 0x{zid:02X}")
                print(f"  0x{zid:02X}  {name:<24s}  #{r:02X}{g:02X}{b:02X}")
            return

        if args.reset:
            led_colors = {zid: FACTORY_COLORS.get(zid, FACTORY_DEFAULT) for zid in LED_IDS}
            send_led_packet(dev, led_colors, persistent=True)
            print("All LEDs reset to factory defaults and saved to EEPROM.")
            return

        if args.rainbow:
            rainbow_breathing_effect(dev, leds_to_set)
        elif args.breathing:
            base_rgb = hex_to_rgb(args.color)
            breathing_effect(dev, leds_to_set, base_rgb)
        else:
            color = hex_to_rgb(args.color)
            led_colors = {led: color for led in leds_to_set}
            send_led_packet(dev, led_colors, persistent=args.persistent)
            if args.persistent:
                print("LED colors saved to EEPROM.")
            else:
                print("LED colors updated.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        usb.util.release_interface(dev, INTERFACE)
        try:
            dev.attach_kernel_driver(INTERFACE)
        except usb.core.USBError:
            pass

if __name__ == "__main__":
    main()
