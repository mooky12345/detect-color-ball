

import json
import time
import sys
import cv2
import numpy as np
from math import atan, tan, sin

from cscore import CameraServer, VideoSource, UsbCamera, MjpegServer
from networktables import NetworkTablesInstance, NetworkTables





class CameraConfig: pass

team = None
server = False
cameraConfigs = []
switchedCameraConfigs = []
cameras = []
configFile = None
def parseError(str):
    pass

def readCameraConfig(config):
    """Read single camera configuration."""
    cam = CameraConfig()

    # name
    try:
        cam.name = config["name"]
    except KeyError:
        parseError("could not read camera name")
        return False

    # path
    try:
        cam.path = config["path"]
    except KeyError:
        parseError("camera '{}': could not read path".format(cam.name))
        return False

    # stream properties
    cam.streamConfig = config.get("stream")

    cam.config = config

    cameraConfigs.append(cam)
    return True

def readSwitchedCameraConfig(config):
    
    cam = CameraConfig()

    # name
    try:
        cam.name = config["name"]
    except KeyError:
        parseError("could not read switched camera name")
        return False

    # path
    try:
        cam.key = config["key"]
    except KeyError:
        parseError("switched camera '{}': could not read key".format(cam.name))
        return False

    switchedCameraConfigs.append(cam)
    return True

def readConfig():
    """Read configuration file."""
    global team
    global server

   

    # top level must be an object
    if not isinstance(j, dict):
        parseError("must be JSON object")
        return False

    # team number
    try:
        team = j["team"]
    except KeyError:
        parseError("could not read team number")
        return False

    # ntmode (optional)
    if "ntmode" in j:
        str = j["ntmode"]
        if str.lower() == "client":
            server = False
        elif str.lower() == "server":
            server = True
        else:
            parseError("could not understand ntmode value '{}'".format(str))

    # cameras
    try:
        cameras = j["cameras"]
    except KeyError:
        parseError("could not read cameras")
        return False
    for camera in cameras:
        if not readCameraConfig(camera):
            return False

    # switched cameras
    if "switched cameras" in j:
        for camera in j["switched cameras"]:
            if not readSwitchedCameraConfig(camera):
                return False

    return True

def startCamera(config):
    
    print("Starting camera '{}' on {}".format(config.name, config.path))
    inst = CameraServer.getInstance()
    camera = UsbCamera(config.name, config.path)
    server = inst.startAutomaticCapture(camera=camera, return_server=True)

    camera.setConfigJson(json.dumps(config.config))
    camera.setConnectionStrategy(VideoSource.ConnectionStrategy.kKeepOpen)

    if config.streamConfig is not None:
        server.setConfigJson(json.dumps(config.streamConfig))

    return camera

def startSwitchedCamera(config):
    
    print("Starting switched camera '{}' on {}".format(config.name, config.key))
    server = CameraServer.getInstance().addSwitchedCamera(config.name)

    def listener(fromobj, key, value, isNew):
        if isinstance(value, float):
            i = int(value)
            if i >= 0 and i < len(cameras):
              server.setSource(cameras[i])
        elif isinstance(value, str):
            for i in range(len(cameraConfigs)):
                if value == cameraConfigs[i].name:
                    server.setSource(cameras[i])
                    break

    NetworkTablesInstance.getDefault().getEntry(config.key).addListener(
        listener,
        NetworkTablesInstance.NotifyFlags.IMMEDIATE |
        NetworkTablesInstance.NotifyFlags.NEW |
        NetworkTablesInstance.NotifyFlags.UPDATE)

    return server

def processImg(input_img):
    global vision_nt, f, pi, d, g, cam_resolution
    
    output_img = np.copy(input_img)
    hsv_img = cv2.cvtColor(input_img, cv2.COLOR_BGR2HSV)
    binary_img = cv2.inRange(hsv_img, (22.7, 73.4, 130), (34.1, 255, 255))
    im2, contour_list, hierachy = cv2.findContours(binary_img, mode=cv2.RETR_EXTERNAL, method=cv2.CHAIN_APPROX_SIMPLE)

    max_area = 0
    max_contour = None
    for contour in contour_list:

        # Ignore small contours that could be because of noise/bad thresholding
        area = cv2.contourArea(contour)
        if area < 50:
            continue

        cv2.drawContours(output_img, contour, -1, color = (255, 255, 255), thickness = -1)
        
        if area > max_area:
            max_area = area
            max_contour = contour
        
        #corners = cv2.approxPolyDP(contour, 0.03 * cv2.arcLength(contour), True)
        #print(corners)
    
    output_val = (0, 0, 0, 0, 0, 0)
    # Draw rectangle and circle
    if max_contour is not None:
        area = cv2.contourArea(max_contour)
        rect = cv2.minAreaRect(max_contour)
        center, size, angle = rect
        center = [int(dim) for dim in center] # Convert to int so we can draw
        cv2.drawContours(output_img, [np.int0(cv2.boxPoints(rect))], -1, color = (0, 0, 255), thickness = 2)
        cv2.circle(output_img, center = tuple(center), radius = 3, color = (0, 0, 255), thickness = -1)
        degree_x = atan( (center[0] - 400)/f )/pi*180
        degree_x = int(degree_x*100)/100
        center[0] -= 400
        center[1] -= 300
        a = atan((-center[1])/f)+d
        obj_x = int(height/tan(a))
        mult = height/f/sin(a)
        obj_y = int((-center[0])*mult)
        
        output_val = (center[0], center[1], area, obj_x, obj_y, degree_x)
    
    return output_img, output_val

vision_nt = None
f = 760.4772721
pi = 3.1415927
d = -0.29082
height = -50
cam_resolution = [400, 300]

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        configFile = sys.argv[1]

    # read configuration
    if not readConfig():
        sys.exit(1)

    # start NetworkTables
    ntinst = NetworkTablesInstance.getDefault()
    if server:
        print("Setting up NetworkTables server")
        ntinst.startServer()
    else:
        print("Setting up NetworkTables client for team {}".format(team))
        ntinst.startClientTeam(team)
        ntinst.startDSClient()

    # start cameras
    for config in cameraConfigs:
        cameras.append(startCamera(config))

    # start switched cameras
    for config in switchedCameraConfigs:
        startSwitchedCamera(config)

    CS = CameraServer.getInstance()
    visionCam = CS.getServer('rPi Camera 0')
    h = visionCam.getVideoMode().height
    w = visionCam.getVideoMode().width
    input_stream = CS.getVideo(camera=visionCam)
    output_stream = CS.putVideo("processed", h, w)
    
    # Table for vision output information
    vision_nt = NetworkTables.getTable('Vision')
    
    input_img = None
    # loop forever
    while True:
        grab_time, input_img = input_stream.grabFrame(input_img)
        if grab_time == 0:
            output_stream.notifyError(input_stream.getError())
            continue
        output_img, output_val = processImg(input_img)
        
        output_stream.putFrame(output_img)
        vision_nt.putNumber('center_x', output_val[0])
        vision_nt.putNumber('center_y', output_val[1])
        vision_nt.putNumber('area', output_val[2])
        vision_nt.putNumber('obj_x', output_val[3])
        vision_nt.putNumber('obj_y', output_val[4])
        vision_nt.putNumber('degree_x', output_val[5])
        
        time.sleep(0.01)
