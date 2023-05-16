import os, stat
from Task import *
from Cron import *
from Syslog import *
from Exceptions import *
from HttpServer import *
from ConfDvr import *
from TimerCounter import *
from TelegramClient import *
from SkynetNotifier import *
from PeriodicNotifier import *
from DatabaseConnector import *
from SubProcess import *
from VarStorage import *
from Camera import *



class Dvr():
    def __init__(s):
        s.log = Syslog("Dvr")
        s.conf = ConfDvr()
        s.tc = TelegramClient(s.conf.telegram)
        Task.setErrorCb(s.taskExceptionHandler)
        s.db = DatabaseConnector(s, s.conf.db)
        s.cron = Cron()
        s.sp = SubProcess()

        s.varStorage = VarStorage(s, 'dvr.json')

        s._camerasList = []
        for camConf in s.conf.cameras:
            cam = Camera(s, camConf['name'], camConf, s.conf.dvr)
            s._camerasList.append(cam)

        s.httpServer = HttpServer(s.conf.dvr['host'],
                                  s.conf.dvr['port'],
                                  s.conf.dvr['wwwDir'])
        s.httpHandlers = Dvr.HttpHandlers(s, s.httpServer)

        s.cron.register('videoCleaner', '*/10 * * * *', s.cleaner)
        s.stopperTask = Task.setPeriodic('stopper', 1000, s.stopperCb)
        s.timelapseTask = Task.setPeriodic('ImageRecorderTmelapse',
                                           8000, s.timelapseCb)


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
                if not cam.isStarted() and 'RECORDING' in cam.options():
                    print("Start recording %s" % cam.name())
                    cam.start()
            except OpenRtspAlreadyStarted:
                pass
            Task.sleep(3000)


    def stop(s):
        for cam in s.cameras():
            try:
                if cam.isStarted():
                    print("Stop %s" % cam.name())
                    cam.stop()
            except AppError as e:
                print("%s stop error: %s" % (cam.name(), e))


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


    def size(s):
        return sum([c.size() for c in s.cameras()])


    def cleaner(s):
        gb = (1024 * 1024 * 1024)
        mb = (1024 * 1024)
        size = s.size()
        sizeGb = int(size / gb)
        maxSize = s.conf.dvr['storage']['maxSizeGb'] * gb

        s.log.info("video storage size: %.1fGb, max_storage_size: %.1fGb,\n" % (
                         sizeGb, s.conf.dvr['storage']['maxSizeGb']))

        if size < maxSize:
            return

        sizeToDelete = size - maxSize
        sizeToDeleteGb = int(sizeToDelete / gb)
        s.log.info("video storage size: %.1fGb, need to delete size: %.1fGb,\n" % (
                         sizeGb, sizeToDeleteGb))

        cnt = 0
        while sizeToDelete > 0:
            cnt += 1
            row = s.db.query('select id, fname, file_size from videos ' \
                             'where created < (now() - interval 5 minute) ' \
                             'order by id asc limit 1')
            if 'id' not in row:
                s.log.err("Can't select video file")
                return

            fname = "%s/%s" % (s.conf.dvr['storage']['dir'], row['fname'])

            s.log.info("remove %s, size = %.2fMb, sizeToDelete: %.2f Mb\n" % (
                        fname, row['file_size'] / mb, sizeToDelete / mb))
            try:
                os.unlink(fname)
            except OSError as e:
                s.log.err("Can't remove %s: %s" % (fname, e))

            s.rmEmptyDirs(s.conf.dvr['storage']['dir'], True)

            s.db.query('delete from videos where id = %d' % row['id'])
            sizeToDelete -= row['file_size']

        s.log.info("%d files were removed\n" % cnt)


    def timelapseCb(s, task):
        for cam in s.cameras():
            cam.imageRecorder.timelapseCb()


    def rmEmptyDirs(s, dir, preserve=False):
        ld = os.listdir(dir)
        if not len(ld) and not preserve:
            os.rmdir(dir)
            return
        for path in (os.path.join(dir, p) for p in ld):
            st = os.stat(path)
            if stat.S_ISDIR(st.st_mode):
                s.rmEmptyDirs(path)


    def stopperCb(s, task):
        for cam in s.cameras():
            if not cam.isStarted():
                continue
            cam.checkForRestart()


    def stat(s):
        return {'totalSize': s.size(),
                'totalDuration': s.archiveDuration(),
                'cameras': [c.stat() for c in s.cameras()]}


    def destroy(s):
        s.stop()
        s.httpServer.destroy()
        s.sp.destroy()


    def __repr__(s):
        text = "List cameras:\n"
        def camInfo(c):
            nonlocal text
            text += "\t%s:%s:%s\n" % (c.name(), 'started' if c.isStarted() else 'stopped',
                                      'recording' if c.isRecording() else 'not_recording')
        list(map(camInfo, s.cameras()))
        return text



    class HttpHandlers():
        def __init__(s, dvr, httpServer):
            s.dvr = dvr
            s.log = Syslog("Dvr.HttpHandlers")
            s.toAdmin = dvr.toAdmin
            s.httpServer = httpServer
            s.httpServer.setReqHandler("GET", "/open_rtsp_cb", s.openRtspHandler,
                                       ('cname', 'start_time', 'video_file'), errLog=True)
            s.httpServer.setReqHandler("GET", "/dvr/start", s.startHandler, ('cname',))
            s.httpServer.setReqHandler("GET", "/dvr/stop", s.stopHandler, ('cname',))
            s.httpServer.setReqHandler("GET", "/dvr/stat", s.statHandler)
            s.httpServer.setReqHandler("GET", "/dvr/create_jpeg_frames", s.createJpegFramesHandler)


        def startHandler(s, args, conn):
            cName = args['cname']
            try:
                cam = s.dvr.camera('cName')
                cam.start()
            except AppError as e:
                raise HttpHandlerError('Can`t start camera %s: %s' % (cName, e))


        def stopHandler(s, args, conn):
            cName = args['cname']
            try:
                cam = s.dvr.camera('cName')
                cam.stop()
            except AppError as e:
                raise HttpHandlerError('Can`t stop camera %s: %s' % (cName, e))


        def statHandler(s, args, conn):
            try:
                return s.dvr.stat()
            except AppError as e:
                raise HttpHandlerError('Can`t gettitng DVR status: %s' % e)


        def openRtspHandler(s, args, conn):
            conf = s.dvr.conf.dvr
            cName = args['cname']
            try:
                cam = s.dvr.camera(args['cname'])
            except CameraNotRegistredError as e:
                s.log.err("openRtspHandler: call unregistred camera: %s" % e)
                raise HttpHandlerError(str(e))
            cam.openRtspHandler(args, conn)


        def createJpegFramesHandler(s, args, conn):
            camList = []
            cnt = 0
            for cam in s.dvr.cameras():
                cnt += 1
                if not cam.isStarted():
                    continue
                try:
                    fname = cam.captureJpegFrame()
                except AppError:
                    continue
                url = "%s%s/%s/%s" % (
                       s.dvr.conf.dvr['globalHttp'],
                       s.dvr.conf.dvr['storage']['jpegFramesWww'],
                       cam.name(), os.path.basename(fname))
                camList.append({'index': cnt,
                                'img_url': url})
            return {"cameras": camList}


