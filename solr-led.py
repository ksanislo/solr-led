import usb.core
import usb.util
import time
import readline

VID = 0x044f
PIDS = [0x0422, 0x042a]
INTERFACE = 1
ENDPOINT_OUT = 0x02
ENDPOINT_IN = 0x82

THUMBSTICK_ID = 0x80  # Virtual ID for grip thumbstick (actual zone 0x00 via 0x88 header)

FACTORY_COLORS = {
    THUMBSTICK_ID: bytes([0x1B, 0xCA, 0xFF]),  # Thumbstick: sky blue
}
FACTORY_DEFAULT = bytes([0x50, 0xFF, 0xFF])  # All other zones: bright cyan

LED_IDS = {
    0x00: "TM Logo Top Right",
    0x01: "TM Logo Top Left",
    0x02: "TM Logo Bottom Left",
    0x03: "TM Logo Bottom Right",
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
    THUMBSTICK_ID: "Thumbstick LED",
}

LED_GROUPS = {
    "tm_logo": [0x00, 0x01, 0x02, 0x03],
    "circle_group": [0x04, 0x05, 0x06, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F],
    "left_buttons": [0x11, 0x10, 0x12, 0x13],   # Buttons 5,6,7,8
    "right_buttons": [0x07, 0x08, 0x0A, 0x09]   # Buttons 17,16,19,18
}

def send_led_packet(dev, led_colors, persistent=False):
    persist_flag = 0x80 if persistent else 0x00

    # Thumbstick uses 0x88 header and actual zone 0x00 on the grip
    if THUMBSTICK_ID in led_colors:
        color = led_colors[THUMBSTICK_ID]
        packet = bytes([0x01, 0x88, persist_flag | 0x01, 0xFF, 0x00]) + color
        dev.write(ENDPOINT_OUT, packet, timeout=1000)
        time.sleep(0.01)

    # All other LEDs use 0x08 header on the base
    base_colors = {k: v for k, v in led_colors.items() if k != THUMBSTICK_ID}
    keys = list(base_colors.keys())
    for i in range(0, len(keys), 2):
        batch = {k: base_colors[k] for k in keys[i:i+2]}
        packet = bytes([0x01, 0x08, persist_flag | len(batch), 0xFF])
        for led_id, color in batch.items():
            packet += bytes([led_id]) + color
        dev.write(ENDPOINT_OUT, packet, timeout=1000)
        time.sleep(0.01)

def read_led_colors(dev):
    """Read EEPROM-stored LED colors from the device.
    Returns dict: {report_type: {zid: (r, g, b), ...}, ...}
    """
    results = {}
    for report_type in [0x0002, 0x8002]:  # base zones, then grip zones
        colors = {}
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
        results[report_type] = colors
    return results

def hex_to_rgb(hex_str):
    if len(hex_str) != 6:
        raise ValueError("Hex color must be 6 characters (e.g. 'ff0000')")
    return bytes.fromhex(hex_str)

def find_devices():
    devices = []
    for pid in PIDS:
        found = usb.core.find(find_all=True, idVendor=VID, idProduct=pid)
        for dev in found:
            devices.append((dev, pid))
    return devices

def select_device(devices):
    pid_labels = {
        0x0422: "Right Stick",
        0x042a: "Left Stick"
    }

    if len(devices) == 1:
        pid = devices[0][1]
        label = pid_labels.get(pid, f"Unknown (PID {pid:04X})")
        print(f"Found one device: {label}")
        return devices[0][0]

    print("Multiple devices found:")
    for i, (dev, pid) in enumerate(devices):
        label = pid_labels.get(pid, f"Unknown (PID {pid:04X})")
        print(f"  [{i}] {label}")

    while True:
        choice = input("Select device number: ").strip()
        if choice.isdigit() and 0 <= int(choice) < len(devices):
            return devices[int(choice)][0]
        print("Invalid choice.")

def main():
    devices = find_devices()
    if not devices:
        raise ValueError("No compatible devices found")

    dev = select_device(devices)

    if dev.is_kernel_driver_active(INTERFACE):
        dev.detach_kernel_driver(INTERFACE)
    usb.util.claim_interface(dev, INTERFACE)

    try:
        # Drain any pending data on IN endpoint
        try:
            while True:
                dev.read(ENDPOINT_IN, 64, timeout=100)
        except usb.core.USBTimeoutError:
            pass

        print("Available LEDs:")
        for lid, label in LED_IDS.items():
            print(f"  {lid:02X}: {label}")
        print("\nAvailable Groups:")
        for name, ids in LED_GROUPS.items():
            print(f"  {name}: {[f'{i:02X}' for i in ids]}")

        led_colors = {}

        while True:
            user_input = input("\nEnter LED ID (hex), group name, 'thumb', 'read', 'reset', or 'done': ").strip().lower()
            if user_input == "done":
                break

            if user_input == "read":
                print("\nReading EEPROM-stored colors...")
                results = read_led_colors(dev)
                report_labels = {0x0002: "Base (0x0002)", 0x8002: "Grip (0x8002)"}
                for report_type in [0x0002, 0x8002]:
                    colors = results.get(report_type, {})
                    label = report_labels[report_type]
                    print(f"\n  {label}:")
                    if not colors:
                        print(f"    (no zones returned)")
                    for zid in sorted(colors.keys()):
                        r, g, b = colors[zid]
                        if report_type == 0x8002 and zid == 0x00:
                            display_id = THUMBSTICK_ID
                        else:
                            display_id = zid
                        name = LED_IDS.get(display_id, f"Zone 0x{zid:02X}")
                        print(f"    {zid:02X}: {name:<24s} #{r:02X}{g:02X}{b:02X}")
                continue

            if user_input == "reset":
                led_colors = {zid: FACTORY_COLORS.get(zid, FACTORY_DEFAULT) for zid in LED_IDS}
                send_led_packet(dev, led_colors, persistent=True)
                print("All LEDs reset to factory defaults and saved to EEPROM.")
                return

            if user_input == "thumb":
                led_ids = [THUMBSTICK_ID]
            elif user_input in LED_GROUPS:
                led_ids = LED_GROUPS[user_input]
            elif all(c in "0123456789abcdef" for c in user_input) and len(user_input) <= 2:
                try:
                    led_id = int(user_input, 16)
                    if led_id not in LED_IDS:
                        print("Unknown LED ID.")
                        continue
                    led_ids = [led_id]
                except ValueError:
                    print("Invalid LED ID format.")
                    continue
            else:
                print("Unknown LED ID or group name.")
                continue

            color_input = input("Enter color (RRGGBB hex, e.g. FF0000 for red): ").strip().lower()
            try:
                color = hex_to_rgb(color_input)
                for lid in led_ids:
                    led_colors[lid] = color
                    print(f"Set LED {lid:02X} to #{color_input.upper()}")
            except ValueError as e:
                print(e)

        if not led_colors:
            print("No LEDs selected. Exiting.")
            return

        persist_input = input("\nSave to EEPROM (persistent)? [y/N]: ").strip().lower()
        persistent = persist_input in ("y", "yes")

        send_led_packet(dev, led_colors, persistent=persistent)
        if persistent:
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
