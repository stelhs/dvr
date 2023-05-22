import pathlib, os, shutil, datetime
from Syslog import *
from Task import *
from Exceptions import *
from Counters import *


class Timelapse():
    def __init__(s, fs):
        s.fs = fs
        s.cam = fs.cam
        s.fr = s.cam.fr
        s.intervalName = fs.intervalName
        s.dvrConf = s.cam.dvrConf
        s.dvr = s.cam.dvr
        s.cron = s.dvr.cron
        s.sp = s.cam.sp
        s._finished = False

        s.counters = Counters({'restart': 0})

        s.log = Syslog("Timelapse_%s_%s" % (s.intervalName, s.cam.name()))
        s.processingDir = '%s/%s_processing/%s' % (
                           s.dvrConf['timelapse']['dir'], s.intervalName,
                           s.cam.name())

        s.proc = s.sp.register("timelapseCreator_%s_%s" % (
                               s.intervalName, s.cam.name()), s.ffmpegArgs,
                               autoRestart=True, onStoppedCb=s.onFinishedProc)


    def ffmpegArgs(s):
        try:
            os.unlink(s.destFile)
        except OSError:
            pass
        return ['/usr/bin/ffmpeg',
                '-nostdin',
                '-framerate', '30',
                '-pattern_type', 'glob',
                '-i', '%s/*.jpg' % s.processingDir,
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p', s.destFile]


    def name(s):
        return "%s_%s" % (s.intervalName, s.cam.name())


    def toAdmin(s, msg):
        s.dvr.toAdmin("Timelapse_%s: %s" % (s.name(), msg))


    def startCreator(s):
        s._finished = False
        if not os.path.exists(s.processingDir):
            try:
                s.fs.exportDir(os.path.dirname(s.processingDir))
            except FrameStorageErr as e:
                raise TimelapseCreatorErr(s.log, 'Can`t start timelapse creator: %s' % e)

        d = datetime.datetime.now()
        s.destFile = "%s/%s/%s/day_%s.mp4" % (
                    s.dvrConf['timelapse']['dir'],
                    d.strftime('%Y-%m'), s.cam.name(),
                    d.strftime('%d'))
        try:
            pathlib.Path(os.path.dirname(s.destFile)).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise TimelapseCreatorErr(s.log, "Can`t create frames destination " \
                                             "directory: %s" % e) from e

        try:
            if os.path.exists(s.destFile):
                os.unlink(s.destFile)
            s.proc.start()
        except OSError as e:
            raise TimelapseCreatorErr(s.log, "Can`t remove previously " \
                                             "timelapse file: %s" % e) from e
        except SubProcessError as e:
            raise TimelapseCreatorErr(s.log, "Can`t start ffmpeg: %s" % e) from e


    def stopCreator(s):
        try:
            s.proc.stop()
        except SubProcessError as e:
            raise TimelapseErr(s.log, "Can`t stop ffmpeg: %s" % e) from e


    def isStarted(s):
        return s.proc.isStarted()


    def onFinishedProc(s, proc, rc, fin):
        s._finished = True
        s.counters.inc('restart')
        if rc != 0:
            return s.toAdmin("Timelapse_%s creation error:" \
                             "ffmpeg return non zero code: %s" % (
                             s.name(), s.proc.stdout()[-4096:]))
        shutil.rmtree(s.processingDir)
        fin()


    def createSyncCronCb(s, cronWorker=None):
        try:
            if not s.fs.filesNumber():
                return
        except IOError as e:
            return s.toAdmin("Can`t create timelapse_%s: " \
                             "FrameStorage.filesNumber error: %s" % (
                              s.name(), e))

        try:
            s.startCreator()
            Task.wait(lambda: s._finished == True,
                      timeoutSec=60*60*2, pollInterval=1000)
        except TimelapseErr as e:
            return s.toAdmin('Can`t create timelapse_%s: %s' % (
                              s.name(), e))
        except Task.WaitTimeout as e:
            s.toAdmin('Timelapse_%s creation timeout exceded: %s' % (
                              s.name(), e))
            return s.stopCreator()


    def __repr__(s):
        return "Timelapse_%s" % s.name()

