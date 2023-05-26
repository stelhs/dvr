import pathlib, shutil, os, threading
from Syslog import *
from Cron import *
from Timelapse import *
from Exceptions import *
from Counters import *


class FrameStorage():
    def __init__(s, cam, intervalName, cronRule):
        s.cam = cam
        s.fr = cam.fr
        s.intervalName = intervalName
        s.varStorage = cam.varStorage
        s.cron = cam.cron
        s.dvrConf = cam.dvrConf
        s._enabled = False
        s.log = Syslog("FrameStorage_%s" % s.name())
        s.frameStoreLock = threading.Lock()

        s.counters = Counters({'totalFrames': 0,
                               'exportDirs': 0})

        s.fsDir = '%s/%s_frames/%s' % (s.dvrConf['timelapse']['dir'],
                                       intervalName, cam.name())

        try:
            s.cw = s.cron.worker('FrameStorage_%s' % intervalName)
        except Cron.Err:
            s.cw = s.cron.register('FrameStorage_%s' % intervalName,
                                    cronRule, sync=True)
        s.cw.addCb(s.frameStoreCronCb)

        s.frameCnt = s.varStorage.key('/cam_%s/timelapse/%sFrameCnt' % (
                                      cam.name(), intervalName), 1)
        s.tlps = Timelapse(s)


    def name(s):
        return "%s_%s" % (s.cam.name(), s.intervalName)


    def enable(s):
        s._enabled = True


    def disable(s):
        s._enabled = False


    def dirExists(s):
        return os.path.exists(s.fsDir)


    def createDir(s):
        if s.dirExists():
            return

        pathlib.Path(s.fsDir).mkdir(parents=True, exist_ok=True)
        with open("%s/created" % s.fsDir, "w") as f:
            f.write(str(now()))


    def frameStoreCronCb(s, cronWorker=None):
        if not s._enabled:
            return

        def do(fName, created):
            if not s.dirExists():
                s.createDir()

            newFName = "%s/%06d.jpg" % (s.fsDir, s.frameCnt.val)
            try:
                shutil.copyfile(fName, newFName)
                s.frameCnt.set(s.frameCnt.val + 1)
                s.counters.inc('totalFrames')
            except OSError as e:
                s.log.err("Can`t move %s to %s: %s" % (fName, newFName, e))

        with s.frameStoreLock:
            try:
                if not s.fr.isStarted():
                    return
                s.fr.processFile(do)
            except CamFrameRecorderErr as e:
                s.log.err('Can`t getting frame: %s' % e)


    def filesNumber(s):
        return len(os.listdir(s.fsDir))


    def exportDir(s, newDir):
        with s.frameStoreLock:
            if not s.filesNumber():
                raise FrameStorageErr(s.log, 'No frame files')

            try:
                with open("%s/export" % s.fsDir, "w") as f:
                    f.write(str(now()))

                pathlib.Path(newDir).mkdir(parents=True, exist_ok=True)
                shutil.move(s.fsDir, newDir)
                s.counters.inc('exportDirs')
            except OSError as e:
                raise FrameStorageErr(s.log, "Can`t export directory %s. " \
                                                 "to directory: %s" % (
                                                 s.fsDir, newDir, e)) from e
            try:
                s.createDir()
            except OSError as e:
                raise FrameStorageErr(s.log, "Can`t create directory %s: %s" % (
                                                  s.fsDir, e)) from e
            s.frameCnt.set(0)


    def mkTimelapseByCron(s, cronWorker):
        cronWorker.addCb(s.tlps.createSyncCronCb)


    def __repr__(s):
        return "FrameStorage:%s" % s.name()



