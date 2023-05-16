import subprocess, os, re, pathlib, shutil, datetime
import inotify.adapters
from Syslog import *
from Task import *
from Exceptions import *
from HttpServer import *



class Camera():
    def __init__(s, dvr, name, conf, dvrConf):
        s.dvr = dvr
        s.db = dvr.db
        s.sp = dvr.sp
        s._name = name
        s.conf = conf
        s.dvrConf = dvrConf
        s.log = Syslog("Camera_%s" % name)
        s.restartLock = threading.Lock()
        s._restartFlag = False
        s._startFlag = False
        s._lastUpdate = 0
        s.pidDir = s.dvr.conf.dvr['pidDir']
        s.audioCodec = conf['audio']['codec'] if 'audio' in conf else None
        s.audioSampleRate = conf['audio']['sampleRate'] if 'audio' in conf else None

        s._restartCnt = 0
        s._openrtspNoFileCnt = 0
        s._openrtspNullSizeCnt = 0
        s._encoderOutputParseErrCnt = 0
        s._dbInsertErrCnt = 0
        s._openrtspKillCnt = 0

        s._restartTime = 0

        if 'HIDE_ERRORS' in s.options():
            s.log.mute('error')
            s.log.mute('info')

        s.openRtspCmd = "/usr/local/bin/openRTSP " \
                        "-D 20 -K -b 1000000 -P %d -c -t -f %d " \
                        "-F %s -N %s -j %s %s" % (
                           s.dvr.conf.dvr['videoFileDuration'],
                           s.conf['video']['frameRate'],
                           s.name(), '/root/dvr/src/open_rtsp_callback.sh',
                           s.pidFileName(), s.rtsp())
        s.openRtspProc = s.sp.register("openRTSP:%s" % s.name(),
                                       s.openRtspCmd, s.openRtspOnKillCb)

        s.imageRecorder = Camera.ImageRecording(s)


    def options(s):
        return s.conf['options']


    def name(s):
        return s._name


    def description(s):
        return s.conf['desc']


    def toAdmin(s, msg):
        s.dvr.toAdmin("camera %s: %s" % (s.name(), msg))


    def pidFileName(s):
        return '%s/camera_%s_pid' % (s.pidDir, s.name())


    def pid(s):
        fname = s.pidFileName()
        if not os.path.exists(fname):
            return None

        try:
            pid = int(fileGetContent(fname))
        except FileError:
            return None
        return pid


    def rtsp(s):
        return s.conf['rtsp']


    def openRtspOnKillCb(s, proc):
        if s._startFlag:
            s.log.info("openRTSP %s killed" % s.name())
            s._openrtspKillCnt += 1
            proc.start()


    def start(s):
        if s.isStarted():
            raise OpenRtspAlreadyStarted(s.log,
                    "Can't starting camera '%s' recording. " \
                    "Recording already was started" % s.name())
        s.openRtspProc.start()
        s.imageRecorder.start()
        s._startFlag = True


    def stop(s):
        if not s.isStarted():
            raise OpenRtspAlreadyStopped(s.log,
                    "Can't stopping camera '%s' recording. " \
                    "Recording already was stopped" % s.name())
        s._startFlag = False
        if s.imageRecorder.isStarted():
            s.imageRecorder.stop()
        if s.openRtspProc.isStarted():
            s.openRtspProc.stop()
        s.log.info("camera '%s' recording has stopped" % s.name())


    def restart(s):
        with s.restartLock:
            try:
                s.stop()
            except OpenRtspAlreadyStopped:
                pass
            s.start()
            s._restartCnt += 1
            s._restartTime = now()


    def restartAsync(s):
        s._restartFlag = True


    def stat(s):
        return {'name': s.name(),
                'desc': s.description(),
                'restartCnt': s._restartCnt,
                'openrtspNoFileCnt': s._openrtspNoFileCnt,
                'openrtspNullSizeCnt': s._openrtspNullSizeCnt,
                'encoderOutputParseErrCnt': s._encoderOutputParseErrCnt,
                'dbInsertErrCnt': s._dbInsertErrCnt,
                'isRecordStarted': s.isStarted(),
                'isRecording': s.isRecording(),
                'dataSize': s.size(),
                'duration': s.duration()}


    def resetStat(s):
        s._restartCnt = 0
        s._openrtspNoFileCnt = 0
        s._openrtspNullSizeCnt = 0
        s._encoderOutputParseErrCnt = 0
        s._dbInsertErrCnt = 0
        s._openrtspKillCnt = 0


    def size(s):
        row = s.db.query("select sum(file_size) as size "\
                         "from videos where cam_name = '%s'" %
                         s.name())
        if 'size' not in row:
            return 0
        return int(row['size'])


    def duration(s):
        row = s.db.query("select sum(duration) as sum from videos "\
                         "where cam_name = '%s' and file_size is not NULL" %
                          s.name());
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
            s._openrtspNoFileCnt += 1
            s.restartAsync()
            raise HttpHandlerError("file %s not exist" % videoFile)

        if vsize == 0:
            s.log.err("openRtspHandler: file %s has null size" % videoFile)
            s._openrtspNullSizeCnt += 1
            s.restartAsync()
            raise HttpHandlerError("file %s null size" % videoFile)

        ffmpegCmd = 'ffmpeg -i %s ' % videoFile
        aCopy = ''
        if audioFile:
            if s.audioCodec == 'PCMA':
                ffmpegCmd += '-f alaw -ar %d -i "%s" ' % (
                        s.audioSampleRate, audioFile)
            aCopy = '-c:a aac -b:a 256k'

        camDir = "%s/%s" % (startDate.strftime('%Y-%m/%d'), s.name())
        fullDir = "%s%s" % (s.dvrConf['storage']['dir'], camDir)

        if not os.path.exists(fullDir):
            os.system("mkdir -p %s" % fullDir)

        fileName = "%s/%s.mp4" % (camDir, startDate.strftime('%H_%M_%S'));
        fullFileName = '%s/%s' % (s.dvrConf['storage']['dir'], fileName)
        ffmpegCmd += '-c:v copy %s -strict -2 -f mp4 %s' % (
                aCopy, fullFileName)

        try:
            os.unlink(fullFileName)
        except FileNotFoundError:
            pass

        try:
            p = subprocess.run(ffmpegCmd, shell=True, capture_output=True, text=True)
            if p.returncode:
                err = "can't encode video file %s: \n%s\n" % (
                                       fullFileName, p.stderr)
                s.log.err("openRtspHandler: %s" % err)
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
            s._encoderOutputParseErrCnt += 1
            s.restartAsync()
            raise HttpHandlerError(err)

        try:
            s.dvr.db.insert('videos',
                            {'cam_name': s.name(),
                             'fname': fileName,
                             'duration': (hours * 3600 + mins * 60 + secs),
                             'file_size': os.path.getsize(fullFileName)},
                            {'created': 'FROM_UNIXTIME(%s)' % startTime})
            s._lastUpdate = now()
        except DatabaseConnectorError as e:
            err = "Can't insert into Database: %s" % e
            s.toAdmin(err)
            try:
                os.unlink(fullFileName)
            except FileNotFoundError:
                pass
            s._dbInsertErrCnt += 1
            raise HttpHandlerError(err)


    def updateInterval(s):
        return now() - s._lastUpdate


    def isRecording(s):
        return s.updateInterval() < 100


    def isStarted(s):
        return s._startFlag


    def size(s):
        size = s.db.query('select sum(file_size) as size ' \
                         'from videos where cam_name = "%s"' % s.name())['size']
        if size == None:
            return 0
        return int(size)


    def captureJpegFrame(s):
        return s.imageRecorder.exportJpegFrame()


    def checkForRestart(s):
        if s._restartFlag:
            s._restartFlag = False
            return s.restart()

        if (s.updateInterval() > 60 * 2) and ((now() - s._restartTime) > 60 * 2):
            return s.restart()


    def __repr__(s):
        return "Dvr.Camera:%s" % s.name()




    class ImageRecording():
        def __init__(s, cam):
            s.dvrConf = cam.dvrConf
            s.cam = cam
            s.sp = cam.sp
            s.cron = cam.dvr.cron
            s.varStorage = cam.dvr.varStorage
            s.captureLock = threading.Lock()
            s._startFlag = False
            s._lastFile = None
            s._lastUpdate = 0

            s.log = cam.log

            s._timeLapseCnt = s.varStorage.key('/cam_%s/timeLapseCnt' % cam.name(), 1)
            s._restartCnt = 0

            s.tmpImagesDir = '%s/%s' % (s.dvrConf['storage']['imageTmpDir'], s.cam.name())
            s.timelapseDir = '%s/%s' % (s.dvrConf['storage']['timelapseDir'], s.cam.name())
            s.jpegFramesDir = '%s/%s' % (s.dvrConf['storage']['jpegFramesDir'], s.cam.name())

            s.ffmpegCmd = "/usr/bin/ffmpeg -nostdin -loglevel error " \
                          "-rtsp_transport tcp -use_wallclock_as_timestamps 1 " \
                          "-skip_frame nokey " \
                          "-i %s -vsync 0 %s/img_%%04d.jpg" % (s.cam.rtsp(), s.tmpImagesDir)

            s.cleanTmp()
            s.ffmpegProc = s.sp.register("imageRecorder:%s" % s.cam.name(),
                                          s.ffmpegCmd, s.ffmpegKillCb)

            s.inotify = inotify.adapters.Inotify()
            s.inotify.add_watch(s.tmpImagesDir)
            s.inotifyTask = Task.asyncRun('ImageRecorderInotify_%s' % s.cam.name(),
                                          s.inotifyDo)
            s.cron.register('imageRecorderRestarter_%s' % cam.name(),
                            '*/1 * * * *', s.checkForRestart)


        def start(s):
            if s.isStarted():
                raise ImageRecordingAlreadyStartedError(s.log,
                        "Can't starting camera '%s' image recorder: " \
                        "Already was started" % s.name())
            s._startFlag = True
            s.ffmpegProc.start()


        def stop(s):
            if not s.isStarted():
                raise ImageRecordingAlreadyStoppedError(s.log,
                        "Can't stopping camera '%s' image recorder: " \
                        "Already was stopped" % s.name())
            s._startFlag = False
            if s.ffmpegProc.isStarted():
                s.ffmpegProc.stop()
            s.log.info("camera '%s' recording has stopped" % s.cam.name())


        def restart(s):
            try:
                s.stop()
            except (ImageRecordingAlreadyStoppedError, SubProcessCantStopError):
                pass
            Task.sleep(1000)
            s.start()
            s._restartCnt += 1


        def isStarted(s):
            return s._startFlag


        def ffmpegKillCb(s, proc):
            if not s._startFlag:
                return
            s.cleanTmp()
            s._lastFile = None
            proc.start()


        def cleanTmp(s):
            pathlib.Path(s.tmpImagesDir).mkdir(parents=True, exist_ok=True)
            pathlib.Path(s.timelapseDir).mkdir(parents=True, exist_ok=True)
            pathlib.Path(s.jpegFramesDir).mkdir(parents=True, exist_ok=True)
            for i in os.listdir(s.tmpImagesDir):
                try:
                    os.remove("%s/%s" % (s.tmpImagesDir, i))
                except IOError:
                    pass


        def inotifyDo(s):
            while 1:
                Task.sleep(0)
                for event in s.inotify.event_gen(yield_nones=False, timeout_s=1):
                    (_, evType, _, filename) = event
                    if 'IN_CLOSE_WRITE' in evType:
                        s.processImage(filename)


        def processImage(s, tmpFname):
            s._lastUpdate = now()
            with s.captureLock:
                prevFile = s._lastFile
                s._lastFile = "%s/%s" % (s.tmpImagesDir, tmpFname)
                if prevFile:
                    try:
                        os.unlink(prevFile)
                    except OSError:
                        pass


        def exportJpegFrame(s):
            with s.captureLock:
                imgFileName = s.imgFileName()
                fdate = datetime.datetime.fromtimestamp(s._lastUpdate)
                exportFName = "%s/%s" % (s.jpegFramesDir, fdate.strftime("%Y_%d_%m_%H_%M_%S.jpg"))
                try:
                    return shutil.copyfile(imgFileName, exportFName)
                except OSError as e:
                    raise ImageRecordingNoImageError(s.log, "Can`t move %s to %s: %s" % (
                                                     imgFileName, exportFName, e))


        def imgFileName(s):
            if not s._lastFile:
                raise ImageRecordingNoImageError(s.log, 'captured image file not found')

            if s.updateInterval() > 60:
                raise ImageRecordingNoImageError(s.log, 'captured image file outdated')
            return s._lastFile


        def updateInterval(s):
            return now() - s._lastUpdate


        def timelapseCb(s):
            if not s.isStarted():
                return

            with s.captureLock:
                try:
                    imgFileName = s.imgFileName()
                except ImageRecordingError:
                    return

                newFName = "%s/%d.jpg" % (s.timelapseDir, s._timeLapseCnt.val)
                try:
                    shutil.copyfile(imgFileName, newFName)
                    s._timeLapseCnt.set(s._timeLapseCnt.val + 1)
                except OSError:
                    s.log.err("Can`t move %s to %s: %s" % (imgFileName, newFName))


        def checkForRestart(s):
            if s.updateInterval() > 60:
                return s.restart()


