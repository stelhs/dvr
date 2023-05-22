import datetime, os, subprocess, re
from Syslog import *
from Exceptions import *
from HttpServer import *
from Counters import *
from Cron import *


class VideoRecorder():
    def __init__(s, cam):
        s.cam = cam
        s.cron = cam.cron
        s.camConf = cam.conf
        s.dvrConf = cam.dvrConf
        s.dvr = cam.dvr
        s.sp = cam.sp
        s.db = cam.db

        s.log = Syslog("VideoRecorder_%s" % cam.name())
        if 'HIDE_ERRORS' in cam.options():
            s.log.mute('error')
            s.log.mute('info')

        s.counters = Counters({'restart': 0,
                               'openRtspNoFile': 0,
                               'openRtspNullSize': 0,
                               'encodeErr': 0,
                               'encoderOutputParseErr': 0,
                               'dbInsertErr': 0,
                               'autoRestart': 0,
                               'restartByTimeout': 0,
                               'restartByTimeoutFail': 0,
                               'totalFiles': 0,
                               'successFiles': 0})

        s.openRtspProc = s.sp.register("openRTSP:%s" % cam.name(), s.openRtspArgs,
                                       autoRestart=True, onStoppedCb=s.openRtspOnKillCb)
        s._restartFlag = False
        s._lastUpdate = now()

        try:
            s.cw = s.cron.worker('VideoRecorderRestarter')
        except Cron.Err:
            s.cw = s.cron.register('VideoRecorderRestarter', ('30 */1 * * * *',))
        s.cw.addCb(s.checkForRestart)



    def openRtspArgs(s):
        return ['/usr/local/bin/openRTSP',
                '-D', '20',
                '-K',
                '-b', '1000000',
                '-P', str(s.dvrConf['videoRecorder']['videoFileDuration']),
                '-c',
                '-t',
                '-f', str(s.camConf['video']['frameRate']),
                '-F', s.cam.name(),
                '-N', s.dvrConf['videoRecorder']['openRtspCb'],
                s.cam.rtsp()]


    def openRtspOnKillCb(s, proc, rc, fin):
        if s.isStarted():
            s.log.info("openRTSP %s killed" % s.cam.name())
            s.counters.inc('autoRestart')


    def start(s):
        if s.isStarted():
            raise CamVideoErr(s.log,
                    "Can't starting camcorder '%s' recording. " \
                    "Recording already was started" % s.cam.name())
        s.openRtspProc.start()


    def stop(s):
        if not s.isStarted():
            raise CamVideoErr(s.log,
                    "Can't stopping camcorder '%s' recording. " \
                    "Recording already was stopped" % s.cam.name())
        s.openRtspProc.stop()
        s.log.info("camcorder '%s' recording has stopped" % s.cam.name())


    def restart(s):
        s.openRtspProc.restart()
        s.counters.inc('restart')
        s._lastUpdate = now()


    def restartAsync(s):
        s._restartFlag = True


    def size(s):
        row = s.db.query("select sum(file_size) as size "\
                         "from videos where cam_name = '%s'" %
                         s.cam.name())
        if 'size' not in row:
            return 0
        return int(row['size'])


    def duration(s):
        row = s.db.query("select sum(duration) as sum from videos "\
                         "where cam_name = '%s' and file_size is not NULL" %
                          s.cam.name());
        if 'sum' not in row or row['sum'] == None:
            return 0
        return int(row['sum'])


    def openRtspHandler(s, args, conn):
        startTime = int(args['start_time'])
        videoFile = args['video_file']
        audioFile = args['audio_file'] if 'audio_file' in args else None
        startDate = datetime.datetime.fromtimestamp(startTime)

        try:
            vsize = os.path.getsize(videoFile)
        except FileNotFoundError:
            s.log.err("openRtspHandler: file %s not exist" % videoFile)
            s.counters.inc('openRtspNoFile')
            s.restartAsync()
            raise HttpHandlerError("file %s not exist" % videoFile)

        s.counters.inc('totalFiles')

        if vsize == 0:
            s.log.err("openRtspHandler: file %s has null size" % videoFile)
            s.counters.inc('openRtspNullSize')
            s.restartAsync()
            raise HttpHandlerError("file %s null size" % videoFile)

        ffmpegCmd = 'ffmpeg -i %s ' % videoFile
        aCopy = ''
        if audioFile:
            if s.cam.audioCodec == 'PCMA':
                ffmpegCmd += '-f alaw -ar %d -i "%s" ' % (
                        s.cam.audioSampleRate, audioFile)
            aCopy = '-c:a aac -b:a 256k'

        camDir = "%s/%s" % (startDate.strftime('%Y-%m/%d'), s.cam.name())
        fullDir = "%s%s" % (s.dvrConf['videoRecorder']['dir'], camDir)

        if not os.path.exists(fullDir):
            os.system("mkdir -p %s" % fullDir)

        fileName = "%s/%s.mp4" % (camDir, startDate.strftime('%H_%M_%S'));
        fullFileName = '%s/%s' % (s.dvrConf['videoRecorder']['dir'], fileName)
        ffmpegCmd += '-c:v copy %s -strict -2 -f mp4 %s' % (
                aCopy, fullFileName)

        try:
            os.unlink(fullFileName)
        except FileNotFoundError:
            pass

        try: # TODO
            p = subprocess.run(ffmpegCmd, shell=True, capture_output=True, text=True)
            if p.returncode:
                err = "can't encode video file %s: \n%s\n" % (
                                       fullFileName, p.stderr)
                s.log.err("openRtspHandler: %s" % err)
                s.counters.inc('encodeErr')
                raise HttpHandlerError(err)
        except UnicodeDecodeError as e:
            s.log.err('ffmpeg UnicodeDecodeError: %s' % e)

        try:
            ret = re.findall('time=(\d{2}):(\d{2}):(\d{2})', p.stderr)[0]
            hours, mins, secs = [int(i) for i in ret]
        except (IndexError, ValueError):
            err = "can't parse encoder output for file %s: \n%s\n" % (
                                   fullFileName, p.stderr)
            if 'HIDE_ERRORS' not in s.options():
                s.toAdmin(err)
            s.log.err("openRtspHandler: %s" % err)
            s.counters.inc('encoderOutputParseErr')
            s.restartAsync()
            raise HttpHandlerError(err)

        try:
            s.dvr.db.insert('videos',
                            {'cam_name': s.cam.name(),
                             'fname': fileName,
                             'duration': (hours * 3600 + mins * 60 + secs),
                             'file_size': os.path.getsize(fullFileName)},
                            {'created': 'FROM_UNIXTIME(%s)' % startTime})
            s._lastUpdate = now()
            s.counters.inc('successFiles')
        except DatabaseConnectorError as e:
            err = "Can't insert into Database: %s" % e
            s.toAdmin(err)
            try:
                os.unlink(fullFileName)
            except FileNotFoundError:
                pass
            s.counters.inc('dbInsertErr')
            raise HttpHandlerError(err)


    def updateInterval(s):
        return now() - s._lastUpdate


    def checkForRestart(s, cronWorker=None):
        if not s.isStarted():
            return
        try:
            if s._restartFlag:
                s._restartFlag = False
                return s.restart()

            if (s.updateInterval() > 60 * 2):
                s.counters.inc('restartByTimeout')
                return s.restart()
        except AppError as e:
            s.counters.inc('restartByTimeoutFail')


    def isRecording(s):
        return s.updateInterval() < 100


    def isStarted(s):
        return s.openRtspProc.isStarted()


    def size(s):
        size = s.db.query('select sum(file_size) as size ' \
                         'from videos where cam_name = "%s"' % s.cam.name())['size']
        if size == None:
            return 0
        return int(size)


    def resetStat(s):
        s.counters.reset()


    def __repr__(s):
        return "VideoRecorder:%s" % s.cam.name()

