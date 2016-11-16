###############################################################
######## NOTES:                                        ########
########   @author: Aaron Paxson / Tony Huinker        ########
########   @date: 11/14/2016                           ########
########   @description:                               ########
########     Used to sync data from NETZ to Extrahop   ########
########     in order to get up-to-date stores and     ########
########     metadata from CSV                         ########
########   @EH_Firmware:  6.0.2                        ########
###############################################################

import logging
import re
import json
import sys
import csv
import ConfigParser
from Ehop import Ehop
from logging.handlers import TimedRotatingFileHandler

###############################################################
######## Variables                                     ########
###############################################################

vars_file = "vars.cfg"
logLevel = logging.DEBUG   # Level of logging.  INFO, WARNING, ERROR, DEBUG, etc
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
fileHandler = TimedRotatingFileHandler(logFileName,when='d',interval=1,backupCount=10)
#logFile = logging.FileHandler(logFileName)
logCon = logging.StreamHandler(sys.stdout)
logFormat = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
fileHandler.setFormatter(logFormat)
logCon.setFormatter(logFormat)
logger.addHandler(fileHandler)
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
    logger.debug("Found the following tags from netz file: " + str(tags))
    return tags

def load_csv_records(filename):
    logger.debug("Loading records from CSV")
    f = open(filename,'rU')
    data = csv.DictReader(f)
    all_tags = extract_csv_tags(data.fieldnames)
    #logger.debug("Found the following tags in file: " + str(all_tags))
    stores = {}
    for row in data:
        # It's not a good idea to load everything.  But, for now, let's just do it.
        #TODO: Load only fields needed
        # Grab store ID to key on
        storeID = row['Unique_ID']
        # Check for RPM data.  If so, DisplayName + _num
        displayName = "Store " + row["Store Number_tag"]
        if row["RPM Store Number"] != '':
            #RPM Store.  Append data
            displayName += "_" + row["RPM Store Number"]
        row["display_name"] = displayName
        # Build dict of tags, with key "tags"
        tmptags = {}
        for tag in all_tags:
            tmptags[tag] = tag + ": " + row[tag + "_tag"]
        row["tags"] = tmptags
        row["criteria"] = row["Juniper"].split("|")
        stores[storeID] = row
    logger.debug("Loaded " + str(len(stores)) + " records from " + filename)
    uniqueCounter = {}
    for key in stores:
        uniqueCounter[stores[key]['display_name']] = -1

    for key in stores:
        uniqueCounter[stores[key]['display_name']] = uniqueCounter[stores[key]['display_name']] + 1
        if uniqueCounter[stores[key]['display_name']] > 0:
            stores[key]['display_name'] = stores[key]['display_name'] + "_" + str(uniqueCounter[stores[key]['display_name']])

    return stores

def initStore(csv_store, extrahop):
    #create custom device
    criterias = csv_store['Juniper'].split(',')
    logger.info("Creating custom device for " + csv_store["display_name"] + " with criteria " + str(criterias))
    body = '{ "author": "automation script", "description": "Store", "disabled": false, "extrahop_id": "'+csv_store["Unique_ID"]+'", "name": "'+csv_store["display_name"]+'" }'
    resp = extrahop.api_request("POST", "customdevices", body=body)
    location = resp.getheader('location')
    customDeviceID = location[location.rfind('/')+1:]

    for criteria in criterias:
        cidr = criteria + "/24"
        body = '{ "custom_device_id": '+customDeviceID+', "ipaddr": "'+cidr+'"}'
        extrahop.api_request("POST", "customdevices/"+customDeviceID+"/criteria", body=body)


    #add criteria
def validateCriteria(csv_store, eh_store, extrahop):
    csv_criteria = csv_store["criteria"]
    eh_criteria = eh_store["criteria"]
    crit_to_assign = []
    crit_to_remove = []

    # Check if we need to remove criteria from EH
    for crit in eh_criteria:
        if crit["ipaddr"] not in csv_criteria:
            crit_to_remove.append(crit["ipaddr"])
            logger.info("Removing criteria: " + crit["ipaddr"] + " for " + csv_store["display_name"])
            resp = extrahop.api_request("DELETE", "customdevices/" + str(eh_store["id"]) + "/criteria/" + str(crit["id"]))

    # Check if we need to add criteria to EH
    found = []
    for crit_csv in csv_criteria:
        for crit_eh in eh_criteria:
            if crit_csv == crit_eh["ipaddr"]:
                found.append(crit_eh["ipaddr"])

    for crit in csv_criteria:
        if crit not in found:
            logger.info("Adding criteria: " + crit + " for " + csv_store["display_name"])
            body = {"custom_device_id":eh_store["custom_id"],
                    "ipaddr": crit}
            extrahop.api_request("POST","customdevices/" + str(eh_store["custom_id"] + "/criteria",body=body))



    # We've got our criteria to change.

def validateTags(csv_store, eh_store, extrahop):
    # First, check if device tag exists in eh device.
    tags_to_assign = []
    tags_to_remove = []
    for tag in csv_store["tags"]:
        if tag not in eh_store["tags"]:
            tags_to_assign.append(tag)

    # Next, check if if we need to remove tags
    for tag in eh_store["tags"]:
        if tag not in csv_store["tags"]:
            tags_to_remove.append(tag)

    tag_rm_ids = []
    tag_add_ids = []
    params = {}
    if (len(tags_to_assign) > 0) or (len(tags_to_remove) > 0):
        params = {"assign":[], "unassign": []}
        # We have tags to remove/assign.  Make the proper EH calls
        # Get the Tag IDs from EH
        eh_tags = json.loads(extrahop.api_request("GET", "tags").read())
        if (len(tags_to_assign) > 0):
            # We need to assign tags.
            for tag_a in tags_to_assign:
                for tag_e in eh_tags:
                    if tag_a == tag_e["name"]:
                        tag_add_ids.append(tag_e["id"])
            logger.info("Adding Tags for Device " + csv_store["display_name"] + ": " + str(tags_to_assign))

        if (len(tags_to_remove) > 0):
            # We need to remove tags.
            for tag_a in tags_to_remove:
                for tag_e in eh_tags:
                    if tag_a == tag_e["name"]:
                        tag_rm_ids.append(tag_e["id"])
            logger.info("Removing Tags for Device " + csv_store["display_name"] + ": " + str(tags_to_remove))

    params["assign"] = tag_add_ids
    params["remove"] = tag_rm_ids
    resp = extrahop.api_request("POST","devices/" + str(eh_store["id"]) + "/tags", body = str(params))

    if resp.status >= 300:
        try:
            resp_data = json.loads(resp.read())
        except:
            resp_data = {"message":""}

        logger.error("Unable to change tags for " + csv_store["display_name"] + " " + resp_data["message"])

def validateName(csv_store, eh_store, extrahop):
    if csv_store['display_name'] == eh_store['custom_name']:
        #sweet.. don't do shit
        pass
    else:
        #damnit....
        logger.info("Updating name from '" + eh_store['custom_name'] + "' to '" + csv_store['display_name'] + "'")
        body = '{ "custom_name": "'+csv_store['display_name']+'", "custom_type": ""}'
        extrahop.api_request("PATCH", "devices/"+eh_store['extrahop_id'], body=body)




def compare(csv_records, eh_records, custom):
    logger.debug("Comparing CSV data to Extrahop data")
    for csv_storeID in csv_records:
        if csv_storeID in eh_records:
            validateName(csv_records[csv_storeID], eh_records[csv_storeID], eh)
            validateTags(csv_records[csv_storeID], eh_records[csv_storeID], eh)
            validateCriteria(csv_records[csv_storeID], eh_records[csv_storeID], eh)
        else:
            # Not found in device list.  Let's check if the custom device is created
            store_ids_custom_dev = []
            # Currently, the extrahop-id from custom devices are padded.
            # Iterate through each one to clean them up, to be used as a key
            for key in custom.keys():
                temp_id = key.strip('~-')
                store_ids_custom_dev.append(temp_id)

            if csv_storeID not in store_ids_custom_dev:
                initStore(csv_records[csv_storeID], eh)









def load_eh_records(extrahop):
    #load custom devices
    logger.debug("Getting custom device definitions from Extrahop")
    StoreCustomDevices = {}
    tempCustom =  json.loads(extrahop.api_request("GET", "customdevices").read())
    for custom in tempCustom:
        if custom["description"] == "Store":
            StoreCustomDevices[custom["extrahop_id"]] = custom

    #load real devices
    logger.debug("Getting discovered device data from Extrahop")
    StoreDevices = {}
    tempDevices = json.loads(extrahop.api_request("GET", "devices?limit=10000&search_type=type&value=custom").read())
    for device in tempDevices:
        if device["extrahop_id"] in StoreCustomDevices:
            StoreDevices[device["extrahop_id"]] = device

    
    logger.debug("Received all devices from Extrahop.")
    loaded_stores = {}

    logger.debug("Getting criteria and tags from each device in Extrahop.  This may take some time...")
    for key in StoreDevices:
        #Grab ID for later use
        deviceID = StoreDevices[key]["id"]
        customID = StoreCustomDevices[key]["id"]

        #Make unique ID
        storeID = StoreDevices[key]["extrahop_id"].strip("~-")

        #add
        loaded_stores[storeID] = StoreDevices[key]

        #grab criteria
        criteria = json.loads(extrahop.api_request("GET", "customdevices/"+str(customID)+"/criteria").read())
        loaded_stores[storeID]["criteria"] = criteria

        #grab tags
        tags = json.loads(extrahop.api_request("GET", "devices/"+str(deviceID)+"/tags").read())
        loaded_stores[storeID]["tags"] = tags
        loaded_stores[storeID]["custom_id"] = customID

    logger.debug("Added " + str(len(loaded_stores)) + " filtered devices as stores from Extrahop")
    return loaded_stores, StoreCustomDevices

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
eh_stores, custom_devs = load_eh_records(eh)

# Load relevant CSV data into a Set of Dicts
csv_stores = load_csv_records(csv_file)

# Compare the data
compare(csv_stores,eh_stores, custom_devs)
logger.info("Finished")
