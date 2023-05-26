import threading, pathlib, os, inotify
import inotify.adapters
from Syslog import *
from Task import *
from Cron import *
from Exceptions import *
from Counters import *


class FrameRecorder():
    def __init__(s, cam):
        s.cam = cam
        s.dvr = cam.dvr
        s.dvrConf = cam.dvrConf
        s.sp = cam.sp
        s.cron = cam.dvr.cron
        s.captureLock = threading.Lock()
        s._lastFile = None
        s._lastUpdate = now()

        s.counters = Counters({'restartByTimeout': 0,
                               'totalFrames': 0,
                               'autoRestart': 0})

        s._restartCnt = 0

        s.log = Syslog("FrameRecorder_%s" % s.name())

        s.tmpDir = '%s/%s' % (s.dvrConf['frameRecorder']['tmpDir'], s.cam.name())
        s.proc = s.sp.register("FrameRecorder_%s" % s.cam.name(), s.ffmpegArgs,
                                autoRestart=True, onStoppedCb=s.killCb, nice=10)

        s.cleanTmp()
        s.inotify = inotify.adapters.Inotify()
        s.inotify.add_watch(s.tmpDir)
        s.inotifyTask = Task.asyncRun('FrameRecorderInotify_%s' % s.cam.name(),
                                      s.inotifyDo)

        try:
            s.cw = s.cron.worker('FrameRecorderRestarter')
        except Cron.Err:
            s.cw = s.cron.register('FrameRecorderRestarter', ('0 */1 * * * *',))
        s.cw.addCb(s.checkForRestart)



    def ffmpegArgs(s):
        return ['/usr/bin/ffmpeg',
                '-nostdin',
                '-loglevel', 'error',
                '-rtsp_transport', 'tcp',
                '-use_wallclock_as_timestamps', '1',
                '-i', s.cam.rtsp(),
                '-vf', (('fps=%s,' % s.dvrConf['frameRecorder']['frequency']) +
                        ('drawtext=fontfile=%s:' % s.dvrConf['frameRecorder']['fontFile']) +
                                ('fontsize=36:' \
                                 'fontcolor=yellow:' \
                                 'box=1:' \
                                 'boxcolor=black@0.4:' \
                                 "text='%%{pts\:localtime\:%s}'" % now())),
                '-qscale:v', '2',
                '%s/img_%%04d.jpg' % s.tmpDir]


    def name(s):
        return s.cam.name()


    def toAdmin(s, msg):
        s.dvr.toAdmin("FrameRecorder %s: %s" % (s.name(), msg))


    def start(s):
        if s.proc.isStarted():
            raise CamFrameRecorderErr(s.log,
                    "Can't starting frame recorder '%s': " \
                    "Already was started" % s.name())
        try:
            s.proc.start()
        except SubProcessError as e:
            raise CamFrameRecorderErr(s.log, "Can't start ffmpeg: %s" % e) from e


    def stop(s):
        if not s.proc.isStarted():
            raise CamFrameRecorderErr(s.log,
                    "Can't stopping frame recorder '%s': " \
                    "Already was stopped" % s.name())

        with s.captureLock:
            try:
                s.proc.stop()
            except SubProcessError as e:
                raise CamFrameRecorderErr(s.log, "Can't stop ffmpeg: %s" % e) from e

        s.log.info("camcorder '%s' recording has stopped" % s.cam.name())


    def restart(s):
        if not s.isStarted():
            raise CamFrameRecorderErr(s.log,
                    "Can't restart frame recorder '%s': " \
                    "Frame recorder is not started" % s.name())

        s.counters.inc('restartByTimeout')
        s.proc.restart()


    def isStarted(s):
        return s.proc.isStarted()


    def killCb(s, proc, retCode, fin):
        if not s.isStarted():
            return
        s.cleanTmp()
        s._lastFile = None
        s._lastUpdate = now()
        s.counters.inc('autoRestart')


    def cleanTmp(s):
        pathlib.Path(s.tmpDir).mkdir(parents=True, exist_ok=True)
        for i in os.listdir(s.tmpDir):
            try:
                os.remove("%s/%s" % (s.tmpDir, i))
            except IOError:
                pass


    def inotifyDo(s):
        while 1:
            Task.sleep(0)
            for event in s.inotify.event_gen(yield_nones=False, timeout_s=1):
                (_, evType, _, tmpFname) = event
                if 'IN_CLOSE_WRITE' not in evType:
                    continue
                s._lastUpdate = now()
                with s.captureLock:
                    s.counters.inc('totalFrames')
                    prevFile = s._lastFile
                    s._lastFile = "%s/%s" % (s.tmpDir, tmpFname)
                    if prevFile:
                        try:
                            os.unlink(prevFile)
                        except OSError:
                            pass


    def imgFileName(s):
        if not s._lastFile:
            raise CamFramerNoDataErr(s.log, 'captured image file not found')

        if s.updateInterval() > 60:
            raise CamFramerNoDataErr(s.log, 'captured image file outdated')
        return s._lastFile


    def processFile(s, cb):
        with s.captureLock:
            fname = s.imgFileName()
            return cb(fname, s._lastUpdate)


    def updateInterval(s):
        return now() - s._lastUpdate


    def checkForRestart(s, cronWorker=None):
        return
        if not s.isStarted():
            return

        if s.updateInterval() > 60:
            s._lastUpdate = now()
            try:
                return s.proc.restart()
            except SubProcessError as e:
                s.toAdmin('checkForRestart error: %s' % e)


    def __repr__(s):
        return "FrameRecorder:%s" % s.cam.name()

