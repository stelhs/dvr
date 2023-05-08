import socket
import threading
import json
from Task import *
from Exceptions import *
from HttpServer import *


class SkynetNotifier():
    def __init__(s, uiSubsystemName, uiServerHost, uiServerPort, clientHost):
        s.clientHost = clientHost
        s.uiServerHost = uiServerHost
        s.uiServerPort = uiServerPort
        s.uiSubsystemName = uiSubsystemName
        s.log = Syslog('SkynetNotifier')
        s.conn = None
        s.notifyQueue = []

        s.lock = threading.Lock()
        s.task = Task('SkynetNotifier_task', s.doTask, s.close)
        s.task.start()


    def doTask(s):
        while 1:
            Task.sleep(100)
            if not s.isConnected():
                try:
                    s.connect()
                except SkynetNotifierConnectionError:
                    Task.sleep(3000)
                    continue

            with s.lock:
                n = len(s.notifyQueue)

            if not n:
                s.task.waitMessage(60)
                with s.lock:
                    n = len(s.notifyQueue)

            if not n:
                continue

            with s.lock:
                queue = s.notifyQueue

            for item in queue:
                try:
                    (type, data) = item
                    s.send(type, data)
                except SkynetNotifierError:
                    s.close()
                    continue

                with s.lock:
                    s.notifyQueue.remove(item)


    def notify(s, type, data):
        with s.lock:
            s.notifyQueue.append((type, data))
            s.task.sendMessage('event')


    def send(s, type, data):
        if not s.conn:
            return False

        d = {'source': s.uiSubsystemName,
             'type': type,
             'data': data}
        payload = json.dumps(d)

        header = "POST /send_event http/1.1\r\n"
        header += "Host: %s\r\n" % s.clientHost
        header += "Connection: keep-alive\r\n"
        header += "Content-Type: text/json\r\n"
        header += "Content-Length: %s\r\n" % len(payload.encode('utf-8'))
        header += "\r\n"
        try:
            s.conn.send((header + payload).encode('utf-8'))
            resp = s.conn.recv(16535).decode()
        except Exception as e:
            raise SkynetNotifierSendError(s.log,
                        "Can`t sending event data to Skynet server: %s" % e)

        parts = HttpServer.parseHttpResponce(resp)
        if not parts:
            raise SkynetNotifierResponseError(s.log,
                        'No valid responce from UI server: %s' % resp)

        version, respCode, attrs, body = parts
        if version != 'HTTP/1.1':
            raise SkynetNotifierResponseError(s.log,
                        'Incorrect version of HTTP protocol: %s' % version)

        if respCode != '200':
            raise SkynetNotifierResponseError(s.log,
                        'Incorrect responce code: %s' % respCode)

        try:
            jsonResp = json.loads(body)
            if jsonResp['status'] != 'ok':
                s.log.err("status is not OK: %s" % body)
                return False

        except KeyError as e:
            raise SkynetNotifierResponseError(s.log,
                        "field '%s' is absent in responce" % e)
        except JSONDecodeError as e:
            raise SkynetNotifierResponseError(s.log,
                        "Can't decode responce as JSON: %s" % body)


    def connect(s):
        if s.conn:
            return
        try:
            s.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.conn.connect((s.uiServerHost, s.uiServerPort))
            s.conn.settimeout(2.0)
        except Exception as e:
            s.conn = None
            raise SkynetNotifierConnectionError(s.log,
                    'Can`t connect to Skynet server: %s' % e) from e


    def isConnected(s):
        return s.conn != None


    def close(s):
        if not s.conn:
            return
        try:
            s.connectnn.shutdown(socket.SHUT_RDWR)
            s.conn.close()
        except:
            pass
        s.conn = None


