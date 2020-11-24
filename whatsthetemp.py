#!/usr/local/bin/python3
# -*- coding: utf-8 -*-
#Simple Python Script to query a BME280 and return the temp/humidity every 10 mins


from datetime import datetime
import smbus2
import bme280
import time

port = 1
address = 0x77
bus = smbus2.SMBus(port)

calibration_params = bme280.load_calibration_params(bus, address)
now = datetime.now()

# the sample method will take a single reading and return a
# compensated_reading object


while True:
    data = bme280.sample(bus, address, calibration_params)      
    #print(data.timestamp)
    current_time = now.strftime("%H:%M:%S")
    print("Hello, it's currently", current_time)
    print("The current temperature is %s C, the pressure is %s hPa, and the humidity is %s" % (round(data.temperature, 2), round(data.pressure, 2),  round(data.humidity, 2)))
    time.sleep(1000)