"""Copy to config.py AFTER choosing and checking the wiring. Do not use guessed pins."""
# All pins intentionally None until the wiring plan is verified.
SENSOR_PINS = {'P1': None, 'P2': None, 'P3': None, 'P4': None, 'A': None, 'B': None, 'S': None}
SERVO_PIN = None
LED_PINS = {}  # optional: {'red': 25, 'green': 26}, only after wiring is verified
ACTIVE_LOW = True        # FC-51 commonly LOW on obstacle; verify on actual modules
SERVO_CLOSED_ANGLE = 0   # verify mechanical limits first
SERVO_OPEN_ANGLE = 90
DEBOUNCE_MS = 70
HEARTBEAT_MS = 2000
