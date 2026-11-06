"""MicroPython GPIO input mapping and software debounce."""
from machine import Pin
from time import ticks_ms, ticks_diff
from config import SENSOR_PINS, ACTIVE_LOW, DEBOUNCE_MS

KEYS = ('P1','P2','P3','P4','A','B','S')

class Sensors:
    def __init__(self):
        self.pins = {}
        for name in KEYS:
            number = SENSOR_PINS.get(name)
            if number is None:
                raise RuntimeError('尚未確認感測器腳位：' + name)
            self.pins[name] = Pin(number, Pin.IN, Pin.PULL_UP)
        self.stable = {key:self._read(key) for key in KEYS}
        self.raw = dict(self.stable)
        self.changed_at = {key:ticks_ms() for key in KEYS}

    def _read(self,name):
        raw = self.pins[name].value()
        return (raw == 0) if ACTIVE_LOW else (raw == 1)

    def poll(self):
        changed=[]
        now=ticks_ms()
        for name in KEYS:
            value=self._read(name)
            if value != self.raw[name]:
                self.raw[name]=value
                self.changed_at[name]=now
            if value != self.stable[name] and ticks_diff(now,self.changed_at[name])>=DEBOUNCE_MS:
                self.stable[name]=value
                changed.append((name,value))
        return changed

    def blocked(self):
        # Single photoelectric S point is not sufficient for vehicle-grade safety.
        return self.stable['S'] or self.stable['A'] or self.stable['B']
