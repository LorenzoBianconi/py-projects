#!/usr/bin/python

import threading
import signal
import pickle
import time
import os
import datetime

def dumpData(data, path):
	try:
		fp = open(path, 'w')
		pickle.dump(data, fp)
		fp.close
	except IOError:
		print "failed to save data to %s" % path
		raise

class WwData:
	def __init__(self, rH, temp):
		self.ts = datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S')
		self.rH = rH
		self.temp = temp

	def getTs(self): return self.ts
	def getRh(self): return self.rH
	def getTemp(self): return self.temp
	def printSample(self):
		print "%s rH=%.3f temp=%.3f" % (self.ts, self.rH, self.temp)

class WwReaderTh(threading.Thread):
	def __init__(self, sampleList, lock, shutdownEvent, timeOut):
		threading.Thread.__init__(self)

		self.sampleList = sampleList

		self.shutdownEvent = shutdownEvent
		self.lock = lock

		self.timeOut = timeOut
		self.maxListSize = 60
		self.lastSample = datetime.date.today()

		self.rhPath = "/sys/bus/iio/devices/iio:device0/"
		self.tempPath = "/sys/bus/iio/devices/iio:device1/"

		self.rhScale = self.readData(self.rhPath +
					     "in_humidityrelative_scale")
		self.rhOffset = self.readData(self.rhPath +
					      "in_humidityrelative_offset")
		self.tempScale = self.readData(self.tempPath + "in_temp_scale")
		self.tempOffset = self.readData(self.tempPath + "in_temp_offset")

	def run(self):
		while not self.shutdownEvent.is_set():
			rH_raw = self.readData(self.rhPath + "in_humidityrelative_raw")
			rH = (rH_raw + self.rhOffset) * self.rhScale

			temp_raw = self.readData(self.tempPath+ "in_temp_raw")
			temp = (temp_raw + self.tempOffset) * self.tempScale

			self.lock.acquire()
			self.sampleList.append(WwData(rH, temp))
			if len(self.sampleList) > self.maxListSize :
				staleSample = self.sampleList.pop(0)
				del staleSample
			self.lock.release()

			sampleTs = datetime.date.today()
			if sampleTs - self.lastSample >= datetime.timedelta(1) :
				dumpData(self.sampleList, '/tmp/sampleList')
				self.self.lastSample = sampleTs

			time.sleep(self.timeOut)

	def readData(self, path):
		try:
			fp = open(path, 'r')
			data = float(fp.readline().strip())
			fp.close

			return data
		except IOError:
			print "failed to open %s" % path

class WwReader:
	def __init__(self):
		try:
			fp = open('/tmp/sampleList', 'r')
			self.sampleList = pickle.load(fp)
			fp.close
		except IOError:
			self.sampleList = []

		self.shutdownEvent = threading.Event()
		self.lock = threading.Lock()

		self.wwThread = WwReaderTh(self.sampleList, self.lock,
					   self.shutdownEvent, 1800)

		signal.signal(signal.SIGTERM, self.sigTermHl)
		signal.signal(signal.SIGINT, self.sigTermHl)

	def startMeasuring(self):
		print "WwReader: starting process %d" % os.getpid()
		self.wwThread.start()

		while self.wwThread.isAlive():
			self.wwThread.join(1)

		dumpData(self.sampleList, '/tmp/sampleList')

		for i in range(len(self.sampleList)):
			self.sampleList[i].printSample()

	def sigTermHl(self, signum, frame):
		self.shutdownEvent.set()

if __name__ == '__main__':
	wwReader = WwReader()
	wwReader.startMeasuring()

