"""Safety-aware servo demonstration for a tabletop model only."""
from machine import Pin, PWM
from time import sleep_ms
from config import SERVO_PIN, SERVO_CLOSED_ANGLE, SERVO_OPEN_ANGLE

class Gate:
    def __init__(self, sensors):
        if SERVO_PIN is None:
            raise RuntimeError('尚未確認伺服馬達 GPIO，拒絕啟動')
        self.sensors=sensors
        self.pwm=PWM(Pin(SERVO_PIN), freq=50)
        self.angle=SERVO_CLOSED_ANGLE
        self.state='UNKNOWN'  # No limit switch: position is NOT physically verified.
        self._apply(self.angle)
        sleep_ms(250)
        self.state='CLOSED'  # Estimated only: servo has no feedback.

    def _apply(self,angle):
        pulse_us=500+int(angle*2000/180)
        self.pwm.duty_u16(int(pulse_us*65535/20000))

    def _move(self,target,closing=False):
        step=1 if target>self.angle else -1
        for value in range(self.angle,target+step,step):
            # Never continue closing while any lane/safety point is occupied.
            if closing:
                self.sensors.poll()  # Re-read hardware during movement, not only before starting.
                if self.sensors.blocked():
                    return False
            self._apply(value)
            self.angle=value
            sleep_ms(18)
        return True

    def open(self):
        self.state='OPENING'
        self._move(SERVO_OPEN_ANGLE)
        self.state='OPEN'
        return True

    def close(self):
        if self.sensors.blocked():
            return False
        self.state='CLOSING'
        if not self._move(SERVO_CLOSED_ANGLE,closing=True):
            self.open()  # obstacle detected while moving: reopen
            return False
        self.state='CLOSED'
        return True

    def safety_tick(self):
        # This check is performed locally even when Wi-Fi/Render is unreachable.
        if self.state=='CLOSING' and self.sensors.blocked():
            self.open()
