import pathlib, os, shutil, datetime, re
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
        s._startTime = None
        s._finishTime = None
        s._filesNumber = 0

        s.counters = Counters({'onFinishedProc': 0,
                               'startCreator': 0,
                               'stopCreator': 0,
                               'createSyncCronCb': 0,
                               'createSyncFinished': 0})

        s.log = Syslog("Timelapse_%s_%s" % (s.intervalName, s.cam.name()))
        s.processingDir = '%s/%s_processing/%s' % (
                           s.dvrConf['timelapse']['dir'], s.intervalName,
                           s.cam.name())

        s.proc = s.sp.register("timelapseCreator_%s_%s" % (
                               s.intervalName, s.cam.name()), s.ffmpegArgs,
                               autoRestart=True, onStoppedCb=s.onFinishedProc, nice=-20)


    def ffmpegArgs(s):
        try:
            os.unlink(s.destFile)
        except OSError:
            pass
        return ['/usr/bin/ffmpeg',
                '-nostdin',
                '-f', 'image2',
                '-i', '%s/%%6d.jpg' % s.processingDir,
                '-vcodec', 'libx264',
                '-b', '2400k', s.destFile]


    def name(s):
        return "%s_%s" % (s.intervalName, s.cam.name())


    def toAdmin(s, msg):
        s.dvr.toAdmin("Timelapse_%s: %s" % (s.name(), msg))


    def createProcessingDir(s):
        if os.path.exists(s.processingDir):
            return
        try:
            if not s.fs.filesNumber():
                return
        except IOError as e:
            raise TimelapseCreatorErr(s.log, "FrameStorage.filesNumber error: %s" % e)
        try:
            s.fs.exportDir(os.path.dirname(s.processingDir))
        except FrameStorageErr as e:
            raise TimelapseCreatorErr(s.log, 'Can`t start timelapse ' \
                                             'creator: %s' % e)


    def start(s):
        s.counters.inc('startCreator')
        s._finishTime = None
        s._startTime = now()
        s._finished = False
        if not s.isIncomplete():
            raise TimelapseCreatorErr(s.log, 'No processingDir')

        s._accumulationStartTime = s.accumulationStartTime()
        s._accumulationEnd = s.accumulationEnd()

        d = datetime.datetime.fromtimestamp(s._accumulationStartTime)
        s.destFileRelative = "%s_%s_%s.mp4" % (
                    s.intervalName, d.strftime('%Y_%m_%d_%H_%M_%S'),
                    s.cam.name())
        s.destFile = "%s/%s" % (
                    s.dvrConf['timelapse']['dir'],
                    s.destFileRelative)
        try:
            s._filesNumber = s.filesNumber()
            if os.path.exists(s.destFile):
                os.unlink(s.destFile)
            s.proc.start()
        except OSError as e:
            raise TimelapseCreatorErr(s.log, "Can`t remove previously " \
                                             "timelapse file: %s" % e) from e
        except SubProcessError as e:
            raise TimelapseCreatorErr(s.log, "Can`t start ffmpeg: %s" % e) from e


    def stop(s):
        s.counters.inc('stopCreator')
        s._finishTime = now()
        try:
            s.proc.stop()
        except SubProcessError as e:
            raise TimelapseErr(s.log, "Can`t stop ffmpeg: %s" % e) from e


    def isStarted(s):
        return s.proc.isStarted()


    def isIncomplete(s):
        if not os.path.exists(s.processingDir):
            return False
        if len(os.listdir(s.processingDir)) == 0:
            return False
        return True


    def filesNumber(s):
        try:
            return len(os.listdir(s.processingDir))
        except OSError as e:
            raise TimelapseFramesErr(s.log, "Timelapse.filesNumber() error: %e" % e)


    def onFinishedProc(s, proc, rc, fin):
        s._finished = True
        s.counters.inc('onFinishedProc')
        if rc != 0:
            return s.toAdmin("Timelapse_%s creation error:" \
                             "ffmpeg return non zero code: %s" % (
                             s.name(), s.proc.stdout()[-4096:]))

        videoDuration = 0
        try:
            videoDuration = s.ffmpegStat()['videoDuration']
        except TimelapseErr as e:
            s.toAdmin('Can`t get videoDuration %s: %s' % (s.name(), e))

        fileSize = 0
        try:
            fileSize = os.path.getsize(s.destFile)
        except OSError as e:
            s.toAdmin('Can`t get timelapse file size %s: %s' % (s.name(), e))

        try:
            s.dvr.db.insert('timelapses',
                            {'cam_name': s.cam.name(),
                             'interval_name': s.intervalName,
                             'fname': s.destFileRelative,
                             'video_duration': videoDuration,
                             'progress_duration': s.progressDuration(),
                             'file_size': fileSize},
                            {'start': 'FROM_UNIXTIME(%d)' % s._accumulationStartTime,
                             'end': 'FROM_UNIXTIME(%d)' % s._accumulationEnd})
        except DatabaseConnectorError as e:
            s.toAdmin("Can`t insert into database file %s: %s" % (
                      s.destFileRelative, e))

        shutil.rmtree(s.processingDir)
        s._finishTime = now()
        fin()


    def accumulationStartTime(s):
        try:
            with open("%s/created" % s.processingDir, "r") as f:
                return int(f.read().strip())
        except (OSError, ValueError) as e:
            raise TimelapseFramesErr(s.log, "accumulationStartTime %s error: %s" % (s.name(), e))


    def accumulationEnd(s):
        try:
            with open("%s/export" % s.processingDir, "r") as f:
                return int(f.read().strip())
        except (OSError, ValueError) as e:
            raise TimelapseFramesErr(s.log, "accumulationEnd %s error: %s" % (s.name(), e))


    def createSyncCronCb(s, cronWorker=None):
        s.counters.inc('createSyncCronCb')

        msg = "Start timelapse creator %s by cron %s" % (s.name(), cronWorker.name())
        s.log.info(msg)
        print(msg)

        try:
            s.createProcessingDir()
            s.createSync()
        except AppError as e:
            s.toAdmin('Can`t create timelapse %s: %s' % (s.name(), e))


    def createSync(s):
        if not s.isIncomplete():
            raise TimelapseCreatorErr(s.log, "Can't create timelapse %s: " \
                                             "processingDir is not exist" % s.name())
        timeout = 60*60*6
        try:
            s.start()
            Task.wait(lambda: s._finished == True,
                      timeoutSec=timeout, pollInterval=1000)
            s.counters.inc('createSyncFinished')
        except Task.WaitTimeout:
            s.stop()
            raise TimelapseCreatorErr(s.log, "Timelapse %s creates " \
                                             "more then %s" % timeDurationStr(timeout))


    def ffmpegStat(s):
        try:
            cnt, fps, h, m, sec = re.findall('frame=\s*(\d+)\s+fps=\s*([\d.]+).*time=(\d{2}):(\d{2}):(\d{2})',
                                            s.proc.stdout())[-1]
        except (IndexError, TypeError, ValueError) as e:
            raise TimelapseFFmpegErr(s.log, 'ffmpeg stdout parse error: %s; stdout: %s' % (
                                            e, s.proc.stdout()[-512:])) from e

        progress = 'undefined'
        try:
            if s._filesNumber:
                progress = (int(cnt) * 100) / s._filesNumber
        except TimelapseErr:
            pass

        try:
            return {'cnt': int(cnt),
                    'total': s._filesNumber,
                    'fps': float(fps),
                    'videoDuration': int(h) * 3600 + int(m) * 60 + int(sec),
                    'progressDuration': s.progressDuration(),
                    'progressStat': progress}
        except ValueError as e:
            raise TimelapseFFmpegErr(s.log, 'ffmpeg status type error: %e. stdout: %s' % (
                                            e, s.proc.stdout()[-512:])) from e


    def printFFmpeg(s):
        print(s.proc.stdout()[-200:])


    def progressDuration(s):
        if not s._startTime:
            return 0
        if not s._finishTime:
            return now() - s._startTime
        return s._finishTime - s._startTime


    def __repr__(s):
        return "Timelapse_%s" % s.name()


