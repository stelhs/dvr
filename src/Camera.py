import subprocess, os, psutil, re
from Syslog import *
from Task import *
from Exceptions import *
from HttpServer import *



class Camera():
    def __init__(s, dvr, name, conf, dvrConf):
        s.dvr = dvr
        s.db = dvr.db
        s._name = name
        s.conf = conf
        s.dvrConf = dvrConf
        s.log = Syslog("Camera_%s" % name)
        s._restartFlag = False
        s.pidDir = s.dvr.conf.dvr['pidDir']
        s.audioCodec = conf['audio']['codec'] if 'audio' in conf else None
        s.audioSampleRate = conf['audio']['sampleRate'] if 'audio' in conf else None

        s._restartCnt = 0
        s._openrtspNoFileCnt = 0
        s._openrtspNullSizeCnt = 0
        s._encoderOutputParseErrCnt = 0
        s._dbInsertErrCnt = 0

        s.stopFlag = True
        if 'HIDE_ERRORS' in s.options():
            s.log.mute('error')
            s.log.mute('info')


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


    def start(s):
        if s.isStarted():
            raise OpenRtspAlreadyStarted(s.log,
                    "Can't starting camera '%s' recording. " \
                    "Recording already was started" % s.name())

        s.stopFlag = False
        Task.asyncRunSingle('recording_%s' % s.name(), s.openRtspTask)


    def stop(s):
        if not s.isStarted():
            raise OpenRtspAlreadyStopped(s.log,
                    "Can't stopping camera '%s' recording. " \
                    "Recording already was stopped" % s.name())
        s.stopFlag = True
        cnt = 0
        while (s.isRecording()):
            if cnt > 10:
                raise OpenRtspCanNotStopError(s.log,
                    "Can't stop camera '%s'. s.isRecording() = %s" % (
                        s.name(), s.isRecording()))
            pid = s.pid()
            if not pid:
                break

            os.system('kill -9 %s' % s.pid())
            cnt += 1
            Task.sleep(2000)

        s.log.info("camera '%s' recording has stopped" % s.name())


    def restart(s):
        try:
            s.stop()
        except OpenRtspAlreadyStopped:
            pass
        s.start()
        s._restartCnt += 1


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


    def openRtspTask(s):
        openRtspCmd = "/usr/local/bin/openRTSP " \
              "-D 20 -K -b 1000000 -P %d -c -t -f %d " \
              "-F %s -N %s -j %s %s" % (
                   s.dvr.conf.dvr['videoFileDuration'],
                   s.conf['video']['frameRate'],
                   s.name(), '/root/dvr/src/open_rtsp_callback.sh',
                   s.pidFileName(), s.rtsp())

        while True:
            s.log.info("camera '%s' recording has started" % s.name())
            try:
                p = subprocess.run(openRtspCmd.split(' '), shell=False,
                                   capture_output=True, text=True, encoding="ascii")
                if p.returncode:
                    s.log.err("openRTSP fallout with code %d. stdout: '%s'. stderr: '%s'" % (
                              p.returncode, p.stdout, p.stderr))
            except UnicodeDecodeError as e:
                s.log.err('openRTSP UnicodeDecodeError: %s' % e)

            try:
                os.unlink(s.pidFileName())
            except FileNotFoundError:
                pass

            if s.stopFlag:
                return
            Task.sleep(1000)


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
        except DatabaseConnectorError as e:
            err = "Can't insert into Database: %s" % e
            s.toAdmin(err)
            try:
                os.unlink(fullFileName)
            except FileNotFoundError:
                pass
            s._dbInsertErrCnt += 1
            raise HttpHandlerError(err)



    def isRecording(s):
        if not os.path.exists(s.pidFileName()):
            return False

        pid = s.pid()
        if not psutil.pid_exists(pid):
            return False

        try:
            proc = psutil.Process(pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                return False
        except psutil.NoSuchProcess:
            return False
        return True


    def isStarted(s):
        return not s.stopFlag


    def size(s):
        size = s.db.query('select sum(file_size) as size ' \
                         'from videos where cam_name = "%s"' % s.name())['size']
        if size == None:
            return 0
        return int(size)


    def checkForRestart(s):
        if s._restartFlag:
            s._restartFlag = False
            s.restart()


    def __repr__(s):
        return "Dvr.Camera:%s" % s.name()




