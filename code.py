# Temp/Humidity and Pollution Sensor
# Daniel Cuthbert
# 2021 v1.0

import board
import busio
import time
from adafruit_bme280 import basic as adafruit_bme280
from digitalio import DigitalInOut
from adafruit_esp32spi import adafruit_esp32spi, adafruit_esp32spi_wifimanager
from adafruit_io.adafruit_io import IO_HTTP
from simpleio import map_range
from adafruit_pm25.uart import PM25_UART
from analogio import AnalogIn


# We don't need to hammer Adafruit IO, so can get away with every 20 minutes
PUBLISH_INTERVAL = 20


### Wifi stuffs ###
# We keep the secrets in secrets.py
try:
    from secrets import secrets
except ImportError:
    print("Oh dears, the setec astronomy file isn't there.")
    raise

# This gets the AirLift FeatherWing up and running. We will be using SPI and UART
esp32_cs = DigitalInOut(board.D13)
esp32_reset = DigitalInOut(board.D12)
esp32_ready = DigitalInOut(board.D11)
spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)
wifi = adafruit_esp32spi_wifimanager.ESPSPI_WiFiManager(esp, secrets,)

# Let's check the battery level
# if on lipo, the batteries are as follows:
# 4.2V max
# 3.7V healthy
# 3.2V trouble ahead

vbat_voltage = AnalogIn(board.VOLTAGE_MONITOR)
def get_voltage(pin):
    return (pin.value * 3.3) / 65536 * 2
battery_voltage = get_voltage(vbat_voltage)
print("VBat voltage: {:.2f}".format(battery_voltage))

# We are using the PM2.5 sensor over UART, so lets get that ready to sniff
reset_pin = None
uart = busio.UART(board.TX, board.RX, baudrate=9600)
pm25 = PM25_UART(uart, reset_pin)

# Create i2c object for the BME280 temp/humidity sensor
i2c = board.I2C()
bme_sensor = adafruit_bme280.Adafruit_BME280_I2C(i2c)

### Sensor Functions ###
def calculate_aqi(pm_sensor_reading):
    """Returns a calculated air quality index (AQI)
    and category as a tuple.
    NOTE: The AQI returned by this function should ideally be measured
    using the 24-hour concentration average. Calculating a AQI without
    averaging will result in higher AQI values than expected.
    :param float pm_sensor_reading: Particulate matter sensor value.

    """
    # Check sensor reading using EPA breakpoint (Clow-Chigh)
    if 0.0 <= pm_sensor_reading <= 12.0:
        # AQI calculation using EPA breakpoints (Ilow-IHigh)
        aqi_val = map_range(int(pm_sensor_reading), 0, 12, 0, 50)
        aqi_cat = "Good"
    elif 12.1 <= pm_sensor_reading <= 35.4:
        aqi_val = map_range(int(pm_sensor_reading), 12, 35, 51, 100)
        aqi_cat = "Moderate"
    elif 35.5 <= pm_sensor_reading <= 55.4:
        aqi_val = map_range(int(pm_sensor_reading), 36, 55, 101, 150)
        aqi_cat = "Unhealthy for some "
    elif 55.5 <= pm_sensor_reading <= 150.4:
        aqi_val = map_range(int(pm_sensor_reading), 56, 150, 151, 200)
        aqi_cat = "Err, unhealthy"
    elif 150.5 <= pm_sensor_reading <= 250.4:
        aqi_val = map_range(int(pm_sensor_reading), 151, 250, 201, 300)
        aqi_cat = "This isn't good"
    elif 250.5 <= pm_sensor_reading <= 350.4:
        aqi_val = map_range(int(pm_sensor_reading), 251, 350, 301, 400)
        aqi_cat = "Run Daniel Run"
    elif 350.5 <= pm_sensor_reading <= 500.4:
        aqi_val = map_range(int(pm_sensor_reading), 351, 500, 401, 500)
        aqi_cat = "Need a mask"
    else:
        print("Invalid PM2.5 concentration")
        aqi_val = -1
        aqi_cat = None
    return aqi_val, aqi_cat


def sample_aq_sensor():
    """Samples PM2.5 sensor
    over a 2.3 second sample rate.
    """
    aq_reading = 0
    aq_samples = []
    time_start = time.monotonic()
    while time.monotonic() - time_start <= 2.3:
        try:
            aqdata = pm25.read()
            aq_samples.append(aqdata["pm25 env"])
        except RuntimeError:
            print("Unable to read from sensor, retrying...")
            continue
        # pm sensor output rate of 1s
        time.sleep(1)
    # average sample reading / # samples
    for sample in range(len(aq_samples)):
        aq_reading += aq_samples[sample]
    aq_reading = aq_reading / len(aq_samples)
    aq_samples.clear()
    return aq_reading


def read_bme():

    humid = bme_sensor.humidity
    temp = bme_sensor.temperature
    return temp, humid

# Now we have the data from the sensors, we need to do something with it.
# We are using the brilliant Adafruit.io site and client

io = IO_HTTP(secrets["aio_username"], secrets["aio_key"], wifi)

# Once you've created your feeds, you need to list the names here
feed_aqi = io.get_feed("air-quality-sensor.aqi")
feed_aqi_category = io.get_feed("air-quality-sensor.category")
feed_humidity = io.get_feed("air-quality-sensor.humidity")
feed_temperature = io.get_feed("air-quality-sensor.temperature")
feed_battery = io.get_feed("air-quality-sensor.battery")

# Set up location metadata from secrets.py file
location_metadata = {
    "lat": secrets["latitude"],
    "lon": secrets["longitude"],
    "ele": secrets["elevation"],
}

elapsed_minutes = 0
prv_mins = 0

while True:
    try:
        print("Fetching time...")
        cur_time = io.receive_time()
        print("Time fetched OK!")
        # Hourly reset
        if cur_time.tm_min == 0:
            prv_mins = 0
    except (ValueError, RuntimeError) as e:
        print("Failed to fetch time, retrying\n", e)
        wifi.reset()
        wifi.connect()
        continue

    if cur_time.tm_min >= prv_mins:
        print("%d min elapsed.." % elapsed_minutes)
        prv_mins = cur_time.tm_min
        elapsed_minutes += 1

    if elapsed_minutes >= PUBLISH_INTERVAL:
        print("Reading the PM25 sensor ...")
        aqi_reading = sample_aq_sensor()
        aqi, aqi_category = calculate_aqi(aqi_reading)
        print("AQI: %d" % aqi)
        print("Category: %s" % aqi_category)

        # temp and humidity
        print("Reading the environmental sensor...")
        temperature, humidity = read_bme()
        print("Temperature: %0.1f C" % temperature)
        print("Humidity: %0.1f %%" % humidity)

        # Once we have the values, push them up
        # we are adding the geolocaton to the aqi feed so add it there as a seperate box
        print("Publishing to Adafruit IO...")
        try:
            io.send_data(feed_aqi["key"], str(aqi), location_metadata)
            io.send_data(feed_aqi_category["key"], aqi_category)
            io.send_data(feed_temperature["key"], str(temperature))
            io.send_data(feed_humidity["key"], str(humidity))
            io.send_data(feed_battery["key"], str(battery_voltage))
            print("Much success, published!")
        except (ValueError, RuntimeError) as e:
            print("Failed to send data to IO, retrying\n", e)
            wifi.reset()
            wifi.connect()
            continue
        # Reset timer
        elapsed_minutes = 0
    time.sleep(30)