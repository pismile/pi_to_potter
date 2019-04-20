#/usr/bin/python
# -*- coding: utf-8 -*-
import io
import numpy as np
import argparse
import cv2
from cv2 import *
import picamera
import threading
from threading import Thread


import os
from os import listdir
from os.path import isfile, join, isdir

import sys
import math
import time
import imutils
import sys, traceback
import importlib.util
import paho.mqtt.client as mqtt
import json
import SpellCasting
import datetime

from imutils.video.pivideostream import PiVideoStream
fgbg = cv2.bgsegm.createBackgroundSubtractorMOG(10, 2, .5, 0);

print("Initializing point tracking")

parser = argparse.ArgumentParser(description='Cast some spells!  Recognize wand motions')
parser.add_argument('--train', help='Causes wand movement images to be stored for training selection.', action="store_true")

parser.add_argument('--circles', help='Use circles to select wand location', action="store_true")
parser.add_argument('-p','--password',nargs=1, help='MQTT Password')

args = parser.parse_args()
print((args.train))
print((args.circles))

# Parameters
lk_params = dict( winSize  = (25,25),
                  maxLevel = 7,
                  criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03))
blur_params = (4,4)
dilation_params = (5, 5)
movment_threshold = 80

active = False

# start capturing
vs = PiVideoStream().start()
time.sleep(2.0)
run_request = True
frame_holder = vs.read()
frame = None
print ("About to start.")

knn = None
nameLookup = {}

def on_connect(client, userdata,flags,rc):
    print("Python wants this")

mqttClient = mqtt.Client("",True, None, mqtt.MQTTv31)
print(args.password)
mqttClient.username_pw_set("wandtracker",args.password[0])
mqttClient.on_connect = on_connect
mqttClient.connect("localhost",8811,60)


    
def TrainOcr() :
    global knn, nameLookup
    labelNames = []
    labelIndexes = []
    trainingSet = []
    numPics = 0
    dirCount = 0
    print("Getting script path.")
    scriptpath = os.path.realpath(__file__)
    print("Script Path: " + scriptpath)
    mypath = os.path.dirname(scriptpath) + "/Pictures/"
    print("Training directory:" + mypath)
    for d in listdir(mypath):
        if isdir(join(mypath, d)):
            nameLookup[dirCount] = d
            dirCount = dirCount + 1
            for f in listdir(join(mypath,d)):
                if isfile(join(mypath,d,f)):
                    labelNames.append(d)
                    labelIndexes.append(dirCount-1)
                    trainingSet.append(join(mypath,d,f));
                    numPics = numPics + 1

    print("Training set...")
    print(trainingSet)

    print("Labels...")
    print(labelNames)

    print("Indexes...")
    print(labelIndexes)

    print("Lookup...")
    print(nameLookup)

    samples = []
    for i in range(0, numPics):
        img = cv2.imread(trainingSet[i])
        gray = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
        samples.append(gray);
        npArray = np.array(samples)
        shapedArray = npArray.reshape(-1,400).astype(np.float32);

    # Initiate kNN, train the data, then test it with test data for k=1
    knn = cv2.ml.KNearest_create()
    knn.train(shapedArray, cv2.ml.ROW_SAMPLE, np.array(labelIndexes))

lastTrainer = None
def CheckOcr(img):
    global knn, nameLookup, args, lastTrainer
    print("Testing ocr")
    size = (20,20)
    test_gray = cv2.resize(img,size,interpolation=cv2.INTER_LINEAR)
    if args.train and img != lastTrainer:
        cv2.imwrite("Pictures/char" + str(time.time()) + ".png", test_gray)
        lastTrainer = img
    imgArr = np.array(test_gray).astype(np.float32)
    sample = imgArr.reshape(-1,400).astype(np.float32)
    ret,result,neighbours,dist = knn.findNearest(sample,k=5)
    print(ret, result, neighbours, dist)
    if nameLookup[ret] is not None:
        print("Match: " + nameLookup[ret])
        return nameLookup[ret]
    else:
        return "mistakes"

def FrameReader():
    global frame_holder
    print("Starting frame holder...")
    t = threading.currentThread()
    while getattr(t, "do_run", True):
        frame = vs.read()
        fmask = imutils.resize(frame, width=400)
        cv2.flip(fmask,1,fmask)
        frame_holder = fmask
        time.sleep(.03);

def Spell(spell):
    #Invoke IoT (or any other) actions here
    print(":"+spell+":")
    spellToSend = SpellCasting.SpellCasting(spell,datetime.datetime.now().strftime("%Y%m%d %H:%M:%S.%f"),1.0)
    spellCast = json.dumps(spellToSend.__dict__)
    print(spellCast)
    mqttClient.publish("spell",spellCast)
    print("CAST: %s" %spell)


def GetPoints(image):
    if args.circles is not True:
        p0 = cv2.goodFeaturesToTrack(image, 5, .01, 30)
    else:
        p0 = cv2.HoughCircles(image,cv2.HOUGH_GRADIENT,3,50,param1=240,param2=8,minRadius=2,maxRadius=10)

        if p0 is not None:
            p0.shape = (p0.shape[1], 1, p0.shape[2])
            p0 = p0[:,:,0:2]
    return p0;

def ProcessImage():
    global frame_holder
    frame = frame_holder.copy()
    frame_gray = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    th, frame_gray = cv2.threshold(frame_gray, 230, 255, cv2.THRESH_BINARY);
    frame_gray = fgbg.apply(frame_gray);

    return frame_gray, frame

def FindWand():
    global old_frame,old_gray,p0,mask, line_mask, run_request
    try:
        last = time.time()
        t = threading.currentThread()
        while getattr(t, "do_run", True):
            now = time.time()
            if run_request:
                old_gray, old_frame = ProcessImage()
                p0 = GetPoints(old_gray)
                if p0 is not None:
                    mask = np.zeros_like(old_frame)
                    line_mask = np.zeros_like(old_gray)
                    run_request = False
                last = time.time()

            time.sleep(.2)
    except cv2.error as e:
        None
    except:
        e = sys.exc_info()[1]
        #print("Error: %s" % e)

def TrackWand():
        global old_frame,old_gray,p0,mask, line_mask, color, frame, active, run_request
        print("Starting wand tracking...")
        color = (0,0,255)
        lastRuntime = time.time()
    # Create a mask image for drawing purposes
        noPt = 0
        while True:
            try:
                active = False
                if p0 is not None:
                    active = True;
                    frame_gray, frame = ProcessImage();
                    cv2.imshow("Original", frame_gray)

                    # calculate optical flow
                    newPoints = False
                    if p0 is not None and len(p0) > 0:
                        noPt = 0
                        try:
                            if old_gray is not None and frame_gray is not None:
                                p1, st, err = cv2.calcOpticalFlowPyrLK(old_gray, frame_gray, p0, None, **lk_params)
                                newPoints = True
                        except cv2.error as e:
                            None
                        except:
                            print(".")
                            continue
                    else:
                        #print("E2", noPt)
                        noPt = noPt + 1
                        if noPt > 10:
                            try:
                                #im2,
                                contours,hierarchy = cv2.findContours(line_mask.copy(),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                                if len(contours) >=1:
                                    cnt = contours[0] 
                                    print("Contours =>", len(contours))
                                    if len(contours) > 1:
                                        area = 0
                                        for con in contours:
                                            area2 = cv2.contourArea(con)
                                            if area2 > area:
                                                area = area2
                                                cnt = con
                                    
                                    x,y,w,h = cv2.boundingRect(cnt)
                                    print("X{} Y{} W{} H{}".format(x,y,w,h))
                                    #cropX = max(x-10,0)
                                    #//cropY = max(y-10,0)
                                    #cropW = w+(x-cropX)+10
                                    #cropH =
                                    if w > 30 and h > 30:
                                         #[x:x+w,y:y+h]#]
                                        crop = line_mask[y:y+h,x:x+w]#[y-10:y+h+10,x-30:x+w+30]#y:y+h,x:x+w]
                                        cv2.imshow("Cropped", crop)
                                        print("Checking OCR", noPt)
                                        #cv2.waitKey(0) 
                                        result = CheckOcr(crop);
                                        if result != "mistakes":
                                            cv2.putText(line_mask, result, (0,50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255,255,255))
                                            Spell(result)
                                            line_mask = np.zeros_like(line_mask)
                                            noPt = 0
                                    else: 
                                        cv2.rectangle(line_mask,(x,y),(x+w,y+h),(0,255,0),5)
                                        cv2.imshow("Raspberry Potter", line_mask)
                                    
                            except:            
                                exec_type, exc_value, exc_traceback = sys.exc_info()
                                print(repr(traceback.format_exception(exec_type, exc_value, exc_traceback)))
                                print("Unexpected error", sys.exc_info()[0])
                            finally: 
                                run_request = True
                                #if noPt > 50 or lastRuntime+2 < time.time():
                                print("Reset")
                                noPt = 0
                                line_mask = np.zeros_like(line_mask)
                                

                    if newPoints:
                        # Select good points
                        good_new = p1[st==1]
                        good_old = p0[st==1]

                        # draw the tracks
                        for i,(new,old) in enumerate(zip(good_new,good_old)):
                            a,b = new.ravel()
                            c,d = old.ravel()
                            cv2.line(line_mask, (a,b),(c,d),(255,255,255), 10)

                        if line_mask is not None:
                            cv2.imshow("Raspberry Potter", line_mask)
                else:
                    if frame is not None:
                        cv2.imshow("Original", frame)
                    run_request = True
                    time.sleep(.3)

                # Now update the previous frame and previous points
                old_gray = frame_gray.copy()
                p0 = good_new.reshape(-1,1,2)
            except IndexError:
                print("Index Error")
                run_request = True
            except cv2.error as e:
                #None
                print("CV2 Error")
                #print sys.exc_info()
            except TypeError as e:
                None
                print("Type error.")
                exc_type, exc_obj, exc_tb = sys.exc_info()
                print((exc_type, exc_tb.tb_lineno))
            except KeyboardInterrupt as e:
                raise e
            except:
                None
                print("Tracking Error",noPt)
            key = cv2.waitKey(10)
            if key in [27, ord('Q'), ord('q')]: # exit on ESC
                cv2.destroyAllWindows()
                break

try:
    TrainOcr()
    t = Thread(target=FrameReader)
    t.do_run = True
    t.start()
    find = Thread(target=FindWand)
    find.do_run = True
    find.start()
    print("START incendio_pin ON and set switch off if video is running")
    time.sleep(2)
    TrackWand()
except KeyboardInterrupt:
    print("Shutting down...")
finally:
    t.do_run = False
    find.do_run = False
    t.join()
    find.join()
    cv2.destroyAllWindows()

    vs.stop()
    sys.exit(1)
