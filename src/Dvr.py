import os, re
from Task import *
from Syslog import *
from Exceptions import *
from HttpServer import *
from ConfDvr import *
from TimerCounter import *
from TelegramClient import *
from SkynetNotifier import *
from PeriodicNotifier import *
from DatabaseConnector import *
from Camera import *



class Dvr():
    def __init__(s):
        s.log = Syslog("Dvr")
        s.conf = ConfDvr()
        s.tc = TelegramClient(s.conf.telegram)
        Task.setErrorCb(s.taskExceptionHandler)
        s.db = DatabaseConnector(s, s.conf.db)

        s._camerasList = []
        for camConf in s.conf.cameras:
            cam = Camera(s, camConf['name'], camConf)
            s._camerasList.append(cam)


        s.httpServer = HttpServer(s.conf.dvr['host'],
                                  s.conf.dvr['port'])
        s.httpHandlers = Dvr.HttpHandlers(s, s.httpServer)

#        s.sn = SkynetNotifier('dvr',
#                              s.conf.dvr['skynetServer']['host'],
#                              s.conf.dvr['skynetServer']['port'],
#                              s.conf.dvr['host'])

#        s.periodicNotifier = PeriodicNotifier()
#        s.skynetPortsUpdater = s.periodicNotifier.register("ports", s.skynetUpdatePortsHandler, 2000)



    def cameras(s):
        return s._camerasList


    def toAdmin(s, msg):
        s.tc.sendToChat('stelhs', "DVR: %s" % msg)


    def taskExceptionHandler(s, task, errMsg):
        s.toAdmin("%s: task '%s' error:\n%s" % (task.name(), task.name(), errMsg))


    def camera(s, name):
        for cam in s._camerasList:
            if cam.name() == name:
                return cam
        raise CameraNotRegistredError('Camera %s is not registred' % name)


    def start(s):
        for cam in s.cameras():
            try:
                if not cam.isRecording():
                    print("Start recording %s" % cam.name())
                    cam.start()
            except OpenRtspAlreadyStarted:
                pass
            Task.sleep(3000)


    def stop(s):
        for cam in s.cameras():
            try:
                if cam.isRecording():
                    cam.stop()
            except OpenRtspAlreadyStopped:
                pass


    def archiveDuration(s):
        row = s.db.query("select UNIX_TIMESTAMP(created) as start " \
                     "from videos order by id asc limit 1")
        if 'start' not in row:
            return 0;
        start = row['start']

        row = s.db.query("select UNIX_TIMESTAMP(created) as end " \
                         "from videos order by id desc limit 1")
        if 'end' not in row:
            return 0

        end = row['end']
        return end - start


    def destroy(s):
        s.stop()
        s.httpServer.destroy()


    class HttpHandlers():
        def __init__(s, dvr, httpServer):
            s.dvr = dvr
            s.httpServer = httpServer
            s.httpServer.setReqHandler("GET", "/open_rtsp_cb", s.openRtspHandler,
                                       ('cname', 'start_time', 'video_file'), errLog=True)
            s.log = Syslog("Dvr.HttpHandlers")
            s.toAdmin = dvr.toAdmin


        def openRtspHandler(s, args, conn):
            conf = s.dvr.conf.dvr
            cName = args['cname']
            try:
                cam = s.dvr.camera(args['cname'])
            except CameraNotRegistredError as e:
                s.log.err("openRtspHandler: call unregistred camera: %s" % e)
                raise HttpHandlerError(str(e))

            startTime = int(args['start_time'])
            videoFile = args['video_file']
            audioFile = args['audio_file'] if 'audio_file' in args else None

            startDate = datetime.datetime.fromtimestamp(startTime)

            try:
                vsize = os.path.getsize(videoFile)
            except FileNotFoundError:
                s.log.err("openRtspHandler: camera %s: file %s not exist" % (
                          cam.name(), videoFile))
                cam.restart()
                raise HttpHandlerError("file %s not exist" % videoFile)

            if vsize == 0:
                s.log.err("openRtspHandler: camera %s: file %s has null size" % (
                          cam.name(), videoFile))
                cam.restart()
                raise HttpHandlerError("file %s null size" % videoFile)

            ffmpegCmd = 'ffmpeg -i %s ' % videoFile
            aCopy = ''
            if audioFile:
                if cam.audioCodec == 'PCMA':
                    ffmpegCmd += '-f alaw -ar %d -i "%s" ' % (
                            cam.audioSampleRate, audioFile)
                aCopy = '-c:a aac -b:a 256k'

            camDir = "%s/%s" % (startDate.strftime('%Y-%m/%d'), cName)
            fullDir = "%s%s" % (conf['storage']['dir'], camDir)

            if not os.path.exists(fullDir):
                os.system("mkdir -p %s" % fullDir)

            fileName = "%s/%s.mp4" % (camDir, startDate.strftime('%H_%M_%S'));
            fullFileName = '%s/%s' % (conf['storage']['dir'], fileName)

            ffmpegCmd += '-c:v copy %s -strict -2 -f mp4 %s' % (
                    aCopy, fullFileName)

            #print("ffmpegCmd = %s" % ffmpegCmd)

            try:
                os.unlink(fullFileName)
            except FileNotFoundError:
                pass

            p = subprocess.run(ffmpegCmd, shell=True, capture_output=True, text=True)

            if p.returncode:
                err = "can't encode video file %s: \n%s\n" % (
                                       fullFileName, p.stderr)
                s.log.err("openRtspHandler: %s" % err)
                raise HttpHandlerError(err)

            r = re.findall('time=(\d{2}):(\d{2}):(\d{2})', p.stderr);
            if not r or not len(r) or len(r[0]) < 3:
                if not cam.hideErrors:
                    s.toAdmin("can't parse encoder output for file %s, " %
                                        fullFileName)
                Task.setTimeout("camera_%s_async_restart" % cam.name(), 500, cam.restart)
                err = "can't parse encoder output for file %s: \n%s\n" % (
                                       fullFileName, p.stderr)
                s.log.err("openRtspHandler: %s" % err)
                raise HttpHandlerError(err)

            hours = int(r[0][0])
            mins = int(r[0][1])
            secs = int(r[0][2])

            duration = hours * 3600 + mins * 60 + secs
            s.dvr.db.insert('videos',
                            {'cam_name': cName,
                             'fname': fileName,
                             'duration': duration,
                             'file_size': os.path.getsize(fullFileName)},
                            {'created': 'FROM_UNIXTIME(%s)' % startTime})



