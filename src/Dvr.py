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
from Camcorder import *



class Dvr():
    def __init__(s):
        s.log = Syslog("Dvr")
        s.conf = ConfDvr()
        s.dvrConf = s.conf.dvr
        Task.setErrorCb(s.taskExceptionHandler)

        s.tc = TelegramClient(s.conf.telegram)
        s.db = DatabaseConnector(s, s.conf.db)
        s.cron = Cron()
        s.sp = SubProcess()
        s.varStorage = VarStorage(s, 'dvr.json')

        s.cron.register('Timelapse_day', ('0 0 4 * * *',))
        s.cron.register('Timelapse_week', ('0 30 4 * * 6',))
        s.cron.register('Timelapse_month', ('0 0 5 1 * *',))
        s.cron.register('Timelapse_year', ('0 0 6 25 12 *',))

        s._camList = [Camcorder(s, conf, s.dvrConf) for conf in s.conf.camcorders]

        s.httpServer = HttpServer(s.dvrConf['httpServer']['host'],
                                  s.dvrConf['httpServer']['port'],
                                  s.dvrConf['httpServer']['wwwDir'])
        s.httpHandlers = Dvr.HttpHandlers(s, s.httpServer)
        s.cron.register('videoCleaner', ('* */10 * * * *',)).addCb(s.videoCleaner)


    def camcorders(s):
        return s._camList


    def toAdmin(s, msg):
        s.tc.sendToChat('stelhs', "DVR: %s" % msg)


    def taskExceptionHandler(s, task, errMsg):
        s.toAdmin("%s: task '%s' error:\n%s" % (task.name(), task.name(), errMsg))


    def camcorder(s, name):
        for cam in s._camList:
            if cam.name() == name:
                return cam
        raise CamcorderNotRegistredError('Camcorder %s is not registred' % name)


    def start(s):
        for cam in s.camcorders():
            try:
                print("Start camcorder %s" % cam.name())
                cam.start()
            except AppError as e:
                print("Can't start recording %s: %s" % (cam.name(), e))
            Task.sleep(3000)


    def stop(s):
        for cam in s.camcorders():
            try:
                print("Stop camcorder %s" % cam.name())
                cam.stop()
            except AppError as e:
                print("%s stop recording error: %s" % (cam.name(), e))


    def finishTimelapses(s):
        def do():
            print("Start timelapce creation")
            for cam in s.camcorders():
                cam.finishTimelapsesSync()
            print("Finished timelapce creation")
        s.finishTimelapsesTask = Task.asyncRun('finishTimelapses', do)


    def totalVideoDuration(s):
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


    def totalVideoSize(s):
        return sum([c.vr.size() for c in s.camcorders()])


    def videoCleaner(s, cronWorker=None):
        gb = (1024 * 1024 * 1024)
        mb = (1024 * 1024)
        size = s.totalVideoSize()
        sizeGb = int(size / gb)
        maxSize = s.dvrConf['videoRecorder']['maxSizeGb'] * gb

        s.log.info("video storage size: %.1fGb, max_storage_size: %.1fGb,\n" % (
                         sizeGb, s.dvrConf['videoRecorder']['maxSizeGb']))

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

            fname = "%s/%s" % (s.dvrConf['videoRecorder']['dir'], row['fname'])

            s.log.info("remove %s, size = %.2fMb, sizeToDelete: %.2f Mb\n" % (
                        fname, row['file_size'] / mb, sizeToDelete / mb))
            try:
                os.unlink(fname)
            except OSError as e:
                s.log.err("Can't remove %s: %s" % (fname, e))

            s.rmEmptyDirs(s.dvrConf['videoRecorder']['dir'], True)

            s.db.query('delete from videos where id = %d' % row['id'])
            sizeToDelete -= row['file_size']

        s.log.info("%d files were removed\n" % cnt)


    def rmEmptyDirs(s, dir, preserve=False):
        ld = os.listdir(dir)
        if not len(ld) and not preserve:
            os.rmdir(dir)
            return
        for path in (os.path.join(dir, p) for p in ld):
            st = os.stat(path)
            if stat.S_ISDIR(st.st_mode):
                s.rmEmptyDirs(path)


    def stat(s):
        return {'vrTotalSize': s.totalVideoSize(),
                'vrTotalDuration': s.totalVideoDuration(),
                'camcorders': [c.stat() for c in s.camcorders()]}


    def destroy(s):
        s.stop()
        s.httpServer.destroy()
        s.sp.destroy()


    def __repr__(s):
        text = "List camcorders:\n"
        def camInfo(c):
            nonlocal text
            text += "\t%s:%s:%s\n" % (c.name(), 'started' if c.vr.isStarted() else 'stopped',
                                      'recording' if c.vr.isRecording() else 'not_recording')
        list(map(camInfo, s.camcorders()))
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
                cam = s.dvr.camcorder('cName')
                cam.start()
            except AppError as e:
                raise HttpHandlerError('Can`t start camcorder %s: %s' % (cName, e))


        def stopHandler(s, args, conn):
            cName = args['cname']
            try:
                cam = s.dvr.camcorder('cName')
                cam.stop()
            except AppError as e:
                raise HttpHandlerError('Can`t stop camcorder %s: %s' % (cName, e))


        def statHandler(s, args, conn):
            try:
                return s.dvr.stat()
            except AppError as e:
                raise HttpHandlerError('Can`t gettitng DVR status: %s' % e)


        def openRtspHandler(s, args, conn):
            conf = s.dvr.dvrConf
            cName = args['cname']
            try:
                cam = s.dvr.camcorder(args['cname'])
            except CamcorderNotRegistredError as e:
                s.log.err("openRtspHandler: call unregistred camcorder: %s" % e)
                raise HttpHandlerError(str(e))
            cam.vr.openRtspHandler(args, conn)


        def createJpegFramesHandler(s, args, conn):
            camList = []
            cnt = 0
            for cam in s.dvr.camcorders():
                cnt += 1
                if not cam.fr.isStarted():
                    continue
                try:
                    fname = cam.captureJpegFrame()
                    url = "%s%s/%s/%s" % (
                           s.dvr.dvrConf['httpServer']['globalHttp'],
                           s.dvr.dvrConf['frameRecorder']['jpegFramesWww'],
                           cam.name(), os.path.basename(fname))
                    camList.append({'index': cnt,
                                    'img_url': url})
                except AppError:
                    continue
            return {"camcorders": camList}


