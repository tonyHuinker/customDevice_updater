###############################################################
######## NOTES:                                        ########
########   @author: Aaron Paxson / Tony Huinker        ########
########   @date: 11/14/2016                           ########
########   @description:                               ########
########     Used to sync data from NETZ to Extrahop   ########
########     in order to get up-to-date stores and     ########
########     metadata from CSV                         ########
########   @EH_Firmware:  5.3.2                        ########
###############################################################

import logging
import re
import json
import sys
import csv
import ConfigParser
from Ehop import Ehop

###############################################################
######## Variables                                     ########
###############################################################

vars_file = "vars.cfg"
logLevel = logging.INFO   # Level of logging.  INFO, WARNING, ERROR, DEBUG, etc
logApp = 'NETZSync'

# Load Vars
config = ConfigParser.ConfigParser()
config.read(vars_file)
eh_host = config.get("DEFAULT","eh_host")          # Extrahop Host
csv_file = config.get("DEFAULT","datafile")        # CSV File to load
api_key = config.get("DEFAULT", "api_key")         # API Key for EH
logFileName = config.get("DEFAULT","logFileName")  # LogFile

###############################################################
######## Functions and Setup                           ########
###############################################################

logger = logging.getLogger(logApp)
logFile = logging.FileHandler(logFileName)
logCon = logging.StreamHandler(sys.stdout)
logFormat = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
logFile.setFormatter(logFormat)
logCon.setFormatter(logFormat)
logger.addHandler(logFile)
logger.addHandler(logCon)
logger.setLevel(logLevel)

eh = Ehop(host=eh_host,apikey=api_key)

def extract_csv_tags(headers):
    #Use this function to validate or create tag definitions in EH
    tags = []
    for header in headers:
        match = re.search('([\w\s]+)_[Tt]ag$',header)
        if match is not None:
            tags.append(match.group(1))
    return tags

def load_csv_records(filename):
    logger.debug("Loading records from CSV")
    f = open(filename)
    data = csv.DictReader(f)
    stores = {}
    for row in data:
        # It's not a good idea to load everything.  But, for now, let's just do it.
        #TODO: Load only fields needed
        stores.add(row[0])
    logger.debug("Loaded " + str(len(stores)) + " records from " + filename)
    return stores

def load_eh_records(extrahop):
    #load custom devices
    StoreCustomDevices = {}
    tempCustom =  json.loads(extrahop.api_request("GET", "customdevices"))
    for custom in tempCustom:
        if custom["description"] == "Store":
            StoreCustomDevices[custom["extrahop_id"]] = custom

    #load real devices
    StoreDevices = {}
    tempDevices = json.loads(extrahop.api_request("GET", "devices?limit=10000&search_type=type&value=custom"))
    for device in tempDevices:
        if device["extrahop_id"] in StoreCustomDevices:
            StoreDevices[device["extrahop_id"]] = device

    loaded_stores = {}
    logger.debug("Getting custom devices from Extrahop")

    print StoreDevices
    for key in StoreDevices:
        print StoreDevices[key]
        #Grab ID for later use
        deviceID = StoreDevices[key]["id"]
        customID = StoreCustomDevices[key]["id"]

        #Make unique ID
        storeID = StoreDevices[key]["extrahop_id"].strip("~-")

        #add
        loaded_stores[storeID] = StoreDevices[key]

        #grab criteria
        print id
        criteria = json.loads(extrahop.api_request("GET", "customdevices/"+str(customID)+"/criteria"))
        loaded_stores[storeID]["criteria"] = criteria

        #grab tags
        tags = json.loads(extrahop.api_request("GET", "devices/"+str(deviceID)+"/tags"))
        loaded_stores[storeID]["tags"] = tags

    logger.debug("Added " + str(len(loaded_stores)) + " filtered devices as stores from Extrahop")
    return loaded_stores

###############################################################
######## Main Script                                    #######
###############################################################
logger.info("Executing")

DOC = """
This script is mean to take a CSV that was merged by GPC personnel and identify
MAC (Move/Add/Changes) to the Extrahop.

Display Name:  {Mutable}
StoreID: {Unmutable.  2nd and 3rd octets of IP}
Tags:  {Mutable.  Always Changing}
IPs:  {Mutable, but won't change, as this will conflict with StoreID (unmutable)
"""

# Get All Custom Devices Stores from ExtraHop
eh_stores = load_eh_records(eh)
# Load relevant CSV data into a Set of Dicts
#csv_stores = load_csv_records(csv_file)


# Load Extrahop device from CSV
for store in csv_stores:
    id = store['Unique_ID']
    # Access the store in EH from CSV
    eh_store = eh_stores['extrahop_id']
