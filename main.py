"""
PyCom LoRa : Pay your coffee by NFC tags.
"""
import binascii
import socket
import time

import CBOR as cbor
import pycom
from machine import Pin, PWM
from MFRC630 import MFRC630
from network import LoRa
from pyscan import Pyscan


lora = LoRa(mode=LoRa.LORAWAN)

print("devEUI {}".format(binascii.hexlify(lora.mac())))


def hexlify(s):
    return binascii.unhexlify(s.replace(" ", ""))


app_eui = hexlify("00 00 00 00 00 00 00 00")
app_key = hexlify("11 22 33 44 55 66 77 88 11 22 33 44 55 66 77 88")

lora.join(activation=LoRa.OTAA, auth=(app_eui, app_key), timeout=0)
pycom.heartbeat(False)

even = True
while not lora.has_joined():
    time.sleep(2.5)
    if even:
        pycom.rgbled(0x111111)
    else:
        pycom.rgbled(0x000001)
    even = not even
    print("Not yet joined...")

s = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
s.setsockopt(socket.SOL_LORA, socket.SO_DR, 5)
s.setsockopt(socket.SOL_LORA, socket.SO_CONFIRMED, False)
s.settimeout(10)


def purgeLNSQueue():
    purgeCode = cbor.dumps([-2])
    pycom.rgbled(0x0000001)
    print("purge LNS buffer")
    s.setblocking(True)
    s.settimeout(10)

    try:
        s.send(purgeCode.value())
    except:
        print("error in sending")

    try:
        data = s.recv(64)

        print(data)
    except:
        print("timeout in receive")

    s.setblocking(False)

# Empty the queue
purgeLNSQueue()


# Ping the LNS
resetCode = cbor.dumps([-1])
transOK = False
backoff = 0x01
while not transOK:
    s.setblocking(True)
    s.settimeout(10)
    print("Reseting proxy")
    pycom.rgbled(0x330022)
    try:
        s.send(resetCode.value())
    except:
        print("Error in sending")

    try:
        data = s.recv(64)
        r = cbor.loads(data)
        print(r)
        transOK = r[0] == -1
    except:
        print("Timeout in receive")

    pycom.rgbled(0x330011)

    time.sleep(backoff)  # double sending interval
    backoff *= 2
    s.setblocking(False)


# This is the default key for an unencrypted MiFare card
CARDkey = [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
DECODE_CARD = False

py = Pyscan()
nfc = MFRC630(py)

direction = 1
RGB_BRIGHTNESS = 0x08
counter = 0

# Bip
def buz(frequency=440):
    buz = Pin("P10")  # Buzzer
    tim = PWM(0, frequency=frequency)
    ch = tim.channel(2, duty_cycle=0.5, pin=buz)
    time.sleep(1)
    tim = PWM(0, frequency=0)
    ch.duty_cycle(0)

buz(340)  # Reader ready

# Initialise the MFRC630 with some settings
nfc.mfrc630_cmd_init()

while True:
    if RGB_BRIGHTNESS > 200:
        direction = -10
    if RGB_BRIGHTNESS < 20:
        direction = 10

    RGB_BRIGHTNESS += direction

    RGB_RED = RGB_BRIGHTNESS << 16
    RGB_GREEN = RGB_BRIGHTNESS << 8
    RGB_BLUE = RGB_BRIGHTNESS

    # Send REQA for ISO14443A card type
    atqa = nfc.mfrc630_iso14443a_WUPA_REQA(nfc.MFRC630_ISO14443_CMD_REQA)
    if atqa != 0:
        # A card has been detected, read UID
        uid = bytearray(10)
        uid_len = nfc.mfrc630_iso14443a_select(uid)
        if uid_len > 0:
            # A valid UID has been detected, print details
            counter += 1
            pycom.rgbled(RGB_GREEN)
            buz(440)  # Tag read
            print(
                "%d\tUID [%d]: %s" % (counter, uid_len, nfc.format_block(uid, uid_len))
            )
            d = cbor.dumps(uid[0:uid_len])
            c = cbor.dumps([counter, d])
            print(c)

            cptRetrans = 0

            while cptRetrans < 5:
                s.setblocking(True)
                s.settimeout(10)
                try:
                    s.send(c.value())
                except:
                    print("Error in sending transaction")

                pycom.rgbled(0x110011)

                buz(540)  # Message sent
                try:
                    data = s.recv(64)

                    print(data)
                    r = cbor.loads(data)
                    print(r)

                    if r[0] == counter:
                        buz(640)  # Response OK
                        break
                except:
                    print("timeout in receive")
                    pycom.rgbled(0x000001)

                s.setblocking(False)
                time.sleep(5)
                cptRetrans += 1
    else:
        pycom.rgbled(RGB_BLUE)
    # We could go into power saving mode here... to be investigated
    nfc.mfrc630_cmd_reset()
    time.sleep(1)
    # Re-Initialise the MFRC630 with settings as these got wiped during reset
    nfc.mfrc630_cmd_init()

    if time.time() % 3600 == 0:  # Once per hour we purge the queue
        purgeLNSQueue()
