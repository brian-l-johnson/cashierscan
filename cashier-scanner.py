#!/usr/bin/python3
import evdev
import asyncio
import json
from dotenv import load_dotenv
import os
import sqlite3
import requests
from json import JSONEncoder
import datetime

q = asyncio.Queue()
scanner_names = ["BF SCAN SCAN KEYBOARD"]
lock = asyncio.Lock()

async def handle_scan(device, idx):
    #setup vars 
    x = '' 
    caps = False
    station = ""
    #check if we have a mapping for device to cashier station
    res = cursor.execute("SELECT station FROM scanners WHERE path=?",(device.path,))
    stat = res.fetchone()
    if stat is not None:
        station = stat[0]
        print(f"found existing station mapping in database: {stat[0]}")

    scancodes = { 
        # Scancode: ASCIICode 
        0: None, 1: u'ESC', 2: u'1', 3: u'2', 4: u'3', 5: u'4', 6: u'5', 7: u'6', 8: u'7', 9: u'8', 
        10: u'9', 11: u'0', 12: u'-', 13: u'=', 14: u'BKSP', 15: u'TAB', 16: u'q', 17: u'w', 18: u'e', 19: u'r', 
        20: u't', 21: u'y', 22: u'u', 23: u'i', 24: u'o', 25: u'p', 26: u'[', 27: u']', 28: u'CRLF', 29: u'LCTRL', 
        30: u'a', 31: u's', 32: u'd', 33: u'f', 34: u'g', 35: u'h', 36: u'j', 37: u'k', 38: u'l', 39: u';', 
        40: u'\'', 41: u'`', 42: u'LSHFT', 43: u'\\', 44: u'z', 45: u'x', 46: u'c', 47: u'v', 48: u'b', 49: u'n', 
        50: u'm', 51: u',', 52: u'.', 53: u'/', 54: u'RSHFT', 56: u'LALT', 57: u' ', 71: u'7', 72: u'8', 73: u'9',
        75: u'4', 76: u'5', 77: u'6', 79: u'1', 80: u'2', 81: u'3', 82: u'0', 100: u'RALT' 
    } 

    capscodes = { 
        0: None, 1: u'ESC', 2: u'!', 3: u'@', 4: u'#', 5: u'$', 6: u'%', 7: u'^', 8: u'&', 9: u'*', 
        10: u'(', 11: u')', 12: u'_', 13: u'+', 14: u'BKSP', 15: u'TAB', 16: u'Q', 17: u'W', 18: u'E', 19: u'R', 
        20: u'T', 21: u'Y', 22: u'U', 23: u'I', 24: u'O', 25: u'P', 26: u'{', 27: u'}', 28: u'CRLF', 29: u'LCTRL', 
        30: u'A', 31: u'S', 32: u'D', 33: u'F', 34: u'G', 35: u'H', 36: u'J', 37: u'K', 38: u'L', 39: u':', 
        40: u'"', 41: u'~', 42: u'LSHFT', 43: u'|', 44: u'Z', 45: u'X', 46: u'C', 47: u'V', 48: u'B', 49: u'N', 
        50: u'M', 51: u'<', 52: u'>', 53: u'?', 54: u'RSHFT', 56: u'LALT', 57: u' ', 71: u'7', 72: u'8', 73: u'9',
        75: u'4', 76: u'5', 77: u'6', 79: u'1', 80: u'2', 81: u'3', 82: u'0', 100: u'RALT' 
    }

    pending_string = ''

    async for event in device.async_read_loop():
        #print(device.path, evdev.categorize(event), sep=': ')
        if event.type == evdev.ecodes.EV_KEY:
            data = evdev.categorize(event) # Save the event temporarily to introspect it 
            #print(f"got keystroke: {data.scancode} -> {scancodes.get(data.scancode)}")
            if data.scancode == 42: 
                if data.keystate == 1: 
                    caps = True 
                if data.keystate == 0: 
                    caps = False 

            if data.keystate == 1: # Down events only 
                if caps: 
                    key_lookup = capscodes.get(data.scancode) or None
                else: 
                    key_lookup = scancodes.get(data.scancode) or None
            
                if (data.scancode == 28):
                    print(pending_string)
                    try:
                        data = json.loads(pending_string)
                        if "control" in data:
                            print("in control flow")
                            if data['control'] == "setup-station":
                                print(f"set station for {idx} to {data['station']}")
                                station = data['station']
                                async with lock:
                                    cursor.execute("INSERT INTO scanners(path, station) VALUES(?, ?) ON CONFLICT(path) DO UPDATE SET station=excluded.station", (device.path, station) )
                                    connection.commit()
                        else:
                            await q.put((station, data))
                    except json.JSONDecodeError as err:
                        print("unable to parse JSON")
                        print(err)
                    pending_string = ''
                elif (data.scancode != 42) and (key_lookup != None): 
                    pending_string += key_lookup

async def order_handler():
    while True:
        event = await q.get()
        print(event)
        data = event[1]
        if "txn" in data:
            print(f"order number {data['txn']}")
            reqobj = {
                "ordernum": data['txn'],
                "ordertime": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            try:
                resp = requests.patch(os.environ['API_PATH']+"/cashiers/"+event[0], json=reqobj)
            except requests.HTTPError as http_err:
                print(f"HTTP error: {http_err}")
            except Exception as err:
                print(f"some other exception")

        q.task_done()

async def main():
    global cursor, connection
    load_dotenv()

    connection = sqlite3.connect(os.environ['DB_PATH'])
    cursor = connection.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS scanners (path TEXT PRIMARY KEY, station TEXT)")
    connection.commit()


    #devices = [evdev.InputDevice('/dev/input/event0')]
    #devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    #devices = [evdev.InputDevice(path) for path in evdev.list_devices(input_device_dir="/dev/input/by-path")]
    devices = []
    for filename in os.listdir("/dev/input/by-path"):
        try:
            devices.append(evdev.InputDevice("/dev/input/by-path/"+filename))
        except Exception as err:
            print(err)
    print(devices)
    background_tasks = []

    for idx, device in enumerate(devices):
       if device.name in scanner_names:
           print(f"found scanner at index {idx}, {device.path}")
           device.grab() #grab for exclusive access
           task = handle_scan(device, idx)
           background_tasks.append(task)
    task = order_handler()
    background_tasks.append(task)
    await asyncio.gather(*background_tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        print("caught ctrl c")
        connection.close()

