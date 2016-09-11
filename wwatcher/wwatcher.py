#!/usr/bin/python

import threading
import signal
import pickle
import time
import os
import datetime
import socket
import sys
import getopt

DATA_FILE_PATH = '/tmp/sampleList'

RH_PATH = '/sys/bus/iio/devices/iio:device0/'
RH_SCALE = RH_PATH + 'in_humidityrelative_scale'
RH_OFFSET = RH_PATH + 'in_humidityrelative_offset'
RH_RAW = RH_PATH + 'in_humidityrelative_raw'

TEMP_PATH = '/sys/bus/iio/devices/iio:device1/'
TEMP_SCALE = TEMP_PATH + 'in_temp_scale'
TEMP_OFFSET = TEMP_PATH + 'in_temp_offset'
TEMP_RAW = TEMP_PATH + 'in_temp_raw'

TCP_PORT = 9900
MAX_BUFF_SIZE = 32

def usage():
	print 'wwatcher.py -h -t <timeout> -s <samples>'

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
	def getRh(self): return "{0:.2f}".format(self.rH)
	def getTemp(self): return "{0:.2f}".format(self.temp)
	def printSample(self):
		print "%s rH=%.3f temp=%.3f" % (self.ts, self.rH, self.temp)
	def dumpJsonData(self):
		self.data = "{\"ts\":\"" + self.ts + "\","
		self.data += "\"rH\":\"" + str(self.getRh()) + "\","
		self.data += "\"temp\":\"" + str(self.getTemp()) + "\"}"

		return self.data

class WwSamplingThread(threading.Thread):
	def __init__(self, sampleList, lock, shutdownEvent, timeOut, samples):
		threading.Thread.__init__(self)

		self.sampleList = sampleList

		self.shutdownEvent = shutdownEvent
		self.lock = lock

		self.timeOut = timeOut
		self.maxListSize = samples
		self.lastSample = datetime.date.today()

		self.rhScale = self.readData(RH_SCALE)
		self.rhOffset = self.readData(RH_OFFSET)
		self.tempScale = self.readData(TEMP_SCALE)
		self.tempOffset = self.readData(TEMP_OFFSET)

	def run(self):
		while not self.shutdownEvent.is_set():
			rH_raw = self.readData(RH_RAW)
			rH = (rH_raw + self.rhOffset) * self.rhScale

			temp_raw = self.readData(TEMP_RAW)
			temp = (temp_raw + self.tempOffset) * self.tempScale

			self.lock.acquire()
			self.sampleList.append(WwData(rH, temp))
			if len(self.sampleList) > self.maxListSize :
				staleSample = self.sampleList.pop(0)
				del staleSample
			self.lock.release()

			sampleTs = datetime.date.today()
			if sampleTs - self.lastSample >= datetime.timedelta(1) :
				dumpData(self.sampleList, DATA_FILE_PATH)
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

class WwTcpThread(threading.Thread):
	def __init__(self, sock, sampleList, lock, address):
		threading.Thread.__init__(self)

		print "WwTcpThread: got connection from %s port %d" % address

		self.sock = sock
		self.address = address

		self.sampleList = sampleList
		self.lock = lock

	def run(self):
		try:
			while True:
				self.data = self.sock.recv(MAX_BUFF_SIZE)
				if self.data:
					print "WwTcpThread: %s %d" \
					       " rx %s" % (self.address[0],
							   self.address[1],
							   self.data)
					self.data = "\"items\": ["
					self.lock.acquire()
					for i in range(len(self.sampleList)):
						self.entry = self.sampleList[i].dumpJsonData()
						self.data += self.entry
						if i < len(self.sampleList) - 1 :
							self.data += ","
					self.lock.release()
					self.data += "]"
					self.sock.sendall(self.data)
				else:
					print "WwTcpThread: %s %d" \
					      " connection closed" % self.address
					break

		finally:
			self.sock.close()

class Wwatcher:
	def __init__(self, timeout, samples):
		try:
			fp = open(DATA_FILE_PATH, 'r')
			self.sampleList = pickle.load(fp)
			fp.close
		except IOError:
			self.sampleList = []

		self.shutdownEvent = threading.Event()
		self.lock = threading.Lock()

		self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.sock.bind(('', TCP_PORT))
		self.sock.listen(5)

		self.wwSamplingThread = WwSamplingThread(self.sampleList,
							 self.lock,
							 self.shutdownEvent,
							 timeout, samples)

		signal.signal(signal.SIGTERM, self.sigTermHl)
		signal.signal(signal.SIGINT, self.sigTermHl)

	def startMeasuring(self):
		print "Wwatcher: starting process %d" % os.getpid()
		self.wwSamplingThread.start()

		try:
			while not self.shutdownEvent.is_set():
				self.clientSock, self.clientAddress = self.sock.accept()

				self.wwTcpThread = WwTcpThread(self.clientSock,
							       self.sampleList,
							       self.lock,
							       self.clientAddress)
				self.wwTcpThread.start()
		except IOError:
			pass
		finally:
			self.sock.close()
			dumpData(self.sampleList, DATA_FILE_PATH)

	def sigTermHl(self, signum, frame):
		self.shutdownEvent.set()

if __name__ == '__main__':
	try:
		#default values
		timeout = 1800
		samples = 336
		opts, args = getopt.getopt(sys.argv[1:],"ht:s:",
					   ["help", "timeout", "samples"])
		for opt, arg in opts:
			if opt in ("-h", "--help"):
				usage()
				sys.exit()
			elif opt in ("-t", "--timeout"):
				timeout = int(arg)
			elif opt in ("-s", "--samples"):
				samples = int(arg)
			else:
				assert False, "unhandled option"

		wwatcher = Wwatcher(timeout, samples)
		wwatcher.startMeasuring()
	except getopt.GetoptError:
		usage()
		sys.exit(2)

